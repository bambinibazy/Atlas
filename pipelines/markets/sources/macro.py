"""宏观数据：中国（东方财富数据中心）、美国（FRED）。

美国数据默认用 FRED 公开的 CSV 下载地址，无需注册；
如果设置了环境变量 FRED_API_KEY，则改用官方 API（更稳定）。
"""
from __future__ import annotations

import csv
import io
import os
import re

from ..common import Breaker, RateLimiter, SourceStatus, days_ago, log, make_session

EM_DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HISTORY = 24


def cn_period(time_label: str | None, date_str: str | None) -> str:
    t = time_label or ""
    m = re.search(r"(\d{4})年(\d{1,2})月", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})年第(\d)(?:-(\d))?季度", t)
    if m:
        return f"{m.group(1)}Q{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
    return (date_str or "")[:10]


def _entry(it: dict, region: str, points: list[tuple[str, float]], source: str, src_url: str) -> dict | None:
    points = [(p, v) for p, v in points if v is not None]
    if not points:
        return None
    hist = points[-HISTORY:]
    return {
        "id": it["id"], "region": region, "name": it["name"], "unit": it.get("unit", ""),
        "period": hist[-1][0], "value": round(hist[-1][1], 3),
        "prev": round(hist[-2][1], 3) if len(hist) >= 2 else None,
        "prev_period": hist[-2][0] if len(hist) >= 2 else None,
        "history": [{"p": p, "v": round(v, 3)} for p, v in hist],
        "source": source, "url": src_url,
    }


# ---------------- 中国 ----------------
def parse_cn(data: dict, it: dict) -> dict | None:
    rows = ((data or {}).get("result") or {}).get("data") or []
    date_field = it.get("date_field", "REPORT_DATE")
    pts = []
    for r in rows:
        v = r.get(it["field"])
        if v in (None, ""):
            continue
        try:
            pts.append((r.get(date_field) or "", cn_period(r.get("TIME"), r.get(date_field)), float(v)))
        except ValueError:
            continue
    pts.sort(key=lambda x: x[0])
    if date_field != "REPORT_DATE":
        # LPR 等按日期发布的数据：只保留数值发生变化的日期
        dedup = []
        for d, p, v in pts:
            if not dedup or dedup[-1][2] != v:
                dedup.append((d, p, v))
        pts = dedup
    return _entry(it, "cn", [(p, v) for _, p, v in pts], "东方财富数据中心", "https://data.eastmoney.com/cjsj/")


def fetch_cn(items: list[dict], status: SourceStatus) -> list[dict]:
    s = make_session({"Referer": "https://data.eastmoney.com/cjsj/"})
    lim = RateLimiter(0.5)
    out, errors = [], []
    br = Breaker()
    for it in items:
        if br.open():
            errors.append("连续失败，跳过剩余指标")
            break
        lim.wait()
        date_field = it.get("date_field", "REPORT_DATE")
        params = {"reportName": it["report"], "columns": "ALL" if date_field != "REPORT_DATE"
                  else f"REPORT_DATE,TIME,{it['field']}",
                  "pageNumber": "1", "pageSize": "60" if date_field != "REPORT_DATE" else str(HISTORY + 2),
                  "sortColumns": date_field, "sortTypes": "-1", "source": "WEB", "client": "WEB",
                  "p": "1", "pageNo": "1", "pageNum": "1"}
        try:
            r = s.get(EM_DC, params=params, timeout=20)
            r.raise_for_status()
            e = parse_cn(r.json(), it)
            if e:
                out.append(e)
            else:
                errors.append(f"{it['id']} 无数据")
            br.record(True)
        except Exception as exc:
            br.record(False)
            errors.append(f"{it['id']}: {exc}")
    if out:
        status.ok("macro-cn", len(out), "中国宏观")
    else:
        status.fail("macro-cn", "; ".join(errors[:2]) or "无数据", "中国宏观")
    if errors and out:
        log.warning("中国宏观部分失败：%s", "; ".join(errors[:3]))
    return out


# ---------------- 美国（FRED） ----------------
def parse_fred_csv(text: str) -> list[tuple[str, float | None]]:
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r in rows[1:]:
        if len(r) < 2:
            continue
        try:
            out.append((r[0], float(r[1])))
        except ValueError:
            out.append((r[0], None))  # FRED 用 "." 表示缺失
    return out


def transform(obs: list[tuple[str, float | None]], it: dict) -> list[tuple[str, float]]:
    obs = [(d, v) for d, v in obs if v is not None]
    obs.sort()
    if it.get("frequency") == "daily":
        monthly = {}
        for d, v in obs:
            monthly[d[:7]] = (d, v)  # 每月最后一个观测值
        obs = [monthly[k] for k in sorted(monthly)]
    change = it.get("change", "none")
    pts = []
    for i, (d, v) in enumerate(obs):
        if change == "yoy":
            if i < 12 or not obs[i - 12][1]:
                continue
            val = (v / obs[i - 12][1] - 1) * 100
        elif change == "diff":
            if i < 1:
                continue
            val = v - obs[i - 1][1]
        else:
            val = v
        pts.append((d, val))
    return [(fred_period(d, it), v) for d, v in pts]


def fred_period(d: str, it: dict) -> str:
    if it.get("series", "").endswith("Q225SBEA") or it.get("frequency") == "quarterly":
        y, m = int(d[:4]), int(d[5:7])
        return f"{y}Q{(m - 1) // 3 + 1}"
    return d[:7]


def fetch_us(items: list[dict], status: SourceStatus) -> list[dict]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    s = make_session()
    lim = RateLimiter(0.6)
    start = days_ago(365 * 4).date().isoformat()
    out, errors = [], []
    br = Breaker()
    for it in items:
        if br.open():
            errors.append("连续失败，跳过剩余指标")
            break
        lim.wait()
        try:
            if key:
                r = s.get("https://api.stlouisfed.org/fred/series/observations", timeout=25, params={
                    "series_id": it["series"], "api_key": key, "file_type": "json", "observation_start": start})
                r.raise_for_status()
                obs = []
                for o in r.json().get("observations", []):
                    try:
                        obs.append((o["date"], float(o["value"])))
                    except ValueError:
                        obs.append((o["date"], None))
            else:
                r = s.get("https://fred.stlouisfed.org/graph/fredgraph.csv", timeout=25,
                          params={"id": it["series"], "cosd": start})
                r.raise_for_status()
                obs = parse_fred_csv(r.text)
            e = _entry(it, "us", transform(obs, it), "FRED",
                       f"https://fred.stlouisfed.org/series/{it['series']}")
            if e:
                out.append(e)
            else:
                errors.append(f"{it['id']} 无数据")
            br.record(True)
        except Exception as exc:
            br.record(False)
            errors.append(f"{it['id']}: {exc}")
    if out:
        status.ok("macro-us", len(out), "美国宏观 FRED")
    else:
        status.fail("macro-us", "; ".join(errors[:2]) or "无数据", "美国宏观 FRED")
    if errors and out:
        log.warning("美国宏观部分失败：%s", "; ".join(errors[:3]))
    return out


def fetch(cfg: dict, status: SourceStatus, previous: list[dict] | None = None) -> list[dict]:
    got = fetch_cn(cfg.get("cn", []), status) + fetch_us(cfg.get("us", []), status)
    have = {e["id"] for e in got}
    for old in previous or []:  # 失败的指标沿用上次数据
        if old["id"] not in have:
            got.append(dict(old, stale=True))
    order = [it["id"] for it in cfg.get("cn", []) + cfg.get("us", [])]
    got.sort(key=lambda e: order.index(e["id"]) if e["id"] in order else 999)
    return got

