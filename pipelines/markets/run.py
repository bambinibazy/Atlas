"""入口：抓取 → 合并历史 → 分类、合并相似快讯 → 写出 site/data/*.json

用法：
    python -m pipelines.markets.run                     # 抓取全部
    python -m pipelines.markets.run --only flash,quotes # 只抓部分：flash,rss,filings,quotes,macro
    python -m pipelines.markets.run --offline           # 不联网，只按当前配置重新分类已有数据
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

import yaml

from .classify import Classifier, merge_similar
from .common import SourceStatus, iso, log, make_item, parse_date, utcnow

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config" / "markets" / "sources.yaml"
DATA_DIR = ROOT / "site" / "markets" / "data"
PARTS = ("flash", "rss", "filings", "quotes", "macro")


def load_config(path: Path = CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json(name: str, default):
    p = DATA_DIR / name
    if not p.exists():
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("读取 %s 失败：%s", name, exc)
        return default


def write_json(name: str, data, pretty: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / name, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(data, f, ensure_ascii=False, indent=1)
        else:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def source_names(cfg: dict) -> dict[str, dict[str, str]]:
    names = {}
    for sid, s in (cfg.get("flash") or {}).items():
        names[sid] = s.get("name") or {"zh": sid, "en": sid}
    for f in cfg.get("rss") or []:
        names[f["id"]] = {"zh": f["name"], "en": f["name"]}
    names.update({
        "a_share": {"zh": "东方财富公告", "en": "Eastmoney filings"},
        "hkex": {"zh": "港交所披露易", "en": "HKEXnews"},
        "sec": {"zh": "SEC EDGAR", "en": "SEC EDGAR"},
        "macro": {"zh": "宏观数据", "en": "Macro data"},
        "quotes-em": {"zh": "东方财富行情", "en": "Eastmoney quotes"},
        "quotes-yield": {"zh": "国债收益率", "en": "Bond yields"},
        "quotes-gecko": {"zh": "CoinGecko", "en": "CoinGecko"},
        "macro-cn": {"zh": "中国宏观", "en": "China macro"},
        "macro-us": {"zh": "美国宏观 FRED", "en": "US macro (FRED)"},
    })
    return names


def macro_release_items(new: list[dict], old: list[dict]) -> list[dict]:
    """宏观指标出现新一期数据时，生成一条“数据发布”动态放进时间线。"""
    old_by_id = {e["id"]: e for e in old or []}
    out = []
    for e in new:
        if e.get("stale"):
            continue
        prev = old_by_id.get(e["id"])
        if prev is None or prev.get("period") == e["period"]:
            continue  # 第一次运行不生成，避免一次性冒出一堆旧数据
        region = {"cn": "中国", "us": "美国"}[e["region"]]
        unit = e["unit"] if e["unit"] == "%" else ""
        prev_txt = f"，前值 {e['prev']}{unit}" if e.get("prev") is not None else ""
        out.append(make_item(
            id=f"macro:{e['id']}:{e['period']}", type="policy", source="macro",
            title=f"{region} {e['period']} {e['name']['zh']} {e['value']}{unit}{prev_txt}",
            url=e.get("url"), date=utcnow(), markets=["cn" if e["region"] == "cn" else "us", "global"],
            important=True, tags=[e["name"]["en"]],
            extra={"title_en": f"{'China' if e['region'] == 'cn' else 'US'} {e['period']} {e['name']['en']} "
                               f"{e['value']}{unit}" + (f", prior {e['prev']}{unit}" if e.get('prev') is not None else "")},
        ))
    return out


def merge_items(old: dict, new: dict) -> dict:
    m = dict(old)
    m["sources"] = sorted(set(old.get("sources", [])) | set(new.get("sources", [])))
    for k in ("title", "url"):
        if new.get(k):
            m[k] = new[k]
    if len(new.get("summary", "")) > len(m.get("summary", "")):
        m["summary"] = new["summary"]
    m["important"] = old.get("important", False) or new.get("important", False)
    m["markets"] = list(dict.fromkeys((new.get("markets") or []) + (old.get("markets") or [])))
    if not m.get("date"):
        m["date"] = new.get("date")
    return m


def build_items(cfg: dict, fresh: list[dict], existing: list[dict]) -> list[dict]:
    s = cfg["settings"]
    now = utcnow()
    now_s = iso(now)
    by_id = {it["id"]: it for it in existing}
    for it in fresh:
        if it["id"] in by_id:
            seen = by_id[it["id"]].get("first_seen", now_s)
            by_id[it["id"]] = merge_items(by_id[it["id"]], it)
            by_id[it["id"]]["first_seen"] = seen
        else:
            it["first_seen"] = now_s
            by_id[it["id"]] = it

    clf = Classifier(cfg)
    retention = s.get("retention_days", {})
    kept = []
    for it in by_id.values():
        d = parse_date(it.get("date")) or parse_date(it.get("first_seen")) or now
        if d > now + timedelta(hours=2):  # 个别源时间戳异常时，以首次抓到的时间为准
            d = parse_date(it.get("first_seen")) or now
            it["date"] = iso(d)
        if not it.get("date"):
            it["date"] = iso(d)
        if (now - d).total_seconds() > retention.get(it["type"], 14) * 86400:
            continue
        kept.append(clf.apply(it))

    kept = merge_similar(kept, s.get("dedupe_window_hours", 3), s.get("dedupe_similarity", 0.55))
    kept.sort(key=lambda x: x.get("date") or "", reverse=True)
    return kept[: s.get("max_items_total", 8000)]


def build_meta(cfg: dict, items: list[dict], status: SourceStatus, prev_meta: dict) -> dict:
    now = utcnow()
    day = now.timestamp() - 86400
    recent = [i for i in items if parse_date(i["date"]).timestamp() >= day]
    markets = []
    for m in cfg.get("markets", []):
        markets.append({"id": m["id"], "name": m["name"],
                        "count": sum(1 for i in items if m["id"] in i["markets"]),
                        "count_24h": sum(1 for i in recent if m["id"] in i["markets"])})
    types = {}
    for i in items:
        types[i["type"]] = types.get(i["type"], 0) + 1
    # 本次没有运行的数据源，沿用上次的状态
    st = dict(prev_meta.get("sources_status") or {})
    st.update(status.status)
    s = cfg["settings"]
    return {
        "updated": iso(now), "site_name": s["site_name"], "tagline": s["tagline"],
        "timezone": s.get("timezone", "Asia/Shanghai"), "retention_days": s.get("retention_days"),
        "total": len(items), "count_24h": len(recent), "markets": markets, "types": types,
        "source_names": source_names(cfg), "sources_status": st,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="行情快讯栏目数据抓取")
    ap.add_argument("--only", help="只运行部分：" + ",".join(PARTS))
    ap.add_argument("--offline", action="store_true", help="不联网，仅按当前配置重新分类已有数据")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    cfg = load_config()
    prev_meta = read_json("meta.json", {})
    prev_items = read_json("items.json", {}).get("items", [])
    prev_quotes = read_json("quotes.json", {})
    prev_macro = read_json("macro.json", {}).get("indicators", [])
    status = SourceStatus()
    parts = set() if args.offline else (set(args.only.split(",")) if args.only else set(PARTS))
    smax = cfg["settings"].get("summary_max_chars", 360)
    last_run = parse_date(prev_meta.get("updated"))
    since = last_run - timedelta(hours=1) if last_run else None

    fresh: list[dict] = []
    quotes, macro = prev_quotes, prev_macro
    if "flash" in parts:
        from .sources import flash_cn
        fresh += flash_cn.fetch(cfg.get("flash", {}), smax, since, status)
    if "rss" in parts:
        from .sources import rss
        fresh += rss.fetch(cfg.get("rss", []), smax, status)
    if "filings" in parts:
        from .sources import filings
        fresh += filings.fetch(cfg.get("filings", {}), status)
    if "quotes" in parts:
        from .sources import quotes as q
        quotes = q.fetch(cfg["quotes"], status, prev_quotes)
    if "macro" in parts:
        from .sources import macro as mc
        macro = mc.fetch(cfg.get("macro", {}), status, prev_macro)
        fresh += macro_release_items(macro, prev_macro)

    has_quotes = any(g.get("rows") for g in (quotes or {}).get("groups", []))
    if parts and not fresh and not prev_items and not has_quotes and not macro:
        log.error("没有抓到任何数据，请检查网络或配置")
        return 1

    items = build_items(cfg, fresh, prev_items)
    meta = build_meta(cfg, items, status, prev_meta)
    write_json("items.json", {"updated": meta["updated"], "items": items})
    write_json("quotes.json", quotes or {"groups": []})
    write_json("macro.json", {"updated": meta["updated"], "indicators": macro or []})
    write_json("meta.json", meta, pretty=True)

    ok = sum(1 for v in status.status.values() if v["ok"])
    log.info("完成：共 %d 条（24 小时内 %d），数据源成功 %d / %d", meta["total"], meta["count_24h"],
             ok, len(status.status))
    for sid, v in status.status.items():
        if not v["ok"]:
            log.info("  失败：%s %s", v["name"], v.get("error", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
