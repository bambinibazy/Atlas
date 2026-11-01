"""三个数据源的年报抽取：东方财富 A 股、东方财富港股、SEC XBRL（美股）。

每家公司统一输出：
  {"currency": "CNY", "standard": "CAS", "periods": [{"end": "2024-12-31", "label": "2024", ...字段}]}
字段（缺失则不出现）：revenue cost grossProfit operatingProfit netIncome rd totalAssets totalLiabilities
equity currentAssets currentLiabilities cash inventory receivables payables cfo capex
"""
from __future__ import annotations

import os
from datetime import date

from ..common import RateLimiter, log, make_session

FIELDS = ["revenue", "cost", "grossProfit", "operatingProfit", "netIncome", "rd", "totalAssets",
          "totalLiabilities", "equity", "currentAssets", "currentLiabilities", "cash", "inventory",
          "receivables", "payables", "cfo", "capex"]
MAX_YEARS = 6


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # 去掉 NaN
    except (TypeError, ValueError):
        return None


# =====================================================================
#  A 股：东方财富 F10 财务分析（按年度）。接口参考 AKShare stock_*_sheet_by_yearly_em
# =====================================================================
EM_F10 = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis"
A_MAP = {
    "zcfzb": {  # 资产负债表
        "totalAssets": ["TOTAL_ASSETS"], "totalLiabilities": ["TOTAL_LIABILITIES"],
        "equity": ["TOTAL_PARENT_EQUITY", "TOTAL_EQUITY"], "currentAssets": ["TOTAL_CURRENT_ASSETS"],
        "currentLiabilities": ["TOTAL_CURRENT_LIAB"], "cash": ["MONETARYFUNDS"], "inventory": ["INVENTORY"],
        "receivables": ["ACCOUNTS_RECE", "NOTE_ACCOUNTS_RECE"],
        "payables": ["ACCOUNTS_PAYABLE", "NOTE_ACCOUNTS_PAYABLE"],
    },
    "lrb": {  # 利润表
        "revenue": ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"], "cost": ["OPERATE_COST"],
        "operatingProfit": ["OPERATE_PROFIT"], "netIncome": ["PARENT_NETPROFIT", "NETPROFIT"],
        "rd": ["RESEARCH_EXPENSE", "ME_RESEARCH_EXPENSE"],
    },
    "xjllb": {  # 现金流量表
        "cfo": ["NETCASH_OPERATE"], "capex": ["CONSTRUCT_LONG_ASSET"],
    },
}


def a_secucode(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return f"SH{code}"
    if code.startswith(("4", "8")) or code.startswith("92"):
        return f"BJ{code}"
    return f"SZ{code}"


def pick(row: dict, keys: list[str]):
    for k in keys:
        v = _num(row.get(k))
        if v is not None:
            return v
    return None


def parse_a_rows(rows_by_sheet: dict[str, list[dict]]) -> list[dict]:
    periods: dict[str, dict] = {}
    for sheet, rows in rows_by_sheet.items():
        for row in rows or []:
            end = str(row.get("REPORT_DATE", ""))[:10]
            if not end:
                continue
            p = periods.setdefault(end, {"end": end, "label": end[:4]})
            for field, keys in A_MAP[sheet].items():
                v = pick(row, keys)
                if v is not None:
                    p[field] = v
    out = sorted(periods.values(), key=lambda p: p["end"])
    for p in out:
        if "capex" in p:
            p["capex"] = -abs(p["capex"])  # 统一为负数（现金流出）
    return out[-MAX_YEARS:]


def fetch_a(code: str) -> dict:
    s = make_session({"Referer": f"{EM_F10}/Index?type=web&code={a_secucode(code).lower()}"})
    lim = RateLimiter(0.4)
    sec = a_secucode(code)
    rows: dict[str, list[dict]] = {}
    ctype_used = None
    for ctype in ("4", "3", "2", "1"):  # 4 = 一般企业；其余为券商/保险/银行，按顺序尝试
        lim.wait()
        r = s.get(f"{EM_F10}/zcfzbDateAjaxNew", params={"companyType": ctype, "reportDateType": "1", "code": sec},
                  timeout=20)
        r.raise_for_status()
        dates = [str(d.get("REPORT_DATE", ""))[:10] for d in (r.json().get("data") or [])]
        if dates:
            ctype_used = ctype
            break
    if not ctype_used:
        raise ValueError(f"{sec} 没有年报日期")
    dates = ",".join(dates[:MAX_YEARS])
    for sheet in ("zcfzb", "lrb", "xjllb"):
        lim.wait()
        r = s.get(f"{EM_F10}/{sheet}AjaxNew", timeout=20, params={
            "companyType": ctype_used, "reportDateType": "1", "reportType": "1", "dates": dates, "code": sec})
        r.raise_for_status()
        rows[sheet] = r.json().get("data") or []
    periods = parse_a_rows(rows)
    if not periods:
        raise ValueError(f"{sec} 报表为空")
    return {"currency": "CNY", "standard": "CAS", "periods": periods,
            "source_url": f"{EM_F10}/Index?type=web&code={sec.lower()}", "company_type": ctype_used}


# =====================================================================
#  港股：东方财富港股 F10（长表格式：每行一个科目）。接口参考 AKShare stock_financial_hk_report_em
# =====================================================================
EM_DC = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
HK_MAP = {
    "BALANCE": {
        "totalAssets": ["总资产", "资产总值"], "totalLiabilities": ["总负债", "负债总额"],
        "equity": ["股东权益", "本公司拥有人应占权益", "归属于母公司股东权益", "总权益"],
        "currentAssets": ["流动资产合计"], "currentLiabilities": ["流动负债合计"],
        "cash": ["现金及等价物", "现金及现金等价物"], "inventory": ["存货"],
        "receivables": ["应收帐款", "应收账款", "贸易应收款项", "应收账款及票据"],
        "payables": ["应付帐款", "应付账款", "贸易应付款项", "应付账款及票据"],
    },
    "INCOME": {
        "revenue": ["营业额", "营运收入", "经营收入总额", "总收入", "收入"],
        "cost": ["销售成本", "营运成本", "销售及服务成本"], "grossProfit": ["毛利"],
        "operatingProfit": ["经营溢利", "营运溢利", "经营利润"],
        "netIncome": ["股东应占溢利", "本公司拥有人应占溢利", "公司拥有人应占溢利", "归属于母公司股东的净利润"],
        "rd": ["研发费用", "研究及开发费用", "研究开发费用"],
    },
    "CASHFLOW": {
        "cfo": ["经营业务现金净额", "经营活动产生的现金流量净额", "经营活动现金流量净额"],
        "capex": ["购建固定资产", "购买物业、厂房及设备", "购置物业、厂房及设备"],
    },
}


def parse_hk_rows(rows_by_sheet: dict[str, list[dict]]) -> list[dict]:
    periods: dict[str, dict] = {}
    for sheet, rows in rows_by_sheet.items():
        by_date: dict[str, dict[str, float]] = {}
        for row in rows or []:
            end = str(row.get("REPORT_DATE", ""))[:10]
            name = str(row.get("STD_ITEM_NAME", "")).strip()
            v = _num(row.get("AMOUNT"))
            if end and name and v is not None:
                by_date.setdefault(end, {})[name] = v
        for end, items in by_date.items():
            p = periods.setdefault(end, {"end": end, "label": end[:4]})
            for field, names in HK_MAP[sheet].items():
                val = next((items[n] for n in names if n in items), None)
                if val is None:  # 再尝试“包含”匹配，例如“现金及等价物(期末)”
                    val = next((v for n in names for k, v in items.items() if k.startswith(n)), None)
                if val is not None:
                    p[field] = val
    out = sorted(periods.values(), key=lambda p: p["end"])
    for p in out:
        if "capex" in p:
            p["capex"] = -abs(p["capex"])
        if "cost" in p:
            p["cost"] = abs(p["cost"])
    return out[-MAX_YEARS:]


def fetch_hk(code: str) -> dict:
    code = str(code).zfill(5)
    s = make_session({"Referer": "https://emweb.securities.eastmoney.com/"})
    lim = RateLimiter(0.4)
    r = s.get(EM_DC, timeout=20, params={
        "reportName": "RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY",
        "columns": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,FISCAL_YEAR,CURRENCY,"
                   "ACCOUNT_STANDARD,REPORT_TYPE",
        "quoteColumns": "", "filter": f'(SECUCODE="{code}.HK")', "source": "F10", "client": "PC"})
    r.raise_for_status()
    data = ((r.json().get("result") or {}).get("data") or [{}])[0]
    reports = [x for x in (data.get("REPORT_LIST") or []) if x.get("REPORT_TYPE") == "年报"]
    if not reports:
        raise ValueError(f"{code}.HK 没有年报")
    reports = sorted(reports, key=lambda x: x["REPORT_DATE"])[-MAX_YEARS:]
    dates = [x["REPORT_DATE"].split(" ")[0] for x in reports]
    rows = {}
    for sheet in ("BALANCE", "INCOME", "CASHFLOW"):
        lim.wait()
        r = s.get(EM_DC, timeout=25, params={
            "reportName": f"RPT_HKF10_FN_{sheet}_PC",
            "columns": "SECUCODE,SECURITY_CODE,REPORT_DATE,STD_ITEM_CODE,STD_ITEM_NAME,AMOUNT",
            "quoteColumns": "",
            "filter": f"""(SECUCODE="{code}.HK")(REPORT_DATE in ({",".join("'" + d + "'" for d in dates)}))""",
            "pageNumber": "1", "pageSize": "", "sortTypes": "-1,1", "sortColumns": "REPORT_DATE,STD_ITEM_CODE",
            "source": "F10", "client": "PC"})
        r.raise_for_status()
        rows[sheet] = (r.json().get("result") or {}).get("data") or []
    periods = parse_hk_rows(rows)
    if not periods:
        raise ValueError(f"{code}.HK 报表为空")
    return {"currency": reports[-1].get("CURRENCY") or "HKD",
            "standard": reports[-1].get("ACCOUNT_STANDARD") or "HKFRS/IFRS", "periods": periods,
            "source_url": f"https://emweb.securities.eastmoney.com/PC_HKF10/FinancialAnalysis/index?type=web&code={code}"}


# =====================================================================
#  美股：SEC XBRL companyfacts（官方接口）
# =====================================================================
US_MAP = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "ifrs:Revenue"],
    "cost": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "ifrs:CostOfSales"],
    "grossProfit": ["GrossProfit", "ifrs:GrossProfit"],
    "operatingProfit": ["OperatingIncomeLoss", "ifrs:ProfitLossFromOperatingActivities"],
    "netIncome": ["NetIncomeLoss", "ifrs:ProfitLossAttributableToOwnersOfParent"],
    "rd": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
           "ifrs:ResearchAndDevelopmentExpense"],
    "totalAssets": ["Assets", "ifrs:Assets"],
    "totalLiabilities": ["Liabilities", "ifrs:Liabilities"],
    "equity": ["StockholdersEquity", "ifrs:EquityAttributableToOwnersOfParent"],
    "currentAssets": ["AssetsCurrent", "ifrs:CurrentAssets"],
    "currentLiabilities": ["LiabilitiesCurrent", "ifrs:CurrentLiabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "ifrs:CashAndCashEquivalents"],
    "inventory": ["InventoryNet", "ifrs:Inventories"],
    "receivables": ["AccountsReceivableNetCurrent", "ifrs:TradeAndOtherCurrentReceivables"],
    "payables": ["AccountsPayableCurrent", "ifrs:TradeAndOtherCurrentPayables"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "ifrs:CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "ifrs:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
}
DURATION = {"revenue", "cost", "grossProfit", "operatingProfit", "netIncome", "rd", "cfo", "capex"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "10-KT"}


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _concept_series(facts: dict, concept: str, duration: bool) -> tuple[dict[str, float], str | None]:
    """返回 {期末日期: 数值}（同一期取最新提交的版本，即包含重述）和币种。"""
    tax, name = ("ifrs-full", concept[5:]) if concept.startswith("ifrs:") else ("us-gaap", concept)
    node = ((facts.get(tax) or {}).get(name) or {}).get("units") or {}
    if not node:
        return {}, None
    unit = max(node, key=lambda u: len(node[u]))  # 取数据最多的单位（USD / CNY ...）
    best: dict[str, tuple[str, float]] = {}
    for f in node[unit]:
        if f.get("form") not in ANNUAL_FORMS or f.get("fp") not in ("FY", None):
            continue
        end, val = f.get("end"), _num(f.get("val"))
        if not end or val is None:
            continue
        if duration:
            start = f.get("start")
            if not start or not 340 <= _days(start, end) <= 380:
                continue
        filed = f.get("filed", "")
        if end not in best or filed > best[end][0]:
            best[end] = (filed, val)
    return {k: v[1] for k, v in best.items()}, unit


def parse_sec_facts(data: dict) -> dict:
    facts = data.get("facts") or {}
    series: dict[str, dict[str, float]] = {}
    currency_votes: dict[str, int] = {}
    for field, concepts in US_MAP.items():
        merged: dict[str, float] = {}
        for c in concepts:  # 不同年份可能使用不同科目（例如 2018 年新收入准则后改用 RevenueFromContract...）
            vals, unit = _concept_series(facts, c, field in DURATION)
            for end, v in vals.items():
                merged.setdefault(end, v)
            if vals and unit:
                currency_votes[unit] = currency_votes.get(unit, 0) + len(vals)
        if merged:
            series[field] = merged
    # 年度期末日：以有收入或总资产数据的期末日为准；年度内的期中日期丢弃
    ends = sorted(set(series.get("revenue", {})) & set(series.get("totalAssets", {}))) or \
        sorted(set(series.get("revenue", {})) | set(series.get("totalAssets", {})))
    periods = []
    for end in ends:
        p = {"end": end, "label": end[:4] if end[5:7] == "12" else f"FY{end[:4]}"}
        for field, vals in series.items():
            if end in vals:
                p[field] = vals[end]
        if "totalLiabilities" not in p:
            le = _concept_series(facts, "LiabilitiesAndStockholdersEquity", False)[0].get(end)
            eq_all = _concept_series(facts, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                                     False)[0].get(end) or p.get("equity")
            if le is not None and eq_all is not None:
                p["totalLiabilities"] = le - eq_all
        if "capex" in p:
            p["capex"] = -abs(p["capex"])
        periods.append(p)
    currency = max(currency_votes, key=currency_votes.get) if currency_votes else "USD"
    standard = "IFRS" if "ifrs-full" in facts and "us-gaap" not in facts else "US GAAP"
    return {"currency": currency.split("/")[0], "standard": standard, "periods": periods[-MAX_YEARS:]}


_cik_cache: dict[str, int] = {}


def sec_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "decision-desk")
    return ua or f"Atlas {owner}@users.noreply.github.com"


def fetch_us(ticker: str, session=None) -> dict:
    s = session or make_session({"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"})
    if not _cik_cache:
        r = s.get("https://www.sec.gov/files/company_tickers.json", timeout=30)
        r.raise_for_status()
        for v in r.json().values():
            _cik_cache[v["ticker"].upper()] = int(v["cik_str"])
    cik = _cik_cache.get(ticker.upper())
    if not cik:
        raise ValueError(f"SEC 找不到代码 {ticker}")
    r = s.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", timeout=60)
    r.raise_for_status()
    out = parse_sec_facts(r.json())
    if not out["periods"]:
        raise ValueError(f"{ticker} 没有年度数据")
    out["source_url"] = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K"
    return out


FETCHERS = {"a": fetch_a, "hk": fetch_hk, "us": fetch_us}
