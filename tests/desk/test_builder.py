"""离线测试：解析、指标、观察、与前端公式一致性、知识库、完整构建流程。运行：python -m pytest -q"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pipelines.desk import common
from pipelines.desk import run as runner
from pipelines.desk.financials import extract, metrics
from pipelines.desk.sources import news

ROOT = Path(__file__).resolve().parent.parent.parent
FX = Path(__file__).parent / "fixtures"
NOW = common.parse_date("2026-10-26T02:00:00Z")


def j(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


# ---------------- 资讯 ----------------
def test_rss_and_google_news():
    items = news.parse_feed((FX / "feed.xml").read_bytes(), {"id": "corpgov", "topics": ["governance"]}, 280)
    assert items[0]["summary"] == "Directors and the CFO weigh in." and items[0]["topics"] == ["governance"]
    g = news.parse_feed((FX / "gnews.xml").read_bytes(), {"id": "hbr", "via": "Google News"}, 280)
    assert g[0]["title"] == "Test fixture: Why Good Managers Fail" and g[0]["summary"] == ""


def test_gov_list():
    src = {"id": "mof-kjs", "link_pattern": r"t\d{8}_\d+\.s?html?$", "topics": ["finance"]}
    items = news.parse_gov_list((FX / "gov_mof.html").read_text(), src, "https://kjs.mof.gov.cn/zhengcefabu/")
    assert len(items) == 2
    assert items[0]["url"] == "https://kjs.mof.gov.cn/zhengcefabu/202606/t20260615_3991686.htm"
    assert items[0]["date"] == "2026-06-14T16:00:00Z"  # 北京时间 6 月 15 日 0 点
    assert items[0]["kind"] == "policy" and items[0]["region"] == "cn"
    src2 = {"id": "csrc", "link_pattern": r"/csrc/c100028/c\d+/content\.shtml$"}
    items2 = news.parse_gov_list((FX / "gov_csrc.html").read_text(), src2, "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml")
    assert [i["date"] for i in items2] == ["2026-09-10T16:00:00Z", None]  # 日期取自相邻文字


# ---------------- 财报抽取 ----------------
def test_a_share():
    periods = extract.parse_a_rows({"zcfzb": j("a_zcfzb.json")["data"], "lrb": j("a_lrb.json")["data"],
                                    "xjllb": j("a_xjllb.json")["data"]})
    assert [p["end"] for p in periods] == ["2023-12-31", "2024-12-31", "2025-12-31"]
    p = periods[-1]
    assert p["equity"] == 760 and p["netIncome"] == 110 and p["capex"] == -90 and p["rd"] == 60
    assert periods[1]["receivables"] == 100  # ACCOUNTS_RECE 优先于 NOTE_ACCOUNTS_RECE
    assert extract.a_secucode("600519") == "SH600519" and extract.a_secucode("300750") == "SZ300750"
    assert extract.a_secucode("830799") == "BJ830799"


def test_hk():
    periods = extract.parse_hk_rows({s: j(f"hk_{s}.json")["result"]["data"] for s in ("BALANCE", "INCOME", "CASHFLOW")})
    p = periods[-1]
    assert p["revenue"] == 1500 and p["cost"] == 700 and p["grossProfit"] == 800 and p["netIncome"] == 380
    assert p["capex"] == -150 and p["receivables"] == 120 and periods[0]["equity"] == 960


def test_sec():
    out = extract.parse_sec_facts(j("sec_facts.json"))
    ends = [p["end"] for p in out["periods"]]
    assert ends == ["2023-09-30", "2024-09-28", "2025-09-27"]  # 2025-06-28 的“FY”只有 9 个月，被剔除
    p24, p25 = out["periods"][1], out["periods"][2]
    assert p24["revenue"] == 905  # 同一期取最新提交（重述后的）数值
    assert out["periods"][0]["revenue"] == 800  # 早年用的是 Revenues 科目
    assert p25["totalLiabilities"] == 900  # 没有 Liabilities 时用 负债和权益合计 − 权益
    assert p25["label"] == "FY2025" and out["currency"] == "USD" and out["standard"] == "US GAAP"


# ---------------- 指标 ----------------
def test_ratios_and_observations():
    periods = metrics.with_ratios(extract.parse_a_rows({"zcfzb": j("a_zcfzb.json")["data"],
                                                        "lrb": j("a_lrb.json")["data"], "xjllb": j("a_xjllb.json")["data"]}))
    r = periods[-1]["ratios"]
    assert abs(r["grossMargin"] - 0.35) < 1e-9
    assert abs(r["roe"] - 110 / 700) < 1e-6
    assert abs(r["revenueGrowth"] - 0.2) < 1e-9 and abs(r["profitGrowth"] - (110 / 120 - 1)) < 1e-6
    assert r["fcf"] == -20
    obs = metrics.observations(periods, {"debtRatio": 0.2, "roe": 0.1, "equityMultiplier": 1.5})
    texts = " ".join(o["text"] for o in obs)
    assert "毛利率连续 3 年下降" in texts       # 40% → 38% → 35%
    assert "增收不增利" in texts                 # 收入 +20%，利润 -8.3%
    assert "经营现金流不到净利润的 80%" in texts  # 2024: 80/120, 2025: 70/110
    assert "资产负债率" in texts
    meds = metrics.industry_medians([{"industry": "x", "periods": periods}] * 3)
    assert meds["x"]["_n"] == 3 and abs(meds["x"]["grossMargin"] - 0.35) < 1e-9


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 Node.js")
def test_ratios_match_frontend():
    """Python 与前端 fin.js 的 ratios() 必须给出相同结果。"""
    cur = {"revenue": 1200, "cost": 780, "operatingProfit": 160, "netIncome": 110, "rd": 60, "totalAssets": 1300,
           "totalLiabilities": 520, "equity": 760, "currentAssets": 700, "currentLiabilities": 400, "cash": 300,
           "inventory": 150, "receivables": 160, "payables": 120, "cfo": 70, "capex": -90}
    prev = {"revenue": 1000, "netIncome": 120, "totalAssets": 1100, "equity": 640, "inventory": 110,
            "receivables": 100, "payables": 100}
    js = subprocess.run(["node", "-e", f"const F=require('{ROOT}/site/assets/fin.js');"
                         f"console.log(JSON.stringify(F.ratios({json.dumps(cur)},{json.dumps(prev)})))"],
                        capture_output=True, text=True, check=True)
    a, b = json.loads(js.stdout), metrics.ratios(cur, prev)
    assert set(a) == set(b)
    for k in a:
        assert (a[k] is None and b[k] is None) or abs(a[k] - b[k]) < 1e-5, k


# ---------------- 知识库 ----------------
def test_kb_builds():
    from pipelines.desk import kb
    data = kb.build(ROOT / "content" / "kb")
    assert len(data["articles"]) >= 25
    for a in data["articles"]:
        assert a["chars"] > 300, f"{a['id']} 正文太短"
        assert "<h2" in a["html"], f"{a['id']} 缺少小标题"


# ---------------- 完整流程（模拟网络） ----------------
class Resp:
    def __init__(self, body, status=200, url=""):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.text = self.content.decode("utf-8")
        self.encoding, self.apparent_encoding, self.url = "utf-8", "utf-8", url

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
        if "zcfzbDate" in url:
            return Resp(j("a_dates.json"))
        for sheet in ("zcfzb", "lrb", "xjllb"):
            if f"/{sheet}AjaxNew" in url:
                return Resp(j(f"a_{sheet}.json"))
        if "datacenter.eastmoney.com" in url:
            rn = p.get("reportName", "")
            if "SUMMARY" in rn:
                return Resp(j("hk_list.json"))
            for s in ("BALANCE", "INCOME", "CASHFLOW"):
                if s in rn:
                    return Resp(j(f"hk_{s}.json"))
        if "company_tickers" in url:
            return Resp({"0": {"cik_str": 320193, "ticker": "AAPL"}, "1": {"cik_str": 1, "ticker": "MSFT"}})
        if "companyfacts/CIK0000320193" in url:
            return Resp(j("sec_facts.json"))
        if "companyfacts" in url:
            return Resp("not found", 404)
        if "mof.gov.cn" in url:
            return Resp((FX / "gov_mof.html").read_text(), url=url)
        if "csrc.gov.cn" in url:
            return Resp((FX / "gov_csrc.html").read_text(), url=url)
        if "google" in url:
            return Resp((FX / "gnews.xml").read_bytes())
        if "36kr" in url or "sasac" in url or "chinatax" in url:
            return Resp("blocked", 403)
        return Resp((FX / "feed.xml").read_bytes())


@pytest.fixture
def offline(monkeypatch, tmp_path):
    from pipelines.desk.financials import extract as ex
    from pipelines.desk.sources import news as nw
    for mod in (ex, nw, common):
        monkeypatch.setattr(mod, "make_session", FakeSession)
    monkeypatch.setattr(common.RateLimiter, "wait", lambda self: None)
    for mod in (runner, nw, common):
        monkeypatch.setattr(mod, "utcnow", lambda: NOW)
    monkeypatch.setattr(nw, "days_ago", lambda n: NOW - common.timedelta(days=n))
    monkeypatch.setattr(runner, "DATA", tmp_path)
    ex._cik_cache.clear()
    cfg = {"industries": {"food": "食品饮料"}, "companies": [
        {"market": "a", "code": "600519", "name": "样本A", "industry": "food"},
        {"market": "hk", "code": "00700", "name": "样本港股", "industry": "food"},
        {"market": "us", "code": "AAPL", "name": "样本美股", "industry": "food"},
        {"market": "us", "code": "MSFT", "name": "失败样本", "industry": "food"}]}
    real = runner.load_yaml

    def fake_yaml(n):
        if n == "companies.yaml":
            return cfg
        data = real(n)
        # 证监会已改走 RSSHub；这里补一个网页列表样本，继续覆盖“没有发布日期的政策条目”的处理
        data["gov_lists"] = data["gov_lists"] + [{
            "id": "csrc-page", "name": "证监会（网页样本）", "url": "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml",
            "link_pattern": r"/csrc/c100028/c\d+/content\.shtml$", "topics": ["governance"]}]
        return data
    monkeypatch.setattr(runner, "load_yaml", fake_yaml)
    return tmp_path


def test_full_build(offline):
    assert runner.main([]) == 0
    meta = json.loads((offline / "meta.json").read_text())
    st = meta["sources_status"]
    assert st["mof-kjs"]["ok"] and st["hbr"]["ok"] and not st["36kr"]["ok"]
    assert st["fin-us"]["ok"] and "1 家失败" in st["fin-us"]["partial"]
    nws = json.loads((offline / "news.json").read_text())
    titles = [i["title"] for i in nws["items"]]
    assert "Test fixture: Old item" not in titles
    est = [i for i in nws["items"] if i.get("date_estimated")]
    assert est and all(i.get("backfill") for i in est)  # 第一次抓到、没有日期的政策条目被标记
    board = next(i for i in nws["items"] if "boards" in i["title"])
    assert "governance" in board["topics"] and "strategy" in board["topics"]
    idx = json.loads((offline / "companies" / "index.json").read_text())
    assert {c["id"] for c in idx["companies"]} == {"a-600519", "hk-00700", "us-aapl"}
    food = next(i for i in idx["industries"] if i["id"] == "food")
    assert food["median"]["_n"] == 3 and "grossMargin" in food["median"]
    a = json.loads((offline / "companies" / "a-600519.json").read_text())
    assert a["observations"] and a["peers"] == ["hk-00700", "us-aapl"]
    kbj = json.loads((offline / "kb.json").read_text())
    assert len(kbj["articles"]) >= 25
    # 第二次运行：财报接口全部失败时沿用上次数据并标记 stale
    runner_fail = FakeSession.get
    FakeSession.get = lambda self, url, params=None, timeout=None: Resp("down", 503)
    try:
        assert runner.main(["--only", "financials"]) == 0
    finally:
        FakeSession.get = runner_fail
    idx2 = json.loads((offline / "companies" / "index.json").read_text())
    assert len(idx2["companies"]) == 3 and all(c["stale"] for c in idx2["companies"])
