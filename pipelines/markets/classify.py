"""按关键词给条目补充市场标签、判断是否属于“宏观政策”，以及跨来源的相似快讯合并。"""
from __future__ import annotations

import re
from typing import Iterable

from .common import parse_date

_cjk = re.compile(r"[㐀-鿿]")


class KeywordMatcher:
    """关键词匹配。英文按整词匹配（"oil" 不会命中 "boil"）；中文直接子串匹配；
    以 "=" 开头的关键词区分大小写。"""

    def __init__(self, keywords: Iterable[str]):
        self.patterns: list[tuple[str, re.Pattern]] = []
        for kw in keywords:
            kw = str(kw)
            sensitive = kw.startswith("=")
            word = kw[1:] if sensitive else kw
            body = re.escape(word).replace(r"\ ", r"\s+")
            if not _cjk.search(word):
                body = r"(?<![A-Za-z0-9])" + body + r"(?:s|es)?(?![A-Za-z0-9])"
            self.patterns.append((word, re.compile(body, 0 if sensitive else re.IGNORECASE)))

    def matches(self, text: str) -> set[str]:
        if not text:
            return set()
        return {kw for kw, p in self.patterns if p.search(text)}

    def any(self, text: str) -> bool:
        return bool(text) and any(p.search(text) for _, p in self.patterns)


class Classifier:
    def __init__(self, cfg: dict):
        self.markets = [(m["id"], KeywordMatcher(m.get("keywords", []))) for m in cfg.get("markets", [])]
        self.policy = KeywordMatcher(cfg.get("policy_keywords", []))

    def apply(self, item: dict) -> dict:
        text_title = item.get("title", "")
        text = f"{text_title} {item.get('summary', '')} {' '.join(item.get('tags', []))}"
        markets = list(item.get("markets") or [])
        for mid, m in self.markets:
            # 标题命中或正文命中 2 个以上关键词才打标签，减少误判
            if mid in markets:
                continue
            if m.any(text_title) or len(m.matches(text)) >= 2:
                markets.append(mid)
        item["markets"] = markets
        item["macro"] = item["type"] == "policy" or (item["type"] in ("flash", "news") and self.policy.any(text))
        return item


# ---------------- 相似快讯合并 ----------------
_norm = re.compile(r"[\W_]+", re.UNICODE)
# 去掉“财联社10月24日电，”“新浪财经10月24日讯，”这类各家不同的电头
_dateline = re.compile(r"^[\u4e00-\u9fa5A-Za-z·]{0,12}\d{1,2}月\d{1,2}日(?:电|讯|消息)[，,：:\s]*")


def shingles(text: str, n: int = 3) -> set[str]:
    t = _norm.sub("", text.lower())
    if len(t) <= n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def merge_similar(items: list[dict], window_hours: float = 3, threshold: float = 0.55) -> list[dict]:
    """多家快讯报道同一事件时合并为一条：保留最早的一条，来源合并，任一来源标重要则为重要。
    只比较时间相近（window_hours 内）的中文快讯，避免 O(n²) 全量比较。"""
    flashes = sorted((i for i in items if i["type"] == "flash"), key=lambda i: i.get("date") or "")
    others = [i for i in items if i["type"] != "flash"]
    kept: list[dict] = []
    sigs: list[set[str]] = []
    tsigs: list[set[str]] = []
    times: list[float] = []
    window = window_hours * 3600
    for it in flashes:
        body = _dateline.sub("", it.get("summary", ""))[:60]
        sig = shingles(it["title"] + body)
        tsig = shingles(it["title"])
        t = (parse_date(it.get("date")) or parse_date("1970-01-01")).timestamp()
        dup = None
        for j in range(len(kept) - 1, -1, -1):
            if t - times[j] > window:
                break
            if jaccard(sig, sigs[j]) >= threshold or (len(tsig) >= 6 and jaccard(tsig, tsigs[j]) >= 0.8):
                dup = j
                break
        if dup is None:
            kept.append(it)
            sigs.append(sig)
            tsigs.append(tsig)
            times.append(t)
        else:
            k = kept[dup]
            k["sources"] = sorted(set(k["sources"]) | set(it["sources"]))
            k["important"] = k["important"] or it["important"]
            if len(it.get("summary", "")) > len(k.get("summary", "")):
                k["summary"] = it["summary"]
            alts = k.setdefault("alt_urls", {})
            for s in it["sources"]:
                alts.setdefault(s, it["url"])
    return kept + others
