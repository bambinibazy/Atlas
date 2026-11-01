"""arXiv 抓取器：按主题检索式拉取最新提交的论文（Atom API）。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..common import (RateLimiter, clean_text, days_ago, find_github_url, log,
                      make_item, make_session, parse_date)

API = "https://export.arxiv.org/api/query"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_version = re.compile(r"v\d+$")


def arxiv_id_from_url(url: str) -> str:
    """http://arxiv.org/abs/2410.01234v2 -> 2410.01234 ；也兼容旧式 hep-th/9901001。"""
    aid = url.split("/abs/")[-1]
    return _version.sub("", aid)


def parse_feed(xml_text: str, summary_max: int, hint_topic: str | None = None) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for e in root.findall("a:entry", NS):
        raw_id = (e.findtext("a:id", default="", namespaces=NS) or "").strip()
        if "/abs/" not in raw_id:  # 出错时 arXiv 会返回一个错误 entry
            continue
        aid = arxiv_id_from_url(raw_id)
        title = e.findtext("a:title", default="", namespaces=NS)
        abstract = clean_text(e.findtext("a:summary", default="", namespaces=NS))
        comment = e.findtext("arxiv:comment", default="", namespaces=NS) or ""
        authors = [clean_text(a.findtext("a:name", default="", namespaces=NS))
                   for a in e.findall("a:author", NS)]
        cats = [c.get("term") for c in e.findall("a:category", NS) if c.get("term")]
        primary = e.find("arxiv:primary_category", NS)
        if primary is not None and primary.get("term") in cats:
            cats.remove(primary.get("term"))
            cats.insert(0, primary.get("term"))
        pdf = None
        for link in e.findall("a:link", NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf = link.get("href")
        published = parse_date(e.findtext("a:published", default="", namespaces=NS))
        items.append(make_item(
            id=f"arxiv:{aid}",
            type="paper",
            source="arxiv",
            title=title,
            url=f"https://arxiv.org/abs/{aid}",
            date=published,
            summary=clean_text(abstract, summary_max),
            authors=[a for a in authors if a],
            links={
                "pdf": (pdf or f"https://arxiv.org/pdf/{aid}").replace("http://", "https://"),
                "code": find_github_url(comment, abstract),
                "hf": f"https://huggingface.co/papers/{aid}",
            },
            categories=cats,
            tags=[],
            hint_topics=[hint_topic] if hint_topic else [],
        ))
    return items


def fetch(cfg: dict, topics: list[dict], summary_max: int) -> list[dict]:
    acfg = cfg["arxiv"]
    session = make_session()
    limiter = RateLimiter(acfg.get("delay_seconds", 3.5))
    cutoff = days_ago(acfg.get("lookback_days", 10))
    out: list[dict] = []
    for topic in topics:
        for q in topic.get("arxiv_queries", []):
            limiter.wait()
            params = {
                "search_query": q,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": 0,
                "max_results": acfg.get("max_results_per_query", 80),
            }
            try:
                r = session.get(API, params=params, timeout=60)
                r.raise_for_status()
                items = parse_feed(r.text, summary_max, topic["id"])
            except Exception as exc:  # 单条查询失败不影响整体
                log.warning("arXiv 查询失败 [%s] %s: %s", topic["id"], q[:60], exc)
                continue
            fresh = [it for it in items if it["date"] and parse_date(it["date"]) >= cutoff]
            log.info("arXiv [%s] %d 条（近期 %d）", topic["id"], len(items), len(fresh))
            out.extend(fresh)
    return out
