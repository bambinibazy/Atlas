"""财务比率、同行业中位数和规则化观察。

比率公式与前端 site/assets/fin.js 的 ratios() 完全一致（tests 里有一致性测试）。
观察只描述数据呈现的现象，不做投资判断。
"""
from __future__ import annotations

from statistics import median


def _n(x):
    return x if isinstance(x, (int, float)) and x == x else None


def _div(a, b):
    a, b = _n(a), _n(b)
    return a / b if a is not None and b not in (None, 0) else None


def _avg(a, b):
    a, b = _n(a), _n(b)
    if a is not None and b is not None:
        return (a + b) / 2
    return a if a is not None else b


def ratios(cur: dict, prev: dict | None = None) -> dict:
    prev = prev or {}
    g = lambda o, k: _n(o.get(k))  # noqa: E731
    rev, cost, ni = g(cur, "revenue"), g(cur, "cost"), g(cur, "netIncome")
    gp = g(cur, "grossProfit")
    if gp is None and rev is not None and cost is not None:
        gp = rev - cost
    cogs = cost if cost is not None else (rev - gp if rev is not None and gp is not None else None)
    aA, aE = _avg(g(cur, "totalAssets"), g(prev, "totalAssets")), _avg(g(cur, "equity"), g(prev, "equity"))
    aAR = _avg(g(cur, "receivables"), g(prev, "receivables"))
    aInv = _avg(g(cur, "inventory"), g(prev, "inventory"))
    aAP = _avg(g(cur, "payables"), g(prev, "payables"))
    ca, cl, cfo, capex = g(cur, "currentAssets"), g(cur, "currentLiabilities"), g(cur, "cfo"), g(cur, "capex")
    days = lambda a, b: _div(a, b) * 365 if a is not None and _div(a, b) is not None else None  # noqa: E731
    r = {
        "grossMargin": _div(gp, rev),
        "operatingMargin": _div(g(cur, "operatingProfit"), rev),
        "netMargin": _div(ni, rev),
        "roe": _div(ni, aE) if aE and aE > 0 else None,
        "roa": _div(ni, aA),
        "assetTurnover": _div(rev, aA),
        "equityMultiplier": _div(aA, aE) if aE and aE > 0 else None,
        "debtRatio": _div(g(cur, "totalLiabilities"), g(cur, "totalAssets")),
        "currentRatio": _div(ca, cl),
        "quickRatio": _div(ca - (g(cur, "inventory") or 0), cl) if ca is not None and cl is not None else None,
        "cashRatio": _div(g(cur, "cash"), cl),
        "dso": days(aAR, rev),
        "dio": days(aInv, cogs) if cogs and cogs > 0 else None,
        "dpo": days(aAP, cogs) if cogs and cogs > 0 else None,
        "cfoToNetIncome": _div(cfo, ni) if ni and ni > 0 else None,
        "fcf": cfo - abs(capex) if cfo is not None and capex is not None else None,
        "rdRatio": _div(g(cur, "rd"), rev),
        "revenueGrowth": _div(rev, g(prev, "revenue")) - 1 if (g(prev, "revenue") or 0) > 0 and rev is not None else None,
        "profitGrowth": _div(ni, g(prev, "netIncome")) - 1 if (g(prev, "netIncome") or 0) > 0 and ni is not None else None,
    }
    r["ccc"] = r["dso"] + r["dio"] - r["dpo"] if None not in (r["dso"], r["dio"], r["dpo"]) else None
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()}


def with_ratios(periods: list[dict]) -> list[dict]:
    out = []
    for i, p in enumerate(periods):
        prev = periods[i - 1] if i > 0 else {}
        out.append({**p, "ratios": ratios(p, prev)})
    return out


PEER_KEYS = ["grossMargin", "operatingMargin", "netMargin", "roe", "roa", "assetTurnover", "equityMultiplier",
             "debtRatio", "currentRatio", "quickRatio", "dso", "dio", "dpo", "ccc", "cfoToNetIncome", "rdRatio",
             "revenueGrowth", "profitGrowth"]


def industry_medians(companies: list[dict]) -> dict[str, dict[str, float]]:
    """每个行业、每个比率的最新一年中位数（至少 3 家公司有数据才计算）。"""
    by_ind: dict[str, list[dict]] = {}
    for c in companies:
        if c.get("periods"):
            by_ind.setdefault(c["industry"], []).append(c["periods"][-1]["ratios"])
    out = {}
    for ind, rows in by_ind.items():
        med = {}
        for k in PEER_KEYS:
            vals = [r[k] for r in rows if r.get(k) is not None]
            if len(vals) >= 3:
                med[k] = round(median(vals), 6)
        med["_n"] = len(rows)
        out[ind] = med
    return out


# ---------------- 规则化观察 ----------------
def _series(periods, key):
    return [p["ratios"].get(key) for p in periods]


def _trend(vals, n=3):
    v = [x for x in vals[-n:] if x is not None]
    if len(v) < n:
        return 0
    if all(b > a for a, b in zip(v, v[1:])):
        return 1
    if all(b < a for a, b in zip(v, v[1:])):
        return -1
    return 0


def pct(x):
    return f"{x * 100:.1f}%"


def observations(periods: list[dict], med: dict) -> list[dict]:
    """返回 [{level: info|watch, text}]。watch = 值得进一步查看的信号，并非结论。"""
    if not periods:
        return []
    out = []
    cur = periods[-1]["ratios"]
    label = periods[-1]["label"]

    gm = _series(periods, "grossMargin")
    t = _trend(gm)
    if t and gm[-3] is not None:
        out.append({"level": "info" if t > 0 else "watch",
                    "text": f"毛利率连续 3 年{'上升' if t > 0 else '下降'}，从 {pct(gm[-3])} 到 {pct(gm[-1])}。"
                            + ("" if t > 0 else "可以结合价格、成本结构和产品组合的变化来看原因。")})

    rg, pg = cur.get("revenueGrowth"), cur.get("profitGrowth")
    if rg is not None and pg is not None:
        if rg > 0.05 and pg < -0.05:
            out.append({"level": "watch", "text": f"{label} 收入增长 {pct(rg)}，但归母净利润下降 {pct(-pg)}：增收不增利，"
                                                   "通常要看毛利率、费用率或非经常性损益的变化。"})
        elif rg < -0.05 and pg > 0.05:
            out.append({"level": "info", "text": f"{label} 收入下降 {pct(-rg)}，净利润反而增长 {pct(pg)}，"
                                                  "利润改善可能来自降本、产品结构或一次性收益。"})

    cn = _series(periods, "cfoToNetIncome")
    recent = [x for x in cn[-2:] if x is not None]
    if len(recent) == 2 and all(x < 0.8 for x in recent):
        out.append({"level": "watch", "text": f"连续两年经营现金流不到净利润的 80%（最近一年 {recent[-1]:.2f} 倍），"
                                               "利润的现金含量偏低，可关注应收账款和存货是否在增加。"})
    elif cur.get("cfoToNetIncome") is not None and cur["cfoToNetIncome"] >= 1.2:
        out.append({"level": "info", "text": f"{label} 经营现金流是净利润的 {cur['cfoToNetIncome']:.2f} 倍，利润的现金含量较高。"})

    fcf = [p["ratios"].get("fcf") for p in periods[-3:]]
    if len(fcf) == 3 and all(x is not None and x < 0 for x in fcf):
        out.append({"level": "watch", "text": "近 3 年自由现金流（经营现金流减资本开支）均为负，扩张资金依赖融资或存量现金。"})

    dso = _series(periods, "dso")
    if len(dso) >= 2 and None not in dso[-2:] and dso[-2] > 0 and dso[-1] / dso[-2] - 1 > 0.2 and dso[-1] > 30:
        out.append({"level": "watch", "text": f"应收账款周转天数从 {dso[-2]:.0f} 天增加到 {dso[-1]:.0f} 天，回款变慢。"})
    dio = _series(periods, "dio")
    if len(dio) >= 2 and None not in dio[-2:] and dio[-2] > 0 and dio[-1] / dio[-2] - 1 > 0.2 and dio[-1] > 30:
        out.append({"level": "watch", "text": f"存货周转天数从 {dio[-2]:.0f} 天增加到 {dio[-1]:.0f} 天，存货积压或备货增加。"})

    dr, mdr = cur.get("debtRatio"), med.get("debtRatio")
    if dr is not None and mdr is not None and dr - mdr > 0.15:
        out.append({"level": "watch", "text": f"资产负债率 {pct(dr)}，比行业中位数 {pct(mdr)} 高 {(dr - mdr) * 100:.0f} 个百分点。"})
    cr = cur.get("currentRatio")
    if cr is not None and cr < 1:
        out.append({"level": "watch", "text": f"流动比率 {cr:.2f}，流动负债超过流动资产。"
                                               "部分行业（如预收款多的消费、零售、平台企业）属正常经营特征，需结合业务模式判断。"})

    roe, mroe, em, mem = cur.get("roe"), med.get("roe"), cur.get("equityMultiplier"), med.get("equityMultiplier")
    if roe is not None and mroe is not None and roe > mroe and em is not None and mem is not None and em > mem * 1.4:
        out.append({"level": "info", "text": f"ROE {pct(roe)} 高于行业中位数，但权益乘数 {em:.2f} 明显高于同行（{mem:.2f}），"
                                              "高回报有相当部分来自财务杠杆。"})
    elif roe is not None and mroe is not None and roe - mroe > 0.05:
        out.append({"level": "info", "text": f"ROE {pct(roe)}，高于行业中位数 {pct(mroe)}。"})

    if roe is not None and roe < 0:
        out.append({"level": "watch", "text": f"{label} 归母净利润为负，ROE 为 {pct(roe)}。"})
    return out
