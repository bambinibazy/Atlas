"""统一调度与首页摘要。"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from pipelines import home, update

NOW = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def test_first_run_does_everything():
    assert update.due_parts({}, NOW) == ["markets", "news", "financials", "ai"]


def test_intervals():
    runs = {p: {"last_ok": iso(NOW - timedelta(minutes=30)), "last_try": iso(NOW - timedelta(minutes=30))}
            for p in update.ORDER}
    assert update.due_parts(runs, NOW) == ["markets"]  # 行情每次都跑
    runs["news"]["last_ok"] = runs["news"]["last_try"] = iso(NOW - timedelta(hours=6))
    runs["ai"]["last_ok"] = runs["ai"]["last_try"] = iso(NOW - timedelta(hours=23))
    assert update.due_parts(runs, NOW) == ["markets", "news", "ai"]
    runs["financials"]["last_ok"] = runs["financials"]["last_try"] = iso(NOW - timedelta(days=7))
    assert "financials" in update.due_parts(runs, NOW)


def test_failed_part_waits_before_retry():
    runs = {"ai": {"last_ok": iso(NOW - timedelta(days=2)), "last_try": iso(NOW - timedelta(hours=1))}}
    assert "ai" not in update.due_parts(runs, NOW)          # 1 小时前刚失败
    runs["ai"]["last_try"] = iso(NOW - timedelta(hours=4))
    assert "ai" in update.due_parts(runs, NOW)              # 过了重试间隔


def test_forced_parts():
    ap = type("A", (), {"parts": "ai, news"})
    assert update.plan(ap, {}, NOW) == ["news", "ai"]
    ap.parts = "all"
    assert update.plan(ap, {}, NOW) == update.ORDER
    ap.parts = "none"
    assert update.plan(ap, {}, NOW) == []
    ap.parts = "nope"
    with pytest.raises(SystemExit):
        update.plan(ap, {}, NOW)


def test_isolated_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "RUNS", tmp_path / "runs.json")
    monkeypatch.setattr(update, "ROOT", tmp_path)  # 不读写仓库里真实的 site/ 数据
    monkeypatch.setattr(home, "SITE", tmp_path)
    monkeypatch.setattr(home, "build", lambda: {"markets": {"quotes": [], "flash": []}, "ai": {"picks": []}})
    calls = []

    def fake(part, offline=False):
        calls.append(part)
        if part == "ai":
            raise RuntimeError("arXiv down")
        return 0
    monkeypatch.setattr(update, "_run_part", fake)
    assert update.main(["--parts", "markets,ai"]) == 0      # 部分失败仍正常结束
    runs = json.loads((tmp_path / "runs.json").read_text())
    assert runs["markets"]["last_ok"] and "error" not in runs["markets"]
    assert "last_ok" not in runs["ai"] and runs["ai"]["error"]
    monkeypatch.setattr(update, "_run_part", lambda p, offline=False: 1)
    assert update.main(["--parts", "markets"]) == 1         # 全部失败才返回 1


def _write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False))


def test_home_summary(tmp_path):
    md = tmp_path / "markets" / "data"
    _write(md / "meta.json", {"updated": iso(NOW), "count_24h": 3,
                              "source_names": {"cls": {"zh": "财联社", "en": "CLS"}}})
    _write(md / "quotes.json", {"groups": [{"id": "cn", "rows": [
        {"id": "sh", "name": {"zh": "上证指数"}, "last": 3300.5, "chg": 12.3, "pct": 0.37, "decimals": 2},
        {"id": "hsi", "name": {"zh": "恒生指数"}, "last": 20000, "chg": -50, "pct": -0.25, "stale": True}]}]})
    _write(md / "items.json", {"items": [
        {"type": "flash", "title": "普通快讯", "date": iso(NOW - timedelta(minutes=5)), "sources": ["cls"]},
        {"type": "flash", "title": "重要快讯", "date": iso(NOW - timedelta(hours=3)), "important": True, "sources": ["cls"]},
        {"type": "filing", "title": "公告不进首页", "date": iso(NOW), "sources": ["em"]},
        {"type": "flash", "title": "两天前的快讯", "date": iso(NOW - timedelta(days=2)), "sources": ["cls"]}]})
    ad = tmp_path / "ai" / "data"
    _write(ad / "meta.json", {"updated": iso(NOW), "topics": [{"id": "models", "name": {"zh": "AI 模型"}, "count_7d": 9}]})
    _write(ad / "items.json", {"items": [
        {"title": "冷门论文", "date": iso(NOW - timedelta(days=1)), "sources": ["arxiv"], "topics": ["models"], "metrics": {}},
        {"title": "热门仓库", "date": iso(NOW - timedelta(days=2)), "sources": ["github"], "topics": ["models"],
         "metrics": {"stars": 5000}, "type": "repo"},
        {"title": "很久以前", "date": iso(NOW - timedelta(days=30)), "sources": ["arxiv"], "topics": [], "metrics": {"stars": 99999}}]})

    m = home.markets_summary(tmp_path, NOW, ["hsi", "sh", "missing"])
    assert [q["name"] for q in m["quotes"]] == ["恒生指数", "上证指数"] and m["quotes"][0]["stale"]
    assert [f["title"] for f in m["flash"]][:2] == ["重要快讯", "普通快讯"]   # 重要的排前面
    assert "公告不进首页" not in [f["title"] for f in m["flash"]]
    assert m["flash"][0]["source"] == "财联社"
    a = home.ai_summary(tmp_path, NOW)
    assert [p["title"] for p in a["picks"]] == ["热门仓库", "冷门论文"]    # 只看近 7 天，按热度
    assert a["picks"][0]["topics"] == ["AI 模型"] and a["topics"][0]["count_7d"] == 9


def test_home_without_data(tmp_path):
    d = home.build(tmp_path, NOW)
    assert d["markets"]["quotes"] == [] and d["ai"]["picks"] == []
    assert (tmp_path / "data" / "home.json").exists()


def test_runs_file_follows_patched_path(monkeypatch, tmp_path):
    """工作流里测试前会从 public 分支取回真实的 runs.json，测试必须读写临时文件，不受它影响。"""
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"ai": {"last_ok": iso(NOW)}}))
    fake = tmp_path / "fake.json"
    monkeypatch.setattr(update, "RUNS", fake)
    assert update.load_runs() == {}
    monkeypatch.setattr(update, "RUNS", real)
    assert update.load_runs()["ai"]["last_ok"] == iso(NOW)
