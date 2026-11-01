"""公司公告与财报：A 股（东方财富公告）、港股（港交所披露易）、美股（SEC EDGAR）。"""
from __future__ import annotations

import os
import re

from ..common import (CST, Breaker, RateLimiter, SourceStatus, days_ago, log, make_item, make_session,
                      parse_date, utcnow)
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
_important_cn = re.compile(r"年度报告|半年度报告|季度报告|业绩预告|业绩快报|重大资产重组|问询函|停牌|复牌|退市|立案|回购|分红|派息")
_important_hk = re.compile(r"業績|业绩|盈利警告|內幕消息|内幕消息|回購|回购|派息|股息|停牌|復牌|复牌|Results|Profit Warning|Inside Information")


def _em_date(value: str | None):
    """东方财富时间形如 2026-10-24 18:30:12:466，去掉毫秒再解析（北京时间）。"""
    if not value:
        return None
    return parse_date(str(value)[:19], CST)


# ---------------- A 股：东方财富公告 ----------------
A_TYPES = {"全部": "0", "财务报告": "1", "融资公告": "2", "风险提示": "3", "信息变更": "4",
           "重大事项": "5", "资产重组": "6", "持股变动": "7"}


def parse_em_ann(data: dict) -> list[dict]:
    out = []
    for it in ((data or {}).get("data") or {}).get("list") or []:
        art = it.get("art_code")
        codes = it.get("codes") or []
        if not art or not codes:
            continue
        code = next((c for c in codes if str(c.get("ann_type", "")).startswith("A")), codes[0])
        stock, name = code.get("stock_code", ""), code.get("short_name", "")
        column = ((it.get("columns") or [{}])[0] or {}).get("column_name", "")
        title = it.get("title") or ""
        out.append(make_item(
            id=f"ann-a:{art}", type="filing", source="a_share",
            title=title if name and name in title else f"{name}：{title}",
            url=f"https://data.eastmoney.com/notices/detail/{stock}/{art}.html",
            date=_em_date(it.get("display_time")) or _em_date(it.get("notice_date")),
            markets=["cn"], important=bool(_important_cn.search(f"{title} {column}")),
            tags=[t for t in (column, stock) if t],
        ))
    return out


def fetch_a_share(cfg: dict) -> list[dict]:
    s = make_session({"Referer": "https://data.eastmoney.com/notices/"})
    lim = RateLimiter(0.5)
    begin = days_ago(cfg.get("lookback_days", 7)).astimezone(CST).strftime("%Y-%m-%d")
    end = utcnow().astimezone(CST).strftime("%Y-%m-%d")
    base = {"sr": "-1", "page_index": "1", "ann_type": "A", "client_source": "web", "s_node": "0",
            "begin_time": begin, "end_time": end}
    jobs = [dict(base, page_size="50", f_node="0", stock_list=code) for code in cfg.get("stocks", [])]
    recent = days_ago(2).astimezone(CST).strftime("%Y-%m-%d")
    for t in cfg.get("market_wide_types", []):
        if t in A_TYPES:
            jobs.append(dict(base, page_size=str(cfg.get("market_wide_max", 100)), f_node=A_TYPES[t],
                             begin_time=recent))
    out, errors = [], []
    br = Breaker()
    for params in jobs:
        if br.open():
            break
        lim.wait()
        try:
            r = s.get("https://np-anotice-stock.eastmoney.com/api/security/ann", params=params, timeout=20)
            r.raise_for_status()
            out.extend(parse_em_ann(r.json()))
            br.record(True)
        except Exception as exc:
            br.record(False)
            errors.append(str(exc))
    if errors and not out:
        raise RuntimeError(errors[0])
    return out


# ---------------- 港股：披露易最新公告（实验性） ----------------
def parse_hkex(data: dict, stocks: set[str]) -> list[dict]:
    lst = (data or {}).get("newsInfoLst") or (data or {}).get("newsInfoList") or []
    out = []
    for it in lst:
        sts = it.get("stock") or []
        codes = [str(x.get("sc", "")).zfill(5) for x in sts if isinstance(x, dict)]
        if stocks and not (set(codes) & stocks):
            continue
        name = next((x.get("sn") for x in sts if isinstance(x, dict) and x.get("sn")), "")
        title = it.get("title") or ""
        path = it.get("webPath") or it.get("link") or ""
        url = path if path.startswith("http") else f"https://www1.hkexnews.hk{path}"
        cat = re.sub(r"\s*-\s*\[.*$", "", it.get("lTxt") or "").strip()
        out.append(make_item(
            id=f"ann-hk:{it.get('newsId') or path}", type="filing", source="hkex",
            title=f"{name}：{title}" if name else title, url=url,
            date=parse_date(it.get("relTime"), HKT), markets=["hk"],
            important=bool(_important_hk.search(f"{title} {it.get('lTxt', '')}")),
            tags=[t for t in [cat] + codes[:2] if t],
        ))
    return out


def fetch_hkex(cfg: dict) -> list[dict]:
    s = make_session({"Referer": "https://www1.hkexnews.hk/"})
    lim = RateLimiter(0.6)
    stocks = {str(c).zfill(5) for c in cfg.get("stocks", [])}
    out = []
    for page in range(1, cfg.get("pages", 3) + 1):
        lim.wait()
        r = s.get(f"https://www1.hkexnews.hk/ncms/json/eds/lcisehk1relsdc_{page}.json", timeout=20)
        if r.status_code == 404:
            break
        r.raise_for_status()
        out.extend(parse_hkex(r.json(), stocks))
    return out


# ---------------- 美股：SEC EDGAR ----------------
FORM_IMPORTANT = {"10-K", "10-Q", "20-F", "S-1", "F-1"}


def sec_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if ua:
        return ua
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "finance-radar")
    return f"FinanceRadar {owner}@users.noreply.github.com"


def parse_sec(data: dict, ticker: str, forms: set[str], since) -> list[dict]:
    cik = int(data.get("cik") or 0)
    name = data.get("name") or ticker
    rec = ((data.get("filings") or {}).get("recent")) or {}
    n = len(rec.get("accessionNumber") or [])
    out = []
    for i in range(n):
        form = rec["form"][i]
        if forms and form not in forms:
            continue
        acc = rec["accessionNumber"][i]
        dt = parse_date(rec.get("acceptanceDateTime", [None] * n)[i]) or parse_date(rec["filingDate"][i])
        if since and dt and dt < since:
            continue
        doc = (rec.get("primaryDocument") or [""] * n)[i]
        desc = (rec.get("primaryDocDescription") or [""] * n)[i] or form
        items = (rec.get("items") or [""] * n)[i] or ""
        folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
        out.append(make_item(
            id=f"sec:{acc}", type="filing", source="sec",
            title=f"{name} ({ticker}) {form}：{desc}",
            url=f"{folder}/{doc}" if doc else f"{folder}/",
            date=dt, markets=["us"],
            important=form in FORM_IMPORTANT or "2.02" in items,
            tags=[form, ticker] + ([f"Item {x}" for x in items.split(",") if x][:3]),
        ))
    return out


def fetch_sec(cfg: dict) -> list[dict]:
    s = make_session({"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"})
    lim = RateLimiter(0.25)  # SEC 上限每秒 10 次，这里远低于上限
    r = s.get("https://www.sec.gov/files/company_tickers.json", timeout=30)
    r.raise_for_status()
    cik_map = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    since = days_ago(cfg.get("lookback_days", 14))
    forms = set(cfg.get("forms") or [])
    out, missing = [], []
    br = Breaker()
    for t in cfg.get("tickers", []):
        cik = cik_map.get(t.upper())
        if not cik:
            missing.append(t)
            continue
        if br.open():
            break
        lim.wait()
        try:
            r = s.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", timeout=30)
            r.raise_for_status()
            out.extend(parse_sec(r.json(), t.upper(), forms, since))
            br.record(True)
        except Exception as exc:
            br.record(False)
            log.warning("SEC %s 失败：%s", t, exc)
    if missing:
        log.warning("SEC 找不到这些代码：%s", ", ".join(missing))
    return out


def fetch(cfg: dict, status: SourceStatus) -> list[dict]:
    jobs = [("a_share", "A 股公告", fetch_a_share), ("hkex", "港交所披露易", fetch_hkex),
            ("sec", "SEC EDGAR", fetch_sec)]
    out: list[dict] = []
    for sid, name, fn in jobs:
        scfg = cfg.get(sid) or {}
        if not scfg.get("enabled", True):
            continue
        try:
            items = fn(scfg)
            log.info("公告 %s → %d", name, len(items))
            status.ok(sid, len(items), name)
            out.extend(items)
        except Exception as exc:
            status.fail(sid, exc, name)
    return out
