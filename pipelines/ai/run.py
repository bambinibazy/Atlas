"""入口：抓取所有来源 → 合并去重 → 分类 → 与历史数据合并 → 写出 site/data/*.json

用法：
    python -m pipelines.ai.run                 # 抓取全部来源
    python -m pipelines.ai.run --only arxiv,github
    python -m pipelines.ai.run --reclassify    # 不联网，只按当前配置重新分类已有数据
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from .classify import Classifier, KeywordMatcher
from .common import iso, log, parse_date, utcnow

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config" / "ai" / "topics.yaml"
DATA_DIR = ROOT / "site" / "ai" / "data"
ALL_SOURCES = ("arxiv", "github", "huggingface", "biorxiv")


def load_config(path: Path = CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def merge_item(old: dict, new: dict) -> dict:
    """同一条目来自多个来源（如 arXiv + HF 每日论文）时合并信息。"""
    m = dict(old)
    m["sources"] = sorted(set(old.get("sources", [])) | set(new.get("sources", [])))
    if not m.get("title"):
        m["title"] = new.get("title", "")
    if len(new.get("summary", "")) > len(m.get("summary", "")):
        m["summary"] = new["summary"]
    if new.get("tldr") and not m.get("tldr"):
        m["tldr"] = new["tldr"]
    if not m.get("authors") and new.get("authors"):
        m["authors"] = new["authors"]
    links = dict(new.get("links", {}))
    links.update({k: v for k, v in old.get("links", {}).items() if v})
    m["links"] = links
    metrics = dict(old.get("metrics", {}))
    for k, v in new.get("metrics", {}).items():
        metrics[k] = v  # 新抓到的数值更新旧值（星数、点赞会增长）
    m["metrics"] = metrics
    m["tags"] = list(dict.fromkeys(old.get("tags", []) + new.get("tags", [])))[:10]
    m["categories"] = list(dict.fromkeys(old.get("categories", []) + new.get("categories", [])))
    m["_hints"] = sorted(set(old.get("_hints", [])) | set(new.get("_hints", [])))
    d_old, d_new = parse_date(old.get("date")), parse_date(new.get("date"))
    if d_new and (not d_old or d_new < d_old):
        m["date"] = new["date"]
    return m


def dedupe(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:
        out[it["id"]] = merge_item(out[it["id"]], it) if it["id"] in out else it
    return out


def load_existing() -> dict[str, dict]:
    path = DATA_DIR / "items.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {it["id"]: it for it in data.get("items", [])}
    except Exception as exc:
        log.warning("读取历史数据失败，将从零开始：%s", exc)
        return {}


def collect(cfg: dict, only: set[str]) -> list[dict]:
    from .sources import arxiv, biorxiv, github, huggingface

    s = cfg["settings"]
    topics = cfg["topics"]
    smax = s.get("summary_max_chars", 900)
    items: list[dict] = []
    runners = {
        "arxiv": lambda: arxiv.fetch(s, topics, smax),
        "github": lambda: github.fetch(s, topics, smax),
        "huggingface": lambda: huggingface.fetch(s, topics, smax),
        "biorxiv": lambda: biorxiv.fetch(s, topics, smax, KeywordMatcher(cfg.get("ai_keywords", []))),
    }
    for name in ALL_SOURCES:
        if name not in only or not s.get(name, {}).get("enabled", True):
            continue
        log.info("==== 抓取 %s ====", name)
        try:
            got = runners[name]()
            log.info("%s 共 %d 条", name, len(got))
            items.extend(got)
        except Exception as exc:
            log.error("%s 整体失败：%s", name, exc)
    return items


def build(cfg: dict, fresh: list[dict], existing: dict[str, dict]) -> tuple[list[dict], dict]:
    s = cfg["settings"]
    now = utcnow()
    now_s = iso(now)
    merged = dict(existing)
    for iid, it in dedupe(fresh).items():
        if iid in merged:
            keep_seen = merged[iid].get("first_seen", now_s)
            merged[iid] = merge_item(merged[iid], it)
            merged[iid]["first_seen"] = keep_seen
        else:
            it["first_seen"] = now_s
            merged[iid] = it

    clf = Classifier(cfg["topics"])
    cutoff = now.timestamp() - s.get("retention_days", 60) * 86400
    kept = []
    for it in merged.values():
        d = parse_date(it.get("date")) or parse_date(it.get("first_seen"))
        if d and d.timestamp() < cutoff:
            continue
        if not it.get("date"):
            it["date"] = it.get("first_seen", now_s)
        it["topics"] = clf.classify(it)
        kept.append(it)

    kept.sort(key=lambda x: x.get("date") or "", reverse=True)
    kept = kept[: s.get("max_items_total", 5000)]

    week = now.timestamp() - 7 * 86400
    topics_meta = []
    for t in cfg["topics"]:
        in_t = [it for it in kept if t["id"] in it["topics"]]
        topics_meta.append({
            "id": t["id"], "name": t["name"], "description": t.get("description", {}),
            "count": len(in_t),
            "count_7d": sum(1 for it in in_t if parse_date(it["date"]).timestamp() >= week),
        })
    by_source: dict[str, int] = {}
    for it in kept:
        for src in it["sources"]:
            by_source[src] = by_source.get(src, 0) + 1
    meta = {
        "updated": now_s,
        "site_name": s.get("site_name"),
        "tagline": s.get("tagline"),
        "retention_days": s.get("retention_days", 60),
        "total": len(kept),
        "new_this_run": sum(1 for it in kept if it.get("first_seen") == now_s),
        "topics": topics_meta,
        "sources": by_source,
    }
    return kept, meta


def write(items: list[dict], meta: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "items.json", "w", encoding="utf-8") as f:
        json.dump({"updated": meta["updated"], "items": items}, f,
                  ensure_ascii=False, separators=(",", ":"))
    with open(DATA_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI 前沿栏目数据抓取")
    ap.add_argument("--only", help="只抓取部分来源，逗号分隔：" + ",".join(ALL_SOURCES))
    ap.add_argument("--reclassify", action="store_true", help="不联网，仅按当前配置重新分类")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    cfg = load_config()
    existing = load_existing()
    if args.reclassify:
        fresh = []
    else:
        only = set(args.only.split(",")) if args.only else set(ALL_SOURCES)
        fresh = collect(cfg, only)
        if not fresh and not existing:
            log.error("没有抓到任何数据，请检查网络或配置")
            return 1
    items, meta = build(cfg, fresh, existing)
    write(items, meta)
    log.info("完成：共 %d 条，本次新增 %d 条", meta["total"], meta["new_this_run"])
    for t in meta["topics"]:
        log.info("  %-10s %4d 条（近 7 天 %d）", t["name"]["zh"], t["count"], t["count_7d"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
