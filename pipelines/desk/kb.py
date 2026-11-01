"""把 content/kb/*.md 知识库文章编译成 site/data/kb.json。

每篇文章开头是 YAML 头信息：
---
id: npv
title: 净现值（NPV）
en: Net Present Value
category: investment
summary: 一句话说明
tools: [project]        # 相关工具 id（可选）
related: [irr, wacc]    # 相关文章 id（可选）
sources:                # 延伸阅读（可选）
  - { title: "...", url: "https://..." }
---
正文使用 Markdown。
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown
import yaml

CATEGORIES = [
    ("strategy", "战略分析"),
    ("org", "组织与绩效"),
    ("decision", "决策方法"),
    ("analysis", "财务分析"),
    ("investment", "投资与融资"),
    ("budget", "预算与成本"),
    ("governance", "风险与治理"),
    ("standards", "会计准则"),
]
# 前端已实现的工具 id（site/assets/tools.js）
TOOL_IDS = {"project", "breakeven", "dupont", "workingcap", "wacc", "loan", "matrix", "ev", "cashflow", "pricing", "iit"}
_link = re.compile(r'href="#/(kb|tools)/([\w-]+)"')
# 每个分类内的阅读顺序（未列出的排在最后，按文件名）
ORDER = ["swot", "pestel", "five-forces", "value-chain", "bcg-matrix", "ansoff", "business-model-canvas",
         "okr", "kpi-design", "balanced-scorecard",
         "decision-matrix", "expected-value", "scenario-sensitivity", "opportunity-sunk-cost", "pre-mortem",
         "three-statements", "ratio-system", "dupont", "working-capital", "earnings-quality", "free-cash-flow",
         "npv", "irr", "wacc", "capital-structure", "financing-options",
         "comprehensive-budget", "cashflow-forecast", "cvp", "pricing-strategy", "zero-based-budget",
         "activity-based-costing", "standard-cost-variance",
         "internal-control", "enterprise-risk", "corporate-governance-cn",
         "cas-system", "revenue-recognition", "lease-accounting", "cas-ifrs-differences"]
_front = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_tag = re.compile(r"<[^>]+>")


def parse_article(text: str, path: str = "") -> dict:
    m = _front.match(text)
    if not m:
        raise ValueError(f"{path} 缺少 YAML 头信息")
    meta = yaml.safe_load(m.group(1)) or {}
    for k in ("id", "title", "category", "summary"):
        if not meta.get(k):
            raise ValueError(f"{path} 缺少字段 {k}")
    body = text[m.end():]
    md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2"}})
    html = md.convert(body)
    plain = re.sub(r"\s+", " ", _tag.sub(" ", html)).strip()
    return {
        "id": meta["id"], "title": meta["title"], "en": meta.get("en", ""), "category": meta["category"],
        "summary": meta["summary"], "tools": meta.get("tools") or [], "related": meta.get("related") or [],
        "sources": meta.get("sources") or [], "html": html,
        "toc": [{"id": t["id"], "name": t["name"]} for t in md.toc_tokens],
        "text": plain[:4000], "chars": len(plain),
    }


def build(content_dir: Path) -> dict:
    arts = []
    for p in sorted(content_dir.glob("*.md")):
        arts.append(parse_article(p.read_text(encoding="utf-8"), p.name))
    ids = {a["id"] for a in arts}
    cats = {c for c, _ in CATEGORIES}
    problems = []
    for a in arts:
        if a["category"] not in cats:
            problems.append(f"{a['id']}: 未知分类 {a['category']}")
        for r in a["related"]:
            if r not in ids:
                problems.append(f"{a['id']}: 相关文章 {r} 不存在")
        for t in a["tools"]:
            if t not in TOOL_IDS:
                problems.append(f"{a['id']}: 工具 {t} 不存在")
        for kind, target in _link.findall(a["html"]):
            if (kind == "kb" and target not in ids) or (kind == "tools" and target not in TOOL_IDS):
                problems.append(f"{a['id']}: 正文链接 #/{kind}/{target} 无效")
    if len(ids) != len(arts):
        problems.append("存在重复的文章 id")
    if problems:
        raise ValueError("知识库检查失败：\n" + "\n".join(problems))
    order = {c: i for i, (c, _) in enumerate(CATEGORIES)}
    pos = {k: i for i, k in enumerate(ORDER)}
    arts.sort(key=lambda a: (order.get(a["category"], 99), pos.get(a["id"], 999), a["id"]))
    return {"categories": [{"id": c, "name": n} for c, n in CATEGORIES], "articles": arts}
