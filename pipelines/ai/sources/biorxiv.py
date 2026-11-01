"""bioRxiv / medRxiv 抓取器：拉取最近几天的预印本，只保留与 AI 相关的。"""
from __future__ import annotations

from urllib.parse import quote

from ..classify import KeywordMatcher
from ..common import (RateLimiter, clean_text, days_ago, find_github_url, log,
                      make_item, make_session, parse_date, utcnow)

API = "https://api.biorxiv.org/details"


def parse_collection(data: dict, server: str, ai: KeywordMatcher, summary_max: int) -> list[dict]:
    items = []
    for p in data.get("collection", []) or []:
        title = p.get("title") or ""
        abstract = clean_text(p.get("abstract"))
        if not ai.any_match(f"{title} {abstract}"):
            continue
        doi = p.get("doi", "")
        version = p.get("version") or "1"
        category = (p.get("category") or "").strip()
        authors = [clean_text(a) for a in (p.get("authors") or "").split(";") if a.strip()]
        hint = "brain" if "neuro" in category.lower() else "medicine"
        items.append(make_item(
            id=f"{server}:{doi}",
            type="paper",
            source=server,
            title=title,
            url=f"https://www.{server}.org/content/{doi}v{version}",
            date=parse_date(p.get("date")),
            summary=clean_text(abstract, summary_max),
            authors=authors,
            links={
                "pdf": f"https://www.{server}.org/content/{doi}v{version}.full.pdf",
                "code": find_github_url(abstract),
            },
            categories=[category] if category else [],
            hint_topics=[hint],
        ))
    return items


def _page_through(session, limiter, server, start, end, category, max_pages):
    cursor, pages = 0, 0
    while pages < max_pages:
        url = f"{API}/{server}/{start}/{end}/{cursor}/json"
        if category:
            url += "?category=" + quote(category.replace(" ", "_"))
        limiter.wait()
        r = session.get(url, timeout=60)
        r.raise_for_status()
        data = r.json()
        yield data
        msg = (data.get("messages") or [{}])[0]
        count = int(msg.get("count") or 0)
        total = int(msg.get("total") or 0)
        cursor += count
        pages += 1
        if count == 0 or cursor >= total:
            break


def fetch(cfg: dict, topics: list[dict], summary_max: int, ai: KeywordMatcher) -> list[dict]:
    bcfg = cfg["biorxiv"]
    session = make_session()
    limiter = RateLimiter(1.0)
    start = days_ago(bcfg.get("lookback_days", 4)).strftime("%Y-%m-%d")
    end = utcnow().strftime("%Y-%m-%d")
    max_pages = bcfg.get("max_pages_per_server", 25)

    jobs = [("biorxiv", c) for c in bcfg.get("biorxiv_categories", [])] + [("medrxiv", None)]
    out: list[dict] = []
    for server, category in jobs:
        n_before = len(out)
        try:
            for data in _page_through(session, limiter, server, start, end, category, max_pages):
                out.extend(parse_collection(data, server, ai, summary_max))
        except Exception as exc:
            log.warning("%s %s 失败: %s", server, category or "全部", exc)
        log.info("%s [%s] AI 相关 → %d", server, category or "全部", len(out) - n_before)
    return out
