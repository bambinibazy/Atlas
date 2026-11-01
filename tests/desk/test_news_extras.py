"""合并财管日报后新增的资讯能力：RSSHub 路由、关键词过滤、文章类列表页、聚合 RSS。"""
import types
from pathlib import Path

from pipelines.desk.common import SourceStatus
from pipelines.desk.sources import news

FX = Path(__file__).parent / "fixtures"
FEED = (FX / "feed.xml").read_bytes()

LIST_HTML = """<html><body><ul>
<li><a href="/cn/zh/home/insights/2026/10/cfo-agenda-2027.html">2027年首席财务官议程：AI 驱动的财务转型</a> 2026-10-20</li>
<li><a href="/cn/zh/home/insights/2026/10/cfo-agenda-2027.print.html">2027年首席财务官议程（打印版）</a></li>
<li><a href="/cn/zh/home/insights/2026/09/esg.html">中国可持续披露准则实施观察</a> 2026-09-30</li>
<li><a href="/cn/zh/home/insights/2026/09/x.html">更多</a></li>
<li><a href="/cn/zh/home/about.html">关于我们的介绍页面</a></li>
</ul></body></html>"""


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                if body is None:
                    raise ConnectionError("refused")
                return types.SimpleNamespace(content=body, text=body.decode() if isinstance(body, bytes) else body,
                                             raise_for_status=lambda: None, encoding="utf-8",
                                             apparent_encoding="utf-8", url=url)
        raise AssertionError("unexpected url " + url)


def test_rsshub_falls_back_to_public(monkeypatch):
    monkeypatch.setenv("RSSHUB_BASE", "http://localhost:1200")
    monkeypatch.setenv("RSSHUB_FALLBACKS", "https://rsshub.example")
    sess = FakeSession({"http://localhost:1200": None, "https://rsshub.example": FEED})
    monkeypatch.setattr(news, "make_session", lambda *a, **k: sess)
    st = SourceStatus()
    items = news.fetch_rss([{"id": "pp", "name": "澎湃", "route": "/thepaper/list/1", "region": "cn"}],
                           200, st, max_age_days=100000)
    assert items and all(i["source"] == "pp" and i["region"] == "cn" for i in items)
    assert sess.calls == ["http://localhost:1200/thepaper/list/1", "https://rsshub.example/thepaper/list/1"]
    assert st.status["pp"]["ok"]


def test_rsshub_all_fail_is_reported(monkeypatch):
    monkeypatch.setenv("RSSHUB_FALLBACKS", "")
    monkeypatch.setattr(news, "make_session", lambda *a, **k: FakeSession({"http://localhost:1200": None}))
    st = SourceStatus()
    assert news.fetch_rss([{"id": "pp", "name": "澎湃", "route": "/x"}], 200, st, 30) == []
    assert not st.status["pp"]["ok"] and "RSSHub" in st.status["pp"]["error"]


def test_keyword_filter():
    src = {"keywords": ["财务", "审计"], "exclude_keywords": ["广告"]}
    assert news.keyword_ok({"title": "央企财务共享建设", "summary": ""}, src)
    assert not news.keyword_ok({"title": "新款手机发布", "summary": "消费电子"}, src)
    assert not news.keyword_ok({"title": "审计软件广告", "summary": ""}, src)
    assert news.keyword_ok({"title": "anything"}, {})


def test_page_list_as_articles():
    src = {"id": "kpmg-cn", "link_pattern": r"/insights/20\d\d/\d\d/[^/]+\.html$",
           "exclude_pattern": r"\.print\.html", "topics": ["big4"], "kind": "news"}
    items = news.parse_gov_list(LIST_HTML, src, "https://kpmg.com/cn/zh/home/insights.html")
    assert [i["title"][:4] for i in items] == ["2027", "中国可持"]
    assert all(i["kind"] == "news" and i["topics"] == ["big4"] and i["region"] == "cn" for i in items)
    assert items[0]["date"].startswith("2026-10-")  # 日期从相邻文字解析
    # 政府网站默认仍是政策
    gov = news.parse_gov_list(LIST_HTML, {**src, "kind": None} | {"kind": "policy"}, "https://x/")
    assert gov[0]["kind"] == "policy"


def test_same_site_routes_skipped_after_timeout(monkeypatch):
    """澎湃屏蔽海外服务器时，第一个栏目超时后，其余栏目直接跳过，不再各等一分钟。"""
    import requests
    monkeypatch.setenv("RSSHUB_BASE", "http://localhost:1200")
    monkeypatch.setenv("RSSHUB_FALLBACKS", "")

    class Slow(FakeSession):
        def get(self, url, timeout=None):
            self.calls.append(url)
            if "/thepaper/" in url:
                raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)")
            return super().get(url, timeout)

    sess = Slow({"http://localhost:1200/gov": FEED})
    monkeypatch.setattr(news, "make_session", lambda *a, **k: sess)
    st = SourceStatus()
    srcs = [{"id": "pp1", "name": "澎湃1", "route": "/thepaper/list/1"},
            {"id": "pp2", "name": "澎湃2", "route": "/thepaper/list/2"},
            {"id": "gov", "name": "国务院", "route": "/gov/zhengce/x"}]
    items = news.fetch_rss(srcs, 200, st, max_age_days=100000)
    assert [u for u in sess.calls if "thepaper" in u] == ["http://localhost:1200/thepaper/list/1"]
    assert st.status["pp1"]["error"] == "RSSHub 失败：localhost:1200 超时"
    assert st.status["pp2"]["error"].startswith("跳过")
    assert st.status["gov"]["ok"] and items          # 其他网站不受影响


def test_disabled_sources_dropped_from_status(monkeypatch, tmp_path):
    """关闭的来源（如澎湃的旧栏目）不再以“失败”留在页面底部；财报状态保留。"""
    import json
    from pipelines.desk import run as runner
    monkeypatch.setattr(runner, "DATA", tmp_path)
    (tmp_path / "meta.json").write_text(json.dumps({"sources_status": {
        "thepaper-finance": {"ok": False, "name": "澎湃 · 财经", "error": "超时"},
        "fin-a": {"ok": True, "name": "A 股财报", "count": 26}}}))
    assert runner.main(["--only", "kb"]) == 0
    st = json.loads((tmp_path / "meta.json").read_text())["sources_status"]
    assert "thepaper-finance" not in st and st["fin-a"]["ok"]
