"""通用工具：HTTP 会话、日期处理、文本清洗、条目结构。"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("radar")

USER_AGENT = "AI-Frontier-Radar/1.0 (+https://github.com/; research digest bot)"


def make_session(headers: dict[str, str] | None = None) -> requests.Session:
    """带自动重试的 HTTP 会话（429/5xx 会退避重试）。"""
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT})
    if headers:
        s.headers.update(headers)
    return s


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: Any) -> datetime | None:
    """尽量宽松地解析各种日期字符串，返回 UTC datetime。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # 去掉过长的小数秒（Python 3.10 及以下不支持 >6 位）
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def days_ago(n: float) -> datetime:
    return utcnow() - timedelta(days=n)


_ws = re.compile(r"\s+")


def clean_text(text: str | None, max_chars: int | None = None) -> str:
    if not text:
        return ""
    t = _ws.sub(" ", str(text)).strip()
    if max_chars and len(t) > max_chars:
        cut = t[:max_chars]
        # 尽量在句号或空格处截断
        p = max(cut.rfind(". "), cut.rfind("。"))
        if p > max_chars * 0.6:
            cut = cut[: p + 1]
        else:
            sp = cut.rfind(" ")
            if sp > max_chars * 0.8:
                cut = cut[:sp]
        t = cut.rstrip() + "…"
    return t


_gh_url = re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.I)


def find_github_url(*texts: str | None) -> str | None:
    """从摘要 / 备注中找出第一个 GitHub 仓库链接（论文的代码实现）。"""
    for t in texts:
        if not t:
            continue
        m = _gh_url.search(t)
        if m:
            url = m.group(0).rstrip(".,;)")
            if url.lower().endswith(".git"):
                url = url[:-4]
            return url
    return None


def make_item(
    *,
    id: str,
    type: str,
    source: str,
    title: str,
    url: str,
    date: datetime | None,
    summary: str = "",
    authors: list[str] | None = None,
    links: dict[str, str] | None = None,
    metrics: dict[str, float] | None = None,
    tags: list[str] | None = None,
    categories: list[str] | None = None,
    hint_topics: list[str] | None = None,
) -> dict[str, Any]:
    """统一的条目结构。前端只依赖这里的字段。

    type:   paper | repo | model | dataset
    source: arxiv | github | huggingface | biorxiv | medrxiv
    hint_topics: 由“哪个主题的查询抓到的”给出的提示，分类时会加分
    """
    return {
        "id": id,
        "type": type,
        "sources": [source],
        "title": clean_text(title),
        "url": url,
        "date": iso(date) if date else None,
        "summary": summary,
        "authors": authors or [],
        "links": {k: v for k, v in (links or {}).items() if v},
        "metrics": {k: v for k, v in (metrics or {}).items() if v is not None},
        "tags": tags or [],
        "categories": categories or [],
        "_hints": sorted(set(hint_topics or [])),
    }


class RateLimiter:
    """保证两次调用之间至少间隔 interval 秒。"""

    def __init__(self, interval: float):
        self.interval = interval
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last = time.monotonic()
