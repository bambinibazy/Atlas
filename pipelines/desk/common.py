"""通用工具：HTTP 会话、时区日期、文本清洗、统一条目结构、数据源状态记录。"""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("decisiondesk")

CST = ZoneInfo("Asia/Shanghai")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


class _Session(requests.Session):
    """默认连接超时 6 秒：被墙或不可达的站点快速失败，不拖慢整次运行。"""

    def request(self, method, url, **kw):
        t = kw.get("timeout") or 20
        if not isinstance(t, tuple):
            kw["timeout"] = (min(6, t), t)
        return super().request(method, url, **kw)


def make_session(headers: dict[str, str] | None = None, retries: int = 2) -> requests.Session:
    s = _Session()
    retry = Retry(total=retries, connect=1, read=1, backoff_factor=1.0,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    if headers:
        s.headers.update(headers)
    return s


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: Any, tz: ZoneInfo | timezone = timezone.utc) -> datetime | None:
    """宽松解析日期。没有时区信息的字符串按 tz 解释（中文接口一般是北京时间）。
    纯数字视为 Unix 时间戳（秒或毫秒）。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        n = float(value)
        if n > 1e12:
            n /= 1000
        if n < 1e8:  # 太小的数字不是时间戳
            return None
        return datetime.fromtimestamp(n, tz=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    s = s.replace("/", "-") if re.match(r"^\d{4}/\d", s) else s
    fmts = (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M")
    for fmt in fmts:
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def days_ago(n: float) -> datetime:
    return utcnow() - timedelta(days=n)


_tag = re.compile(r"<[^>]+>")
_ws = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    t = _tag.sub(" ", str(text))
    t = html.unescape(t)
    return _ws.sub(" ", t).strip()


def clean_text(text: str | None, max_chars: int | None = None) -> str:
    t = strip_html(text)
    if max_chars and len(t) > max_chars:
        cut = t[:max_chars]
        p = max(cut.rfind("。"), cut.rfind(". "), cut.rfind("；"))
        if p > max_chars * 0.6:
            cut = cut[: p + 1]
        t = cut.rstrip() + "…"
    return t


_bracket_title = re.compile(r"^【([^】]{2,80})】\s*")


def split_bracket_title(text: str) -> tuple[str, str]:
    """中文快讯常见格式“【标题】正文”，拆成 (标题, 正文)。没有【】则返回 ("", 原文)。"""
    m = _bracket_title.match(text or "")
    if m:
        return m.group(1).strip(), text[m.end():].strip()
    return "", (text or "").strip()


def make_item(*, id: str, type: str, source: str, title: str, url: str | None,
              date: datetime | None, summary: str = "", markets: list[str] | None = None,
              important: bool = False, tags: list[str] | None = None,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一条目结构，前端只依赖这些字段。

    type:    flash（快讯）| news（新闻）| filing（公告/财报）| policy（官方政策发布）
    source:  数据源 id，如 cls / sina / cnbc-top / sec
    markets: 来源自带的市场标签，分类器还会根据内容补充
    """
    item = {
        "id": id,
        "type": type,
        "sources": [source],
        "title": clean_text(title),
        "url": url or "",
        "date": iso(date) if date else None,
        "summary": summary,
        "markets": list(dict.fromkeys(markets or [])),
        "important": bool(important),
        "tags": tags or [],
    }
    if extra:
        item.update(extra)
    return item


class RateLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last = time.monotonic()


class Breaker:
    """逐个请求的循环里使用：连续失败 max_fail 次或超过时间预算就放弃剩余请求。"""

    def __init__(self, max_fail: int = 3, budget_s: float = 120):
        self.max_fail, self.fails = max_fail, 0
        self.deadline = time.monotonic() + budget_s

    def open(self) -> bool:
        return self.fails >= self.max_fail or time.monotonic() > self.deadline

    def record(self, ok: bool) -> None:
        self.fails = 0 if ok else self.fails + 1


class SourceStatus:
    """记录每个数据源本次是否成功、抓到多少条，写进 meta.json 方便排查。"""

    def __init__(self):
        self.status: dict[str, dict[str, Any]] = {}

    def ok(self, sid: str, count: int, name: str | None = None) -> None:
        self.status[sid] = {"ok": True, "count": count, "name": name or sid, "at": iso(utcnow())}

    def fail(self, sid: str, err: Exception | str, name: str | None = None) -> None:
        msg = str(err)[:200]
        log.warning("数据源 %s 失败：%s", sid, msg)
        self.status[sid] = {"ok": False, "count": 0, "name": name or sid, "error": msg, "at": iso(utcnow())}


_cjk = re.compile(r"[㐀-鿿]")


class KeywordMatcher:
    """关键词匹配。英文按整词匹配（"oil" 不会命中 "boil"）；中文直接子串匹配；
    以 "=" 开头的关键词区分大小写。"""

    def __init__(self, keywords: Iterable[str]):
        self.patterns: list[tuple[str, re.Pattern]] = []
        for kw in keywords:
            kw = str(kw)
            sensitive = kw.startswith("=")
            word = kw[1:] if sensitive else kw
            body = re.escape(word).replace(r"\ ", r"\s+")
            if not _cjk.search(word):
                body = r"(?<![A-Za-z0-9])" + body + r"(?:s|es)?(?![A-Za-z0-9])"
            self.patterns.append((word, re.compile(body, 0 if sensitive else re.IGNORECASE)))

    def matches(self, text: str) -> set[str]:
        if not text:
            return set()
        return {kw for kw, p in self.patterns if p.search(text)}

    def any(self, text: str) -> bool:
        return bool(text) and any(p.search(text) for _, p in self.patterns)
