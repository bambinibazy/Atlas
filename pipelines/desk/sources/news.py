"""资讯抓取：RSS/Atom 源（可经 RSSHub 生成）+ 网页列表页（政府网站、四大等，通用规则）。"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import warnings

import feedparser
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # 列表页偶尔是 XML，用 HTML 解析即可

from ..common import (CST, RateLimiter, SourceStatus, clean_text, days_ago, log, make_session,
                      parse_date, utcnow)


def news_item(*, id: str, source: str, title: str, url: str, date, summary: str = "",
              topics: list[str] | None = None, region: str = "intl", kind: str = "news",
              via: str | None = None) -> dict:
    """kind: news 文章 | policy 官方政策/监管发布"""
    item = {
        "id": id, "source": source, "title": clean_text(title), "url": url,
        "date": date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if date else None,
        "summary": summary, "topics": list(dict.fromkeys(topics or [])), "region": region, "kind": kind,
    }
    if via:
        item["via"] = via
    return item


# ---------------- RSS ----------------
_gn_suffix = re.compile(r"\s+-\s+[^-]{2,60}$")


def _entry_date(e):
    for key in ("published_parsed", "updated_parsed"):
        st = e.get(key)
        if st:
            return datetime(*st[:6], tzinfo=timezone.utc)
    return parse_date(e.get("published") or e.get("updated"))


def parse_feed(content, src: dict, smax: int) -> list[dict]:
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        link, title = e.get("link") or "", e.get("title") or ""
        if not (link and title):
            continue
        if src.get("via") == "Google News":
            title = _gn_suffix.sub("", title)  # Google News 标题末尾带“ - 来源名”
            summary = ""                         # 摘要只是标题和来源的 HTML，丢弃
        else:
            summary = clean_text(e.get("summary") or e.get("description") or "", smax)
        uid = hashlib.sha1((e.get("id") or link).encode()).hexdigest()[:16]
        out.append(news_item(id=f"{src['id']}:{uid}", source=src["id"], title=title, url=link,
                             date=_entry_date(e), summary=summary, topics=src.get("topics"),
                             region=src.get("region", "intl"), kind=src.get("type", "news"),
                             via=src.get("via")))
    return out


def rsshub_bases() -> list[str]:
    """RSSHub 实例：工作流里临时启动的本地实例优先，失败再试公共实例。"""
    bases = [os.getenv("RSSHUB_BASE", "http://localhost:1200")]
    bases += os.getenv("RSSHUB_FALLBACKS", "https://rsshub.app").split(",")
    return [b.strip().rstrip("/") for b in bases if b.strip()]


def keyword_ok(item: dict, src: dict) -> bool:
    """综合类来源只保留含任一 keywords 的条目；含 exclude_keywords 的丢弃。"""
    text = f"{item['title']} {item.get('summary', '')}".lower()
    kws = src.get("keywords")
    if kws and not any(k.lower() in text for k in kws):
        return False
    bad = src.get("exclude_keywords")
    return not (bad and any(k.lower() in text for k in bad))


def _short_error(base: str, exc: Exception) -> str:
    """把 requests 的长报错压缩成“localhost:1200 超时”“rsshub.app HTTP 403”这样的短句。"""
    host = base.split("://", 1)[-1]
    text = str(exc)
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status:
        return f"{host} HTTP {status}"
    if "timed out" in text.lower() or "timeout" in type(exc).__name__.lower() or "ReadTimeout" in text:
        return f"{host} 超时"
    if "Connection refused" in text or "Failed to establish" in text or "NameResolution" in text:
        return f"{host} 无法连接"
    return f"{host} {text[:60]}"


def _route_site(route: str) -> str:
    return route.strip("/").split("/")[0]  # /thepaper/list/1 → thepaper


def _get_feed(s, src: dict, dead_sites: dict | None = None):
    if not src.get("route"):
        r = s.get(src["url"], timeout=25)
        r.raise_for_status()
        return r.content
    site = _route_site(src["route"])
    if dead_sites is not None and site in dead_sites:
        # 同一网站的上一个路由已经超时，这次直接跳过，避免每个栏目各等一分钟
        raise RuntimeError(f"跳过：同网站的其他栏目刚失败（{dead_sites[site]}）")
    errors, timeouts = [], 0
    for base in rsshub_bases():
        try:
            r = s.get(base + src["route"], timeout=30)
            r.raise_for_status()
            if feedparser.parse(r.content).entries:
                return r.content
            errors.append(f"{base.split('://', 1)[-1]} 返回空内容")
        except Exception as exc:  # noqa: BLE001
            errors.append(_short_error(base, exc))
            timeouts += "超时" in errors[-1] or "HTTP 403" in errors[-1]
    msg = "RSSHub 失败：" + "；".join(errors)
    if dead_sites is not None and timeouts:
        dead_sites[site] = "；".join(errors)
    raise RuntimeError(msg)


def fetch_rss(sources: list[dict], smax: int, status: SourceStatus, max_age_days: float) -> list[dict]:
    s = make_session({"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    lim = RateLimiter(0.6)
    cutoff = days_ago(max_age_days)
    out = []
    dead_sites: dict[str, str] = {}
    for src in sources:
        if not src.get("enabled", True):
            continue
        lim.wait()
        try:
            content = _get_feed(s, src, dead_sites)
            items = [i for i in parse_feed(content, src, smax)
                     if (not i["date"] or parse_date(i["date"]) >= cutoff) and keyword_ok(i, src)]
            items = items[: src.get("limit", 60)]
            log.info("RSS %s → %d", src["name"], len(items))
            status.ok(src["id"], len(items), src["name"])
            out.extend(items)
        except Exception as exc:
            status.fail(src["id"], exc, src["name"])
    return out


# ---------------- 政府网站列表页 ----------------
_date_in_url = [
    re.compile(r"t(20\d{2})(\d{2})(\d{2})_"),          # TRS 系统：t20251218_3979556.htm
    re.compile(r"/(20\d{2})(\d{2})(\d{2})/"),           # /20260227/xxx.html
    re.compile(r"/(20\d{2})-(\d{2})-(\d{2})/"),
]
_date_text = re.compile(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})")


def _date_near(a, pat=None) -> datetime | None:
    href = a.get("href", "")
    for p in _date_in_url:
        m = p.search(href)
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=CST)
    node = a
    for _ in range(3):  # 在链接本身和最多 3 层父元素的文字里找日期
        if node is not a and pat is not None and sum(
                1 for x in node.find_all("a", href=True) if pat.search(x["href"])) > 1:
            break  # 父元素已经包含多条链接（到了列表容器），再往上会取到别的条目的日期
        text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
        m = _date_text.search(text.replace(a.get_text(" ", strip=True), " ", 1) if node is not a else text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=CST)
            except ValueError:
                pass
        node = node.parent
        if node is None:
            break
    return None


def parse_gov_list(html: str, src: dict, base_url: str) -> list[dict]:
    """通用列表页：链接地址符合 link_pattern（且不符合 exclude_pattern）的 <a> 即为一条。
    政府网站默认 kind=policy、region=cn；四大等机构的洞察页在配置里写 kind: news。"""
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(src["link_pattern"])
    exc = re.compile(src["exclude_pattern"]) if src.get("exclude_pattern") else None
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        if not pat.search(href) or href in seen or (exc and exc.search(href)):
            continue
        title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        if len(title) < 6:  # “更多”“详情”之类的链接
            continue
        seen.add(href)
        uid = hashlib.sha1(href.encode()).hexdigest()[:16]
        out.append(news_item(id=f"{src['id']}:{uid}", source=src["id"], title=title, url=href,
                             date=_date_near(a, pat), topics=src.get("topics"),
                             region=src.get("region", "cn"), kind=src.get("kind", "policy")))
    return [i for i in out if keyword_ok(i, src)][: src.get("limit", 60)]


def fetch_gov(sources: list[dict], status: SourceStatus, max_age_days: float) -> list[dict]:
    s = make_session()
    lim = RateLimiter(1.0)
    cutoff = days_ago(max_age_days)
    out = []
    for src in sources:
        if not src.get("enabled", True):
            continue
        lim.wait()
        try:
            r = s.get(src["url"], timeout=25)
            r.raise_for_status()
            r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
            items = parse_gov_list(r.text, src, r.url)
            if not items:
                raise ValueError("页面里没有找到符合规则的链接，可能网站已改版")
            # 没有解析到日期的条目：以第一次抓到的时间为准（run.py 里处理）
            items = [i for i in items if not i["date"] or parse_date(i["date"]) >= cutoff]
            log.info("列表页 %s → %d", src["name"], len(items))
            status.ok(src["id"], len(items), src["name"])
            out.extend(items)
        except Exception as exc:
            status.fail(src["id"], exc, src["name"])
    return out
