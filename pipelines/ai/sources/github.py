"""GitHub 抓取器：按主题关键词搜索最近新建、增长快的仓库。

在 GitHub Actions 里运行时自动使用 GITHUB_TOKEN（每分钟 30 次搜索）；
本地没有 token 时限速为每分钟 10 次，会自动放慢。
"""
from __future__ import annotations

import os

from ..common import (RateLimiter, clean_text, days_ago, log, make_item,
                      make_session, parse_date)

API = "https://api.github.com/search/repositories"


def parse_search(data: dict, summary_max: int, hint_topic: str | None = None) -> list[dict]:
    items = []
    for r in data.get("items", []):
        if r.get("fork") or r.get("archived"):
            continue
        full = r.get("full_name") or ""
        desc = clean_text(r.get("description") or "", summary_max)
        topics = r.get("topics") or []
        items.append(make_item(
            id=f"github:{full.lower()}",
            type="repo",
            source="github",
            title=full,
            url=r.get("html_url") or f"https://github.com/{full}",
            date=parse_date(r.get("created_at")),
            summary=desc,
            authors=[(r.get("owner") or {}).get("login", "")],
            links={"code": r.get("html_url"), "home": r.get("homepage") or None},
            metrics={
                "stars": r.get("stargazers_count"),
                "forks": r.get("forks_count"),
            },
            tags=[t for t in topics][:8] + ([r["language"]] if r.get("language") else []),
            hint_topics=[hint_topic] if hint_topic else [],
        ))
    return items


def fetch(cfg: dict, topics: list[dict], summary_max: int) -> list[dict]:
    gcfg = cfg["github"]
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    session = make_session(headers)
    limiter = RateLimiter(2.2 if token else 6.5)
    since = days_ago(gcfg.get("created_within_days", 45)).strftime("%Y-%m-%d")
    min_stars = gcfg.get("min_stars", 20)
    per = gcfg.get("per_query", 25)

    jobs: list[tuple[str, str | None]] = []
    for topic in topics:
        for q in topic.get("github_queries", []):
            jobs.append((f"{q} created:>{since} stars:>={min_stars}", topic["id"]))
    for t in gcfg.get("trending_topics", []):
        jobs.append((f"topic:{t} created:>{since} stars:>={min_stars * 5}", None))

    out: list[dict] = []
    for query, hint in jobs:
        limiter.wait()
        try:
            r = session.get(API, params={"q": query, "sort": "stars", "order": "desc",
                                         "per_page": per}, timeout=40)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                log.warning("GitHub 速率受限，跳过剩余查询")
                break
            r.raise_for_status()
            items = parse_search(r.json(), summary_max, hint)
        except Exception as exc:
            log.warning("GitHub 查询失败 %s: %s", query, exc)
            continue
        log.info("GitHub [%s] %s → %d", hint or "trending", query.split(" created")[0], len(items))
        out.extend(items)
    return out
