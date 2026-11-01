"""通用 RSS / Atom 新闻源。配置里加一行即可新增来源。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import feedparser

from ..common import (RateLimiter, SourceStatus, clean_text, days_ago, log, make_item, make_session,
                      parse_date)


def _entry_date(e) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = e.get(key)
        if st:
            return datetime(*st[:6], tzinfo=timezone.utc)
    return parse_date(e.get("published") or e.get("updated"))


def parse_feed(content: bytes | str, feed_cfg: dict, smax: int) -> list[dict]:
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        link = e.get("link") or ""
        title = e.get("title") or ""
        if not (link and title):
            continue
        uid = e.get("id") or link
        digest = hashlib.sha1(uid.encode("utf-8")).hexdigest()[:16]
        summary = e.get("summary") or e.get("description") or ""
        tags = [t.get("term") for t in (e.get("tags") or []) if t.get("term")][:5]
        out.append(make_item(
            id=f"rss:{digest}", type=feed_cfg.get("type", "news"), source=feed_cfg["id"],
            title=title, url=link, date=_entry_date(e), summary=clean_text(summary, smax),
            markets=feed_cfg.get("markets") or [], tags=tags,
        ))
    return out


def fetch(feeds: list[dict], smax: int, status: SourceStatus, max_age_days: float = 10) -> list[dict]:
    s = make_session({"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    lim = RateLimiter(0.5)
    cutoff = days_ago(max_age_days)
    out: list[dict] = []
    for f in feeds:
        if not f.get("enabled", True):
            continue
        lim.wait()
        try:
            r = s.get(f["url"], timeout=25)
            r.raise_for_status()
            items = [i for i in parse_feed(r.content, f, smax)
                     if not i["date"] or parse_date(i["date"]) >= cutoff]
            if not items and b"<" not in r.content[:200]:
                raise ValueError("返回内容不是 RSS/XML")
            log.info("RSS %s → %d", f["name"], len(items))
            status.ok(f["id"], len(items), f["name"])
            out.extend(items)
        except Exception as exc:
            status.fail(f["id"], exc, f["name"])
    return out
