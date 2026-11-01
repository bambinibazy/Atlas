"""中文 7x24 快讯：财联社电报、新浪财经、东方财富、同花顺。

接口地址与参数参考开源项目 AKShare（stock_info_global_*）的实现。
这些都是网站前端使用的非公开接口，可能随网站改版变化；
某个源失败只会在页面底部“数据源状态”里显示红点，不影响其他源。
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from urllib.parse import urlencode

from ..common import (CST, RateLimiter, SourceStatus, clean_text, log, make_item, make_session,
                      parse_date, split_bracket_title, strip_html)


def _flash(source: str, uid: str, title: str, body: str, url: str, date: datetime | None,
           smax: int, important: bool = False) -> dict:
    body = strip_html(body)
    t2, body = split_bracket_title(body)
    title = strip_html(title) or t2
    if not title:
        # 没有标题的快讯：用第一句话当标题，其余作为摘要
        first = body.split("。")[0]
        if len(first) <= 90:
            title, body = first, body[len(first) + 1:].strip()
        else:
            title, body = body[:80] + "…", body
    if body.startswith(title):
        body = body[len(title):].lstrip("。，, ")
    return make_item(id=f"{source}:{uid}", type="flash", source=source, title=title, url=url,
                     date=date, summary=clean_text(body, smax), important=important)


# ---------------- 财联社 ----------------
def cls_sign(params: dict) -> str:
    return hashlib.md5(hashlib.sha1(urlencode(params).encode()).hexdigest().encode()).hexdigest()


def parse_cls(data: dict, smax: int) -> list[dict]:
    out = []
    for it in ((data or {}).get("data") or {}).get("roll_data") or []:
        if not it.get("id"):
            continue
        out.append(_flash(
            "cls", str(it["id"]), it.get("title") or "", it.get("content") or it.get("brief") or "",
            it.get("shareurl") or f"https://www.cls.cn/detail/{it['id']}",
            parse_date(it.get("ctime")), smax,
            important=str(it.get("level", "")).upper() in ("A", "B"),
        ))
    return out


def fetch_cls(cfg: dict, smax: int, since: datetime | None) -> list[dict]:
    s = make_session({"Referer": "https://www.cls.cn/telegraph"})
    lim = RateLimiter(1.0)
    last_time = int(time.time())
    out: list[dict] = []
    for _ in range(cfg.get("pages", 6)):
        params = {"app": "CailianpressWeb", "category": "", "last_time": last_time, "os": "web",
                  "refresh_type": "1", "rn": "50", "sv": "8.4.6"}
        params["sign"] = cls_sign(params)
        lim.wait()
        r = s.get("https://www.cls.cn/v1/roll/get_roll_list", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        page = parse_cls(data, smax)
        if not page:
            break
        out.extend(page)
        oldest = min(int(x.get("ctime") or last_time) for x in data["data"]["roll_data"])
        if oldest >= last_time or (since and oldest < since.timestamp()):
            break
        last_time = oldest
    return out


# ---------------- 新浪财经 ----------------
def parse_sina(data: dict, smax: int) -> list[dict]:
    feed = (((data or {}).get("result") or {}).get("data") or {}).get("feed") or {}
    out = []
    for it in feed.get("list") or []:
        if not it.get("id"):
            continue
        tag_names = [t.get("name", "") for t in (it.get("tag") or []) if isinstance(t, dict)]
        out.append(_flash(
            "sina", str(it["id"]), "", it.get("rich_text") or "",
            it.get("docurl") or "https://finance.sina.com.cn/7x24/",
            parse_date(it.get("create_time"), CST), smax,
            important=any(n in ("焦点", "重要") for n in tag_names),
        ))
    return out


def fetch_sina(cfg: dict, smax: int, since: datetime | None) -> list[dict]:
    s = make_session({"Referer": "https://finance.sina.com.cn/7x24/"})
    lim = RateLimiter(0.8)
    out: list[dict] = []
    for page in range(1, cfg.get("pages", 3) + 1):
        lim.wait()
        r = s.get("https://zhibo.sina.com.cn/api/zhibo/feed", timeout=20, params={
            "page": page, "page_size": 100, "zhibo_id": 152, "tag_id": 0, "dire": "f",
            "dpc": 1, "pagesize": 100, "type": 1})
        r.raise_for_status()
        items = parse_sina(r.json(), smax)
        if not items:
            break
        out.extend(items)
        if since and min(parse_date(i["date"]) for i in items) < since:
            break
    return out


# ---------------- 东方财富 ----------------
def parse_eastmoney(data: dict, smax: int) -> list[dict]:
    out = []
    for it in ((data or {}).get("data") or {}).get("fastNewsList") or []:
        code = it.get("code")
        if not code:
            continue
        out.append(_flash(
            "eastmoney", str(code), it.get("title") or "", it.get("summary") or "",
            f"https://finance.eastmoney.com/a/{code}.html",
            parse_date(it.get("showTime"), CST), smax,
        ))
    return out


def fetch_eastmoney(cfg: dict, smax: int, since: datetime | None) -> list[dict]:
    s = make_session({"Referer": "https://kuaixun.eastmoney.com/"})
    r = s.get("https://np-weblist.eastmoney.com/comm/web/getFastNewsList", timeout=20, params={
        "client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "",
        "pageSize": "200", "req_trace": str(int(time.time() * 1000))})
    r.raise_for_status()
    return parse_eastmoney(r.json(), smax)


# ---------------- 同花顺 ----------------
def parse_ths(data: dict, smax: int) -> list[dict]:
    out = []
    for it in ((data or {}).get("data") or {}).get("list") or []:
        if not it.get("id"):
            continue
        out.append(_flash(
            "ths", str(it["id"]), it.get("title") or "", it.get("digest") or "",
            it.get("url") or "https://news.10jqka.com.cn/realtimenews.html",
            parse_date(it.get("rtime") or it.get("ctime")), smax,
        ))
    return out


def fetch_ths(cfg: dict, smax: int, since: datetime | None) -> list[dict]:
    s = make_session({"Referer": "https://news.10jqka.com.cn/realtimenews.html"})
    lim = RateLimiter(0.8)
    out: list[dict] = []
    for page in range(1, cfg.get("pages", 2) + 1):
        lim.wait()
        r = s.get("https://news.10jqka.com.cn/tapp/news/push/stock", timeout=20,
                  params={"page": page, "tag": "", "track": "website", "pagesize": 100})
        r.raise_for_status()
        items = parse_ths(r.json(), smax)
        if not items:
            break
        out.extend(items)
    return out


FETCHERS = {"cls": fetch_cls, "sina": fetch_sina, "eastmoney": fetch_eastmoney, "ths": fetch_ths}


def fetch(cfg: dict, smax: int, since: datetime | None, status: SourceStatus) -> list[dict]:
    out: list[dict] = []
    for sid, fn in FETCHERS.items():
        scfg = cfg.get(sid) or {}
        if not scfg.get("enabled", True):
            continue
        name = (scfg.get("name") or {}).get("zh", sid)
        try:
            items = fn(scfg, smax, since)
            log.info("快讯 %s → %d", name, len(items))
            status.ok(sid, len(items), name)
            out.extend(items)
        except Exception as exc:
            status.fail(sid, exc, name)
    return out
