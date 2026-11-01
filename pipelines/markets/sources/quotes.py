"""行情：东方财富日 K 线（指数/个股/外汇/期货）、中美国债收益率、CoinGecko 加密货币。

每个品种返回：最新值、前收、涨跌额、涨跌幅、最近 N 天收盘价（画走势线）。
某个品种抓取失败时，run.py 会保留上一次成功的数据并标记为“过期”。
"""
from __future__ import annotations

import os

from ..common import Breaker, RateLimiter, SourceStatus, iso, log, make_session, parse_date, utcnow, CST

EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_YIELD = "https://datacenter.eastmoney.com/api/data/get"
GECKO = "https://api.coingecko.com/api/v3"


def _row(item: dict, last: float, prev: float | None, spark: list[float], as_of: str | None,
         decimals: int, unit: str = "", change_unit: str = "pct") -> dict:
    chg = None if prev in (None, 0) else last - prev
    pct = None if prev in (None, 0) else (last - prev) / prev * 100
    return {
        "id": item["id"], "name": item["name"], "last": round(last, 6),
        "prev": None if prev is None else round(prev, 6),
        "chg": None if chg is None else round(chg, 6),
        "pct": None if pct is None else round(pct, 4),
        "spark": [round(v, 6) for v in spark], "as_of": as_of,
        "decimals": decimals, "unit": unit, "change_unit": change_unit,
    }


# ---------------- 东方财富 K 线 ----------------
def parse_em_kline(data: dict, item: dict, days: int) -> dict | None:
    d = (data or {}).get("data") or {}
    rows = []
    for line in d.get("klines") or []:
        parts = line.split(",")
        try:
            rows.append((parts[0], float(parts[2])))  # 日期, 收盘
        except (IndexError, ValueError):
            continue
    if not rows:
        return None
    last_date, last = rows[-1]
    prev = rows[-2][1] if len(rows) >= 2 else (float(d["preKPrice"]) if d.get("preKPrice") else None)
    dec = item.get("decimals", d.get("decimal", 2))
    return _row(item, last, prev, [c for _, c in rows[-days:]], last_date, int(dec))


def fetch_em(items: list[dict], days: int, status: SourceStatus) -> dict[str, dict]:
    s = make_session({"Referer": "https://quote.eastmoney.com/"})
    lim = RateLimiter(0.35)
    out, fails = {}, []
    br = Breaker(max_fail=4, budget_s=120)
    for it in items:
        if br.open():
            fails.append("连续失败或超时，跳过剩余品种")
            break
        lim.wait()
        try:
            r = s.get(EM_KLINE, timeout=15, params={
                "secid": it["secid"], "klt": "101", "fqt": "1", "lmt": str(days + 1), "end": "20500000",
                "iscca": "1", "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "f057cbcbce2a86e2866ab8877db1d059", "forcect": "1"})
            r.raise_for_status()
            row = parse_em_kline(r.json(), it, days)
            if row is None:
                raise ValueError("无 K 线数据")
            out[it["id"]] = row
            br.record(True)
        except Exception as exc:
            br.record(False)
            fails.append(f"{it['id']}: {exc}")
    _report(status, "quotes-em", "东方财富行情", out, fails, len(items))
    return out


# ---------------- 中美国债收益率 ----------------
def parse_yields(data: dict, items: list[dict], days: int) -> dict[str, dict]:
    rows = ((data or {}).get("result") or {}).get("data") or []
    rows = sorted(rows, key=lambda r: r.get("SOLAR_DATE") or "")
    out = {}
    for it in items:
        series = [(r["SOLAR_DATE"][:10], float(r[it["field"]])) for r in rows
                  if r.get(it["field"]) not in (None, "")]
        if not series:
            continue
        last_date, last = series[-1]
        prev = series[-2][1] if len(series) >= 2 else None
        row = _row(it, last, prev, [v for _, v in series[-days:]], last_date, 3, "%", "bp")
        if row["chg"] is not None:
            row["chg"] = round(row["chg"] * 100, 1)  # 收益率变动用基点表示
        row["pct"] = None
        out[it["id"]] = row
    return out


def fetch_yields(items: list[dict], days: int, status: SourceStatus) -> dict[str, dict]:
    if not items:
        return {}
    s = make_session({"Referer": "https://data.eastmoney.com/cjsj/zmgzsyl.html"})
    try:
        r = s.get(EM_YIELD, timeout=20, params={
            "type": "RPTA_WEB_TREASURYYIELD", "sty": "ALL", "st": "SOLAR_DATE", "sr": "-1",
            "token": "894050c76af8597a853f5b408b759f5d", "p": "1", "ps": str(days + 15),
            "pageNo": "1", "pageNum": "1"})
        r.raise_for_status()
        out = parse_yields(r.json(), items, days)
        _report(status, "quotes-yield", "国债收益率", out, [], len(items))
        return out
    except Exception as exc:
        status.fail("quotes-yield", exc, "国债收益率")
        return {}


# ---------------- CoinGecko ----------------
def parse_gecko(markets: list, charts: dict[str, dict], items: list[dict], days: int) -> dict[str, dict]:
    by_coin = {m.get("id"): m for m in markets or []}
    out = {}
    for it in items:
        m = by_coin.get(it["coin"])
        if not m or m.get("current_price") is None:
            continue
        last = float(m["current_price"])
        pct = m.get("price_change_percentage_24h")
        prev = last / (1 + pct / 100) if pct not in (None, -100) else None
        prices = [p[1] for p in (charts.get(it["coin"]) or {}).get("prices", [])]
        spark = prices[-days:] if prices else [p for p in (m.get("sparkline_in_7d") or {}).get("price", [])][::6]
        dec = 2 if last >= 1 else 4
        as_of = parse_date(m.get("last_updated"))
        row = _row(it, last, prev, spark, as_of.astimezone(CST).strftime("%Y-%m-%d %H:%M") if as_of else None, dec)
        row["unit"] = "$"
        out[it["id"]] = row
    return out


def fetch_gecko(items: list[dict], days: int, status: SourceStatus) -> dict[str, dict]:
    if not items:
        return {}
    headers = {}
    if os.environ.get("COINGECKO_DEMO_KEY"):
        headers["x-cg-demo-api-key"] = os.environ["COINGECKO_DEMO_KEY"]
    s = make_session(headers)
    lim = RateLimiter(3.0)  # 免费接口每分钟约 10–30 次
    try:
        ids = ",".join(i["coin"] for i in items)
        r = s.get(f"{GECKO}/coins/markets", timeout=20, params={
            "vs_currency": "usd", "ids": ids, "sparkline": "true", "price_change_percentage": "24h"})
        r.raise_for_status()
        markets = r.json()
        charts = {}
        br = Breaker(max_fail=2, budget_s=60)
        for it in items:
            if br.open():
                break
            lim.wait()
            try:
                c = s.get(f"{GECKO}/coins/{it['coin']}/market_chart", timeout=20,
                          params={"vs_currency": "usd", "days": str(days), "interval": "daily"})
                c.raise_for_status()
                charts[it["coin"]] = c.json()
                br.record(True)
            except Exception as exc:  # 走势线拿不到就退回 7 天小时线
                br.record(False)
                log.info("CoinGecko %s 走势失败：%s", it["coin"], exc)
        out = parse_gecko(markets, charts, items, days)
        _report(status, "quotes-gecko", "CoinGecko", out, [], len(items))
        return out
    except Exception as exc:
        status.fail("quotes-gecko", exc, "CoinGecko")
        return {}


def _report(status: SourceStatus, sid: str, name: str, out: dict, fails: list[str], total: int) -> None:
    if out:
        status.ok(sid, len(out), name)
        if fails:
            log.warning("%s 部分失败：%s", name, "; ".join(fails[:5]))
    else:
        status.fail(sid, "; ".join(fails[:3]) or "无数据", name)
    log.info("行情 %s → %d/%d", name, len(out), total)


def fetch(cfg: dict, status: SourceStatus, previous: dict | None = None) -> dict:
    """返回 quotes.json 内容。失败的品种沿用上次数据并加 stale 标记。"""
    days = cfg.get("history_days", 30)
    all_items = [it for g in cfg["groups"] for it in g["items"]]
    rows: dict[str, dict] = {}
    rows.update(fetch_em([i for i in all_items if i.get("provider", "em") == "em"], days, status))
    rows.update(fetch_yields([i for i in all_items if i.get("provider") == "yield"], days, status))
    rows.update(fetch_gecko([i for i in all_items if i.get("provider") == "gecko"], days, status))

    prev_rows = {}
    for g in (previous or {}).get("groups", []):
        for r in g.get("rows", []):
            prev_rows[r["id"]] = r
    groups = []
    for g in cfg["groups"]:
        out_rows = []
        for it in g["items"]:
            if it["id"] in rows:
                out_rows.append(rows[it["id"]])
            elif it["id"] in prev_rows:
                old = dict(prev_rows[it["id"]])
                old["stale"] = True
                old["name"] = it["name"]
                out_rows.append(old)
        groups.append({"id": g["id"], "name": g["name"], "rows": out_rows})
    return {"updated": iso(utcnow()), "groups": groups}
