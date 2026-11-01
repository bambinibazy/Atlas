"""按关键词 / arXiv 分类 / 来源提示，给每个条目打上一个或多个主题标签。

打分规则（可在 SCORE 中调整）：
  标题或标签命中一个关键词   +3
  仅摘要命中一个关键词       +1（同一关键词只计一次）
  arXiv 分类属于该主题       交叉学科 +2，通用主题 +1
  由该主题的检索式抓到       +3
达到阈值即归入该主题。交叉学科主题（脑科学/医学/数学/物理/金融）优先：
一旦命中交叉学科，通用主题（AI 模型/AI 应用）需要更高的分数才会同时标注，
避免所有论文都挤进“AI 模型”。
"""
from __future__ import annotations

import re
from typing import Iterable

SCORE = {
    "title": 3,
    "abstract": 1,
    "category_domain": 2,
    "category_general": 1,
    "hint": 3,
    "threshold_domain": 3,
    "threshold_general": 4,
    "threshold_general_if_domain": 6,
}


class KeywordMatcher:
    """关键词匹配器。以 "=" 开头的关键词区分大小写（如 =LLM、=CT）。"""

    def __init__(self, keywords: Iterable[str]):
        self.patterns: list[tuple[str, re.Pattern]] = []
        for kw in keywords:
            kw = str(kw)
            sensitive = kw.startswith("=")
            word = kw[1:] if sensitive else kw
            # 空格和连字符互相通配：“fine-tuning” 也能匹配 “fine tuning”
            body = r"[\s\-]?".join(re.escape(part) for part in re.split(r"[\s\-]+", word))
            pat = re.compile(r"(?<![A-Za-z0-9])" + body + r"(?:s|es)?(?![A-Za-z0-9])",
                             0 if sensitive else re.IGNORECASE)
            self.patterns.append((word.lower(), pat))

    def matches(self, text: str) -> set[str]:
        if not text:
            return set()
        return {kw for kw, pat in self.patterns if pat.search(text)}

    def any_match(self, text: str) -> bool:
        return bool(text) and any(pat.search(text) for _, pat in self.patterns)


class Classifier:
    def __init__(self, topics: list[dict]):
        self.topics = topics
        self.matchers = {t["id"]: KeywordMatcher(t.get("keywords", [])) for t in topics}
        self.cats = {t["id"]: set(t.get("arxiv_categories", [])) for t in topics}
        self.kind = {t["id"]: t.get("kind", "domain") for t in topics}
        self.fallback = next((t["id"] for t in topics if t["id"] == "models"),
                             topics[0]["id"] if topics else None)

    def scores(self, item: dict) -> dict[str, int]:
        title_text = " ".join([item.get("title", "").replace("/", " ").replace("_", " "),
                               " ".join(item.get("tags", []))])
        body = " ".join([item.get("summary", ""), item.get("tldr", "")])
        if item.get("type") in ("repo", "model", "dataset"):
            # 仓库/模型的简介只有一两句，和标题同等重要
            title_text, body = f"{title_text} {body}", ""
        cats = set(item.get("categories", []))
        hints = set(item.get("_hints", []))
        out = {}
        for tid, m in self.matchers.items():
            t_hits = m.matches(title_text)
            b_hits = m.matches(body) - t_hits
            s = SCORE["title"] * len(t_hits) + SCORE["abstract"] * len(b_hits)
            if cats & self.cats[tid]:
                s += SCORE["category_domain"] if self.kind[tid] == "domain" else SCORE["category_general"]
            if tid in hints:
                s += SCORE["hint"]
            out[tid] = s
        return out

    def classify(self, item: dict) -> list[str]:
        sc = self.scores(item)
        domain = [t for t, s in sc.items()
                  if self.kind[t] == "domain" and s >= SCORE["threshold_domain"]]
        g_thr = SCORE["threshold_general_if_domain"] if domain else SCORE["threshold_general"]
        general = [t for t, s in sc.items() if self.kind[t] == "general" and s >= g_thr]
        chosen = sorted(domain + general, key=lambda t: -sc[t])
        if not chosen and self.fallback:
            chosen = [self.fallback]
        return chosen
