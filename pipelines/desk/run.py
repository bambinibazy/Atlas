"""入口：资讯抓取 / 财报更新 / 知识库编译 → site/data/

用法：
    python -m pipelines.desk.run                      # 全部
    python -m pipelines.desk.run --only news,kb       # 只运行部分：news, financials, kb
    python -m pipelines.desk.run --only financials --companies 600519,AAPL   # 只更新指定公司
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

import yaml

from .common import Breaker, KeywordMatcher, RateLimiter, SourceStatus, iso, log, parse_date, utcnow

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config" / "desk"
DATA = ROOT / "site" / "data"
CONTENT = ROOT / "content" / "kb"
PARTS = ("news", "financials", "kb")


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json(rel: str, default):
    p = DATA / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("读取 %s 失败：%s", rel, exc)
        return default


def write_json(rel: str, data, pretty=False) -> None:
    p = DATA / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1 if pretty else None,
                            separators=None if pretty else (",", ":")), encoding="utf-8")


# ---------------- 资讯 ----------------
def run_news(cfg: dict, status: SourceStatus) -> dict:
    from .sources import news

    s = cfg["settings"]
    keep_days = s.get("retention_days", 45)
    fresh = news.fetch_rss(cfg.get("rss", []), s.get("summary_max_chars", 280), status, keep_days)
    fresh += news.fetch_gov(cfg.get("gov_lists", []) + cfg.get("page_lists", []), status, keep_days)
    prev = {i["id"]: i for i in read_json("news.json", {}).get("items", [])}
    now = utcnow()
    now_s = iso(now)
    first_run_sources = {i["source"] for i in fresh} - {i["source"] for i in prev.values()}
    for it in fresh:
        old = prev.get(it["id"])
        it["first_seen"] = old["first_seen"] if old else now_s
        if not it.get("date"):
            # 没有发布日期的条目：用首次收录时间；某个来源第一次抓取时不知道真实日期，标记出来
            it["date"] = old["date"] if old else now_s
            it["date_estimated"] = True
            if it["source"] in first_run_sources and not old:
                it["backfill"] = True
        prev[it["id"]] = it

    matchers = [(t["id"], KeywordMatcher(t.get("keywords", []))) for t in cfg.get("topics", [])]
    items = []
    for it in prev.values():
        d = parse_date(it["date"]) or now
        if d > now + timedelta(hours=2):
            it["date"] = now_s
        if (now - d).days > keep_days:
            continue
        text = f"{it['title']} {it.get('summary', '')}"
        topics = list(it.get("topics") or [])
        for tid, m in matchers:
            if tid not in topics and (m.any(it["title"]) or len(m.matches(text)) >= 2):
                topics.append(tid)
        it["topics"] = topics
        items.append(it)
    items.sort(key=lambda x: x["date"], reverse=True)
    items = items[: s.get("max_items", 1500)]
    names = {x["id"]: x["name"] for x in cfg.get("rss", []) + cfg.get("gov_lists", []) + cfg.get("page_lists", [])}
    write_json("news.json", {"updated": now_s, "items": items, "sources": names,
                             "topics": [{"id": t["id"], "name": t["name"]} for t in cfg.get("topics", [])]})
    write_feed(items, names, {t["id"]: t["name"] for t in cfg.get("topics", [])})
    log.info("资讯：共 %d 条", len(items))
    return {"news_total": len(items)}


def write_feed(items: list[dict], names: dict, topics: dict, limit: int = 100) -> None:
    """资讯的聚合 RSS（site/feed.xml），可以用阅读器订阅。"""
    from email.utils import format_datetime
    from xml.sax.saxutils import escape as x

    rows = []
    for it in [i for i in items if not i.get("backfill")][:limit]:
        d = parse_date(it["date"]) or utcnow()
        cats = "".join(f"<category>{x(topics.get(t, t))}</category>" for t in it.get("topics", []))
        rows.append(f"<item><title>{x(it['title'])}</title><link>{x(it['url'])}</link>"
                    f"<guid isPermaLink=\"false\">{x(it['id'])}</guid>{cats}"
                    f"<description>{x(names.get(it['source'], it['source']) + '｜' + (it.get('summary') or ''))}</description>"
                    f"<pubDate>{format_datetime(d)}</pubDate></item>")
    (DATA.parent / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>星图智策 · 资讯与政策</title>'
        "<link>./</link><description>管理研究、四大洞察、财经资讯与财政、税务、证监会政策</description>"
        + "".join(rows) + "</channel></rss>\n", encoding="utf-8")


# ---------------- 财报 ----------------
def run_financials(status: SourceStatus, only: set[str] | None = None) -> dict:
    from .financials import extract, metrics

    cfg = load_yaml("companies.yaml")
    industries = cfg.get("industries", {})
    old_index = {c["id"]: c for c in read_json("companies/index.json", {}).get("companies", [])}
    us_session = None
    lim = {"a": RateLimiter(0.5), "hk": RateLimiter(0.5), "us": RateLimiter(0.2)}
    breakers = {m: Breaker(max_fail=4, budget_s=600) for m in ("a", "hk", "us")}
    ok_count = {"a": 0, "hk": 0, "us": 0}
    fail_count = {"a": 0, "hk": 0, "us": 0}
    last_err = {}
    companies = []
    for c in cfg["companies"]:
        cid = f"{c['market']}-{str(c['code']).lower()}"
        base = {"id": cid, "market": c["market"], "code": str(c["code"]), "name": c["name"],
                "industry": c["industry"], "industry_name": industries.get(c["industry"], c["industry"])}
        data = None
        if (not only or str(c["code"]) in only) and not breakers[c["market"]].open():
            lim[c["market"]].wait()
            try:
                if c["market"] == "us":
                    if us_session is None:
                        from .common import make_session
                        us_session = make_session({"User-Agent": extract.sec_user_agent(),
                                                   "Accept-Encoding": "gzip, deflate"})
                    data = extract.fetch_us(c["code"], us_session)
                else:
                    data = extract.FETCHERS[c["market"]](c["code"])
                data["fetched"] = iso(utcnow())
                ok_count[c["market"]] += 1
                breakers[c["market"]].record(True)
            except Exception as exc:
                fail_count[c["market"]] += 1
                last_err[c["market"]] = f"{c['name']}: {exc}"
                breakers[c["market"]].record(False)
                log.warning("财报 %s %s 失败：%s", c["name"], c["code"], exc)
        if data is None:  # 失败或本次未更新：沿用上次的数据
            old = read_json(f"companies/{cid}.json", None)
            if old:
                data = {k: old.get(k) for k in ("currency", "standard", "periods", "source_url", "fetched")}
                data["periods"] = [{k: v for k, v in p.items() if k != "ratios"} for p in data["periods"] or []]
                data["stale"] = True
        if not data or not data.get("periods"):
            continue
        companies.append({**base, **data, "periods": metrics.with_ratios(data["periods"])})

    meds = metrics.industry_medians(companies)
    index = []
    for c in companies:
        med = meds.get(c["industry"], {})
        c["observations"] = metrics.observations(c["periods"], med)
        c["peers"] = [p["id"] for p in companies if p["industry"] == c["industry"] and p["id"] != c["id"]]
        write_json(f"companies/{c['id']}.json", c)
        last = c["periods"][-1]
        index.append({
            "id": c["id"], "market": c["market"], "code": c["code"], "name": c["name"],
            "industry": c["industry"], "industry_name": c["industry_name"], "currency": c["currency"],
            "standard": c.get("standard"), "latest": last["label"], "latest_end": last["end"],
            "revenue": last.get("revenue"), "netIncome": last.get("netIncome"),
            "ratios": {k: last["ratios"].get(k) for k in metrics.PEER_KEYS},
            "stale": bool(c.get("stale")), "watch": sum(1 for o in c["observations"] if o["level"] == "watch"),
        })
    write_json("companies/index.json", {
        "updated": iso(utcnow()), "companies": index,
        "industries": [{"id": k, "name": v, "median": meds.get(k, {})} for k, v in industries.items()],
    })
    names = {"a": "A 股财报（东方财富）", "hk": "港股财报（东方财富）", "us": "美股财报（SEC XBRL）"}
    for m in ("a", "hk", "us"):
        if ok_count[m] or fail_count[m]:
            if ok_count[m]:
                status.ok(f"fin-{m}", ok_count[m], names[m])
                if fail_count[m]:
                    status.status[f"fin-{m}"]["partial"] = f"{fail_count[m]} 家失败；{last_err.get(m, '')}"[:200]
            else:
                status.fail(f"fin-{m}", last_err.get(m, "全部失败"), names[m])
    log.info("财报：%d 家公司（A 股成功 %d，港股 %d，美股 %d）", len(companies), ok_count["a"], ok_count["hk"], ok_count["us"])
    return {"companies": len(companies)}


# ---------------- 知识库 ----------------
def run_kb(status: SourceStatus) -> dict:
    from . import kb

    data = kb.build(CONTENT)
    write_json("kb.json", data)
    log.info("知识库：%d 篇", len(data["articles"]))
    return {"kb_articles": len(data["articles"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="星图智策：资讯、财报、知识库数据构建")
    ap.add_argument("--only", help="只运行部分：" + ",".join(PARTS))
    ap.add_argument("--companies", help="只更新这些公司代码（逗号分隔），其他公司沿用旧数据")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    parts = set(args.only.split(",")) if args.only else set(PARTS)
    status = SourceStatus()
    meta = read_json("meta.json", {})
    sources = cfg_news = load_yaml("sources.yaml")
    summary = dict(meta.get("summary") or {})
    if "kb" in parts:
        summary.update(run_kb(status))  # 知识库出错直接失败，避免发布不完整的内容
    if "news" in parts:
        summary.update(run_news(cfg_news, status))
        meta["news_updated"] = iso(utcnow())
    if "financials" in parts:
        only = set(args.companies.split(",")) if args.companies else None
        summary.update(run_financials(status, only))
        meta["financials_updated"] = iso(utcnow())
    st = dict(meta.get("sources_status") or {})
    st.update(status.status)
    # 已关闭或已删除的来源不再显示在“数据源状态”里（财报状态在只更新资讯时也要保留）
    active = {x["id"] for x in cfg_news.get("rss", []) + cfg_news.get("gov_lists", []) + cfg_news.get("page_lists", [])
              if x.get("enabled", True)} | {"fin-a", "fin-hk", "fin-us"}
    st = {k: v for k, v in st.items() if k in active}
    meta.update({"updated": iso(utcnow()), "site_name": sources["settings"]["site_name"],
                 "site_name_en": sources["settings"].get("site_name_en"),
                 "tagline": sources["settings"]["tagline"], "summary": summary, "sources_status": st})
    write_json("meta.json", meta, pretty=True)
    bad = [v["name"] for v in status.status.values() if not v["ok"]]
    log.info("完成。失败的数据源：%s", "、".join(bad) if bad else "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
