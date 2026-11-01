"""Hugging Face 抓取器：每日论文（HF Papers）+ 热门模型 / 数据集。

Papers with Code 已于 2025 年 7 月停止运营并重定向到 HF Trending Papers，
HF 每日论文自带 GitHub 代码链接和社区点赞数，正好替代它的“论文 ↔ 代码”功能。
"""
from __future__ import annotations

from datetime import timedelta

from ..common import (RateLimiter, clean_text, find_github_url, log, make_item,
                      make_session, parse_date, utcnow)

BASE = "https://huggingface.co/api"
_DROP_TAG_PREFIX = ("region:", "license:", "base_model:", "dataset:", "doi:",
                    "endpoints_compatible", "autotrain_compatible", "text-generation-inference",
                    "deploy:", "format:", "size_categories:", "modality:", "library:")


def parse_daily_papers(data: list, summary_max: int, fallback_date=None) -> list[dict]:
    items = []
    for entry in data or []:
        p = entry.get("paper") if isinstance(entry, dict) and "paper" in entry else entry
        if not isinstance(p, dict) or not p.get("id"):
            continue
        aid = str(p["id"]).strip()
        abstract = clean_text(p.get("summary") or entry.get("summary"))
        authors = [a.get("name", "") for a in (p.get("authors") or []) if isinstance(a, dict)]
        repo = p.get("githubRepo") or find_github_url(abstract)
        items.append(make_item(
            id=f"arxiv:{aid}",
            type="paper",
            source="huggingface",
            title=p.get("title") or entry.get("title") or aid,
            url=f"https://arxiv.org/abs/{aid}",
            date=parse_date(p.get("publishedAt") or entry.get("publishedAt")) or fallback_date,
            summary=clean_text(abstract, summary_max),
            authors=[a for a in authors if a],
            links={
                "pdf": f"https://arxiv.org/pdf/{aid}",
                "code": repo,
                "hf": f"https://huggingface.co/papers/{aid}",
                "home": p.get("projectPage"),
            },
            metrics={
                "upvotes": p.get("upvotes"),
                "comments": entry.get("numComments") if isinstance(entry, dict) else None,
                "stars": p.get("githubStars"),
            },
            tags=[k for k in (p.get("ai_keywords") or [])][:6],
        ))
        if p.get("ai_summary"):
            items[-1]["tldr"] = clean_text(p["ai_summary"], 300)
    return items


_NOISE = ("finetun", "fine-tun", "medium")


def _token_match(repo_id: str, term: str) -> bool:
    import re
    name = repo_id.split("/")[-1].lower()
    for tok in re.split(r"[-_.\s/]+", name):
        if tok.startswith(term.lower()) and not tok.startswith(_NOISE):
            return True
    return False


def _clean_tags(tags: list[str]) -> tuple[list[str], list[str]]:
    keep, arxiv_ids = [], []
    for t in tags or []:
        if t.startswith("arxiv:"):
            arxiv_ids.append(t.split(":", 1)[1])
        elif not t.startswith(_DROP_TAG_PREFIX) and len(t) < 40:
            keep.append(t)
    return keep, arxiv_ids


def parse_repos(data: list, kind: str, hint_topic: str | None = None) -> list[dict]:
    """kind: model | dataset"""
    items = []
    for m in data or []:
        rid = m.get("id") or m.get("modelId")
        if not rid:
            continue
        tags, arxiv_ids = _clean_tags(m.get("tags") or [])
        pipeline = m.get("pipeline_tag")
        desc_bits = [b for b in (pipeline, m.get("library_name")) if b]
        summary = clean_text(m.get("description") or "", 400) or " / ".join(desc_bits)
        prefix = "" if kind == "model" else "datasets/"
        items.append(make_item(
            id=f"hf-{kind}:{rid.lower()}",
            type=kind,
            source="huggingface",
            title=rid,
            url=f"https://huggingface.co/{prefix}{rid}",
            date=parse_date(m.get("createdAt") or m.get("lastModified")),
            summary=summary,
            authors=[rid.split("/")[0]] if "/" in rid else [],
            links={"paper": f"https://arxiv.org/abs/{arxiv_ids[0]}" if arxiv_ids else None},
            metrics={"likes": m.get("likes"), "downloads": m.get("downloads"),
                     "trending": m.get("trendingScore")},
            tags=([pipeline] if pipeline else []) + [t for t in tags if t != pipeline][:7],
            hint_topics=[hint_topic] if hint_topic else [],
        ))
    return items


def fetch(cfg: dict, topics: list[dict], summary_max: int) -> list[dict]:
    hcfg = cfg["huggingface"]
    session = make_session()
    limiter = RateLimiter(1.0)
    out: list[dict] = []

    # 1) 每日论文
    today = utcnow().date()
    for d in range(hcfg.get("daily_papers_days", 4)):
        day = today - timedelta(days=d)
        limiter.wait()
        try:
            r = session.get(f"{BASE}/daily_papers",
                            params={"date": day.isoformat(), "limit": 100}, timeout=40)
            r.raise_for_status()
            items = parse_daily_papers(r.json(), summary_max,
                                       fallback_date=parse_date(day.isoformat()))
            log.info("HF 每日论文 %s → %d", day, len(items))
            out.extend(items)
        except Exception as exc:
            log.warning("HF 每日论文 %s 失败: %s", day, exc)

    # 2) 全站热门模型 / 数据集
    for kind, n in (("model", hcfg.get("trending_models", 60)),
                    ("dataset", hcfg.get("trending_datasets", 30))):
        if not n:
            continue
        limiter.wait()
        try:
            r = session.get(f"{BASE}/{kind}s", params={"sort": "trendingScore", "direction": -1,
                                                       "limit": n}, timeout=40)
            r.raise_for_status()
            items = parse_repos(r.json(), kind)
            log.info("HF 热门%s → %d", "模型" if kind == "model" else "数据集", len(items))
            out.extend(items)
        except Exception as exc:
            log.warning("HF 热门 %s 失败: %s", kind, exc)

    # 3) 各主题按关键词搜模型
    per = hcfg.get("per_topic_search", 15)
    for topic in topics:
        for term in topic.get("hf_search", []):
            limiter.wait()
            try:
                r = session.get(f"{BASE}/models", params={"search": term, "sort": "trendingScore",
                                                          "direction": -1, "limit": per}, timeout=40)
                r.raise_for_status()
                # 只保留名称里某个词以搜索词开头的模型，避免 "fin" 命中 "finetune" 之类
                hits = [m for m in r.json() if _token_match(m.get("id", ""), term)]
                out.extend(parse_repos(hits, "model", topic["id"]))
            except Exception as exc:
                log.warning("HF 搜索 %s 失败: %s", term, exc)
    return out
