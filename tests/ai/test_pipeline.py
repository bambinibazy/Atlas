"""离线测试：用接口格式样本验证解析、去重合并与分类。运行：python -m pytest -q"""
import json
from pathlib import Path

from pipelines.ai.classify import Classifier, KeywordMatcher
from pipelines.ai.run import build, dedupe, load_config
from pipelines.ai.sources import arxiv, biorxiv, github, huggingface

FX = Path(__file__).parent / "fixtures"
CFG = load_config()
CLF = Classifier(CFG["topics"])


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_arxiv_parse():
    items = arxiv.parse_feed((FX / "arxiv.xml").read_text(), 900, "models")
    assert [i["id"] for i in items] == ["arxiv:2610.00001", "arxiv:2610.00002", "arxiv:2610.00003"]
    a = items[0]
    assert a["title"].startswith("Test Fixture: Sparse Mixture") and "\n" not in a["title"]
    assert a["links"]["code"] == "https://github.com/example-lab/sparse-moe"
    assert a["links"]["pdf"].startswith("https://")
    assert a["categories"][0] == "cs.CL"  # 主分类排第一
    assert items[1]["links"]["code"] == "https://github.com/example/volformer"  # 去掉 .git


def test_github_parse_skips_forks():
    items = github.parse_search(_load("github.json"), 900, "medicine")
    assert [i["id"] for i in items] == ["github:example-lab/med-agent", "github:example/lean-prover"]
    assert items[0]["metrics"]["stars"] == 812
    assert "Python" in items[0]["tags"]


def test_hf_parse():
    papers = huggingface.parse_daily_papers(_load("hf_daily.json"), 900)
    assert papers[0]["id"] == "arxiv:2610.00001"
    assert papers[0]["metrics"]["upvotes"] == 57
    assert papers[0]["tldr"]
    models = huggingface.parse_repos(_load("hf_models.json"), "model")
    assert models[0]["links"]["paper"] == "https://arxiv.org/abs/2610.00001"
    assert not any(t.startswith("region:") for t in models[0]["tags"])
    assert huggingface._token_match("google/medgemma-4b", "med")
    assert not huggingface._token_match("x/llama-finetuned", "fin")


def test_biorxiv_filters_non_ai():
    ai = KeywordMatcher(CFG["ai_keywords"])
    items = biorxiv.parse_collection(_load("biorxiv.json"), "biorxiv", ai, 900)
    assert len(items) == 1 and items[0]["_hints"] == ["brain"]
    assert items[0]["url"].endswith("v1")


def test_keyword_matcher():
    m = KeywordMatcher(["fine-tuning", "=LLM", "agent"])
    assert m.matches("Efficient fine tuning of LLMs") == {"fine-tuning", "llm"}
    assert m.matches("an llm") == set()            # 区分大小写
    assert m.matches("multi-agents system") == {"agent"}
    assert m.matches("reagent chemistry") == set()  # 不匹配单词内部


def test_classification():
    items = arxiv.parse_feed((FX / "arxiv.xml").read_text(), 900)
    topics = {i["id"]: CLF.classify(i) for i in items}
    assert topics["arxiv:2610.00001"] == ["models"]
    assert topics["arxiv:2610.00002"][0] == "finance" and "models" not in topics["arxiv:2610.00002"]
    assert topics["arxiv:2610.00003"][0] == "brain"
    gh = github.parse_search(_load("github.json"), 900)
    assert CLF.classify(gh[0])[0] == "medicine"   # 交叉学科优先
    assert CLF.classify(gh[1]) == ["math"]


def test_merge_across_sources_and_build():
    ax = arxiv.parse_feed((FX / "arxiv.xml").read_text(), 900, "models")
    hf = huggingface.parse_daily_papers(_load("hf_daily.json"), 900)
    merged = dedupe(ax + hf)
    p = merged["arxiv:2610.00001"]
    assert p["sources"] == ["arxiv", "huggingface"]
    assert p["metrics"]["upvotes"] == 57 and p["links"]["code"]
    # 样本日期改成“现在”，测试不随时间失效；超过保留期的旧条目应被剔除
    from pipelines.ai.common import iso, utcnow
    for it in ax + hf:
        it["date"] = iso(utcnow())
    old = {"arxiv:old": {**ax[0], "id": "arxiv:old", "date": "2020-01-01T00:00:00Z",
                         "first_seen": "2020-01-01T00:00:00Z"}}
    items, meta = build(CFG, ax + hf, old)
    ids = {i["id"] for i in items}
    assert "arxiv:old" not in ids and "arxiv:2610.00009" in ids
    phys = next(i for i in items if i["id"] == "arxiv:2610.00009")
    assert "physics" in phys["topics"]
    assert meta["total"] == len(items) and len(meta["topics"]) == 7
