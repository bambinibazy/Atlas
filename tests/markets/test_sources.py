"""离线测试：用各接口格式的样本验证解析、分类、合并与整个运行流程。运行：python -m pytest -q"""
import json
from pathlib import Path

import pytest

from pipelines.markets import common
from pipelines.markets import run as runner
from pipelines.markets.classify import Classifier, KeywordMatcher, merge_similar
from pipelines.markets.common import parse_date
from pipelines.markets.sources import filings, flash_cn, macro, quotes, rss

FX = Path(__file__).parent / "fixtures"
CFG = runner.load_config()
NOW = parse_date("2026-10-25T02:00:00Z")


def j(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_fixture_clock():
    assert parse_date(1792850400).isoformat() == "2026-10-24T14:00:00+00:00"


# ---------------- 快讯 ----------------
def test_cls():
    items = flash_cn.parse_cls(j("cls.json"), 360)
    a, b = items
    assert a["id"] == "cls:900001" and a["important"] and a["title"] == "测试样本：央行开展逆回购操作"
    assert not a["summary"].startswith("【")  # 去掉了重复的【标题】
    assert not b["important"]
    assert b["title"] == "测试样本：沪指收涨0.8%，两市成交额超1万亿元" and b["summary"].startswith("创业板")


def test_sina_eastmoney_ths():
    s = flash_cn.parse_sina(j("sina.json"), 360)
    assert s[0]["important"] and s[0]["date"] == "2026-10-24T14:01:00Z"  # 北京时间转 UTC
    assert "<b>" not in s[1]["title"]
    e = flash_cn.parse_eastmoney(j("em_flash.json"), 360)
    assert e[0]["url"].endswith("202610243000001.html") and e[0]["date"] == "2026-10-24T08:10:00Z"
    t = flash_cn.parse_ths(j("ths.json"), 360)
    assert t[0]["title"].startswith("测试样本：美联储")


def test_cls_sign_stable():
    p = {"app": "CailianpressWeb", "category": "", "last_time": 1, "os": "web", "refresh_type": "1",
         "rn": "50", "sv": "8.4.6"}
    assert len(flash_cn.cls_sign(p)) == 32


# ---------------- RSS ----------------
def test_rss():
    items = rss.parse_feed((FX / "cnbc.xml").read_bytes(),
                           {"id": "cnbc-top", "markets": ["us"], "type": "news"}, 360)
    assert len(items) == 3 and items[0]["summary"].startswith("Wall Street")
    assert items[0]["date"] == "2026-10-24T20:05:00Z" and items[0]["markets"] == ["us"]


# ---------------- 公告 ----------------
def test_filings():
    a = filings.parse_em_ann(j("em_ann.json"))
    assert a[0]["important"] and a[0]["date"] == "2026-10-24T10:30:12Z"
    assert a[0]["title"].startswith("测试样本公司") and "600519" in a[0]["tags"]
    assert a[1]["title"].startswith("测试样本二") and not a[1]["important"]
    h = filings.parse_hkex(j("hkex.json"), {"00700"})
    assert len(h) == 1 and h[0]["important"] and h[0]["date"] == "2026-10-24T09:05:00Z"
    assert h[0]["url"].startswith("https://www1.hkexnews.hk/listedco/")
    sec = filings.parse_sec(j("sec_submissions.json"), "AAPL", {"8-K", "10-Q"}, parse_date("2026-10-01"))
    assert len(sec) == 1 and sec[0]["important"]  # 8-K Item 2.02 = 业绩发布
    assert sec[0]["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000101/test-8k.htm"


# ---------------- 行情 ----------------
def test_quotes_parsers():
    it = {"id": "sh", "name": {"zh": "上证", "en": "SSE"}}
    r = quotes.parse_em_kline(j("em_kline.json"), it, 10)
    assert r["last"] == 3320 and r["prev"] == 3315 and round(r["pct"], 3) == round(5 / 3315 * 100, 3)
    assert len(r["spark"]) == 10 and r["as_of"] == "2026-10-24"
    y = quotes.parse_yields(j("yields.json"), [
        {"id": "us10y", "name": {}, "field": "EMG00001310"}, {"id": "us2y", "name": {}, "field": "EMG00001306"}], 30)
    assert y["us10y"]["chg"] == -3.0 and y["us10y"]["change_unit"] == "bp"
    assert y["us2y"]["last"] == 3.60  # 跳过空值
    g = quotes.parse_gecko(j("gecko_markets.json"), {"bitcoin": j("gecko_chart.json")},
                           [{"id": "btc", "name": {}, "coin": "bitcoin"}], 30)
    assert g["btc"]["last"] == 70000 and round(g["btc"]["pct"], 2) == 2.5 and len(g["btc"]["spark"]) == 30


# ---------------- 宏观 ----------------
def test_macro():
    e = macro.parse_cn(j("macro_cpi.json"), {"id": "cn-cpi", "name": {}, "field": "NATIONAL_SAME", "unit": "%"})
    assert e["period"] == "2026-09" and e["value"] == 0.4 and e["prev"] == 0.1
    lpr = macro.parse_cn(j("macro_lpr.json"), {"id": "lpr", "name": {}, "field": "LPR1Y", "date_field": "TRADE_DATE"})
    assert [h["v"] for h in lpr["history"]] == [3.1, 3.0]  # 只保留变动
    assert macro.cn_period("2026年第1-3季度", None) == "2026Q1-3"
    obs = macro.parse_fred_csv((FX / "fred_cpi.csv").read_text())
    pts = macro.transform(obs, {"series": "CPIAUCSL", "change": "yoy"})
    assert pts[-1][0] == "2026-09" and round(pts[-1][1], 3) == round((332 / 320 - 1) * 100, 3)
    gdp = macro.fred_period("2026-07-01", {"series": "A191RL1Q225SBEA"})
    assert gdp == "2026Q3"


# ---------------- 分类与合并 ----------------
def test_keyword_matcher():
    m = KeywordMatcher(["oil", "=Fed", "恒指"])
    assert m.matches("Oil prices and the Fed") == {"oil", "Fed"}
    assert m.matches("boiling federal") == set()
    assert m.matches("恒指收涨") == {"恒指"}


def test_classify_and_merge():
    clf = Classifier(CFG)
    items = flash_cn.parse_cls(j("cls.json"), 360) + flash_cn.parse_sina(j("sina.json"), 360) \
        + flash_cn.parse_eastmoney(j("em_flash.json"), 360)
    for i in items:
        clf.apply(i)
    by = {i["id"]: i for i in items}
    assert "cn" in by["cls:900002"]["markets"]
    assert "crypto" in by["sina:700002"]["markets"]
    assert "hk" in by["eastmoney:202610243000001"]["markets"]
    assert by["cls:900001"]["macro"]  # 央行逆回购 → 宏观政策
    merged = merge_similar(items)
    ids = {i["id"] for i in merged}
    assert "cls:900001" in ids and "sina:700001" not in ids  # 同一事件只留最早一条
    m = next(i for i in merged if i["id"] == "cls:900001")
    assert m["sources"] == ["cls", "sina"] and m["alt_urls"]["sina"]


def test_macro_release_items():
    old = [{"id": "cn-cpi", "period": "2026-08", "region": "cn"}]
    new = [{"id": "cn-cpi", "period": "2026-09", "region": "cn", "value": 0.4, "prev": 0.1, "unit": "%",
            "name": {"zh": "CPI 同比", "en": "CPI YoY"}, "url": "https://data.eastmoney.com/cjsj/cpi.html"}]
    items = runner.macro_release_items(new, old)
    assert items[0]["title"] == "中国 2026-09 CPI 同比 0.4%，前值 0.1%" and items[0]["type"] == "policy"
    assert runner.macro_release_items(new, []) == []  # 首次运行不生成


# ---------------- 完整流程（模拟网络） ----------------
class Resp:
    def __init__(self, body, status=200):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.text = self.content.decode("utf-8")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, *a, **k):
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        p = params or {}
        routes = [
            ("cls.cn", lambda: j("cls.json")), ("zhibo.sina", lambda: j("sina.json")),
            ("getFastNewsList", lambda: j("em_flash.json")), ("10jqka", lambda: j("ths.json")),
            ("np-anotice", lambda: j("em_ann.json")), ("hkexnews", lambda: j("hkex.json")),
            ("company_tickers", lambda: j("sec_tickers.json")), ("data.sec.gov", lambda: j("sec_submissions.json")),
            ("coins/markets", lambda: j("gecko_markets.json")), ("market_chart", lambda: j("gecko_chart.json")),
            ("kline/get", lambda: j("em_kline.json")), ("TREASURYYIELD", lambda: j("yields.json")),
            ("datacenter-web", lambda: j("macro_lpr.json") if p.get("reportName") == "RPTA_WEB_RATE" else j("macro_cpi.json")),
            ("fredgraph", lambda: (FX / "fred_cpi.csv").read_text()),
            ("ft.com", lambda: Resp("blocked", 403)),  # 模拟一个 RSS 源失败
            ("", lambda: (FX / "cnbc.xml").read_bytes()),
        ]
        key = url + " " + json.dumps(p, ensure_ascii=False)
        for needle, fn in routes:
            if needle in key:
                body = fn()
                return body if isinstance(body, Resp) else Resp(body)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    from pipelines.markets.sources import flash_cn as f, rss as r, filings as fl, quotes as q, macro as m
    for mod in (f, r, fl, q, m):
        monkeypatch.setattr(mod, "make_session", FakeSession)
    monkeypatch.setattr(common.RateLimiter, "wait", lambda self: None)
    for mod in (runner, common, fl, q):
        monkeypatch.setattr(mod, "utcnow", lambda: NOW)
    monkeypatch.setattr(common, "utcnow", lambda: NOW)
    for mod in (r, fl, m):
        monkeypatch.setattr(mod, "days_ago", lambda n: NOW - common.timedelta(days=n))
    monkeypatch.setattr(runner, "DATA_DIR", tmp_path)
    return tmp_path


def test_full_run(offline):
    assert runner.main([]) == 0
    meta = json.loads((offline / "meta.json").read_text())
    items = json.loads((offline / "items.json").read_text())["items"]
    qs = json.loads((offline / "quotes.json").read_text())
    mc = json.loads((offline / "macro.json").read_text())
    st = meta["sources_status"]
    assert st["ft-markets"]["ok"] is False and st["cls"]["ok"] and st["sec"]["ok"]
    types = {i["type"] for i in items}
    assert {"flash", "news", "filing"} <= types
    assert all(i["markets"] is not None for i in items)
    assert not any(i["title"] == "Old item" for i in items)  # 过期 RSS 被丢弃
    rows = {r["id"]: r for g in qs["groups"] for r in g["rows"]}
    assert rows["sh"]["last"] == 3320 and rows["btc"]["last"] == 70000 and rows["cn10y"]["last"] == 1.85
    assert {e["id"] for e in mc["indicators"]} >= {"cn-cpi", "us-cpi"}
    # 第二次运行：已有条目保留 first_seen，行情失败时沿用旧值
    first_seen = {i["id"]: i["first_seen"] for i in items}
    assert runner.main(["--only", "flash"]) == 0
    items2 = json.loads((offline / "items.json").read_text())["items"]
    assert all(first_seen.get(i["id"], i["first_seen"]) == i["first_seen"] for i in items2)
    assert json.loads((offline / "quotes.json").read_text())["groups"]
