"""用假的 HTTP 响应跑通每个来源的 fetch()，覆盖请求拼装、分页和容错路径。"""
import json
from pathlib import Path

import pytest

from pipelines.ai import common
from pipelines.ai.run import build, collect, load_config
from pipelines.ai.sources import arxiv, biorxiv, github, huggingface

FX = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if "arxiv.org" in url:
            if "q-fin" in params["search_query"]:
                return FakeResp("boom", 503)  # 模拟一条查询失败
            return FakeResp((FX / "arxiv.xml").read_text())
        if "api.github.com" in url:
            return FakeResp(json.loads((FX / "github.json").read_text()))
        if "daily_papers" in url:
            return FakeResp(json.loads((FX / "hf_daily.json").read_text()))
        if "huggingface.co/api/models" in url or "huggingface.co/api/datasets" in url:
            return FakeResp(json.loads((FX / "hf_models.json").read_text()))
        if "api.biorxiv.org" in url:
            return FakeResp(json.loads((FX / "biorxiv.json").read_text()))
        raise AssertionError(url)


@pytest.fixture
def fake(monkeypatch):
    s = FakeSession()
    for mod in (arxiv, github, huggingface, biorxiv):
        monkeypatch.setattr(mod, "make_session", lambda *a, **k: s)
    monkeypatch.setattr(common.RateLimiter, "wait", lambda self: None)
    # 样本日期固定在 2026-10，把“现在”钉在附近，保证近期过滤逻辑可测
    fixed = common.parse_date("2026-10-22T00:00:00Z")
    monkeypatch.setattr(common, "utcnow", lambda: fixed)
    for mod in (arxiv, biorxiv, huggingface):
        if hasattr(mod, "utcnow"):
            monkeypatch.setattr(mod, "utcnow", lambda: fixed)
    monkeypatch.setattr(arxiv, "days_ago", lambda n: fixed - common.timedelta(days=n))
    monkeypatch.setattr(github, "days_ago", lambda n: fixed - common.timedelta(days=n))
    monkeypatch.setattr(biorxiv, "days_ago", lambda n: fixed - common.timedelta(days=n))
    return s


def test_collect_all_sources(fake):
    cfg = load_config()
    items = collect(cfg, {"arxiv", "github", "huggingface", "biorxiv"})
    srcs = {s for it in items for s in it["sources"]}
    assert srcs == {"arxiv", "github", "huggingface", "biorxiv", "medrxiv"}
    # medRxiv 也被请求了；GitHub 查询带上了时间和星标条件
    assert any("/medrxiv/" in u for u, _ in fake.calls)
    gh_q = [p["q"] for u, p in fake.calls if "github" in u]
    assert all("created:>" in q and "stars:>=" in q for q in gh_q)
    # bioRxiv 分区里的空格转成了下划线
    assert any("category=systems_biology" in u for u, _ in fake.calls)
    out, meta = build(cfg, items, {})
    assert meta["total"] == len(out) > 0
    assert all(it["topics"] for it in out)
