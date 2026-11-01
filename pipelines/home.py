"""首页摘要：从行情、AI 两个栏目已生成的数据里挑出首页要显示的少量内容，写入 site/data/home.json。

首页不直接加载各栏目的完整数据（快讯可能有几千条），只读这个小文件。
任何一个栏目还没有数据时，对应部分为空，首页会显示提示。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _zh(v) -> str:
    return v.get("zh") or next(iter(v.values()), "") if isinstance(v, dict) else (v or "")


def _short(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def markets_summary(site: Path, now: datetime, quote_ids: list[str], n_flash: int = 8) -> dict:
    d = site / "markets" / "data"
    meta = _read(d / "meta.json", {})
    quotes = _read(d / "quotes.json", {})
    items = _read(d / "items.json", {}).get("items", [])
    rows = {r["id"]: r for g in quotes.get("groups", []) for r in g.get("rows", [])}
    picked = []
    for qid in quote_ids:
        r = rows.get(qid)
        if r:
            picked.append({"id": qid, "name": _zh(r.get("name")), "last": r.get("last"), "chg": r.get("chg"),
                           "pct": r.get("pct"), "decimals": r.get("decimals", 2), "unit": r.get("unit", ""),
                           "change_unit": r.get("change_unit", "pct"), "stale": bool(r.get("stale"))})
    names = meta.get("source_names", {})
    day_ago = now.timestamp() - 86400
    flash = [i for i in items if i.get("type") in ("flash", "news") and i.get("title")]
    recent = [i for i in flash if (_parse(i.get("date")) or now).timestamp() >= day_ago]
    # 24 小时内的重要快讯优先，其余按时间
    ranked = sorted(recent, key=lambda i: (0 if i.get("important") else 1, -(_parse(i.get("date")) or now).timestamp()))
    if len(ranked) < n_flash:
        ranked += [i for i in flash if i not in ranked][: n_flash - len(ranked)]
    out = []
    for i in ranked[:n_flash]:
        src = (i.get("sources") or [""])[0]
        out.append({"title": _short(i["title"], 90), "url": i.get("url", ""), "date": i.get("date"),
                    "important": bool(i.get("important")), "source": _zh(names.get(src, src))})
    return {"updated": meta.get("updated"), "count_24h": meta.get("count_24h", 0), "quotes": picked, "flash": out}


def popularity(it: dict, now: datetime) -> float:
    """与 site/ai/assets/app.js 里的“最热”排序一致。"""
    m = it.get("metrics") or {}
    ln = lambda x: math.log1p(x or 0)  # noqa: E731
    pop = ln(m.get("stars")) + 1.6 * ln(m.get("upvotes")) + ln(m.get("likes")) + 0.15 * ln(m.get("downloads")) \
        + (len(it.get("sources") or []) - 1)
    d = _parse(it.get("date")) or now
    age = max(0.0, (now - d).total_seconds() / 86400)
    return pop / math.pow(1 + age / 10, 0.6)


def ai_summary(site: Path, now: datetime, n: int = 6) -> dict:
    d = site / "ai" / "data"
    meta = _read(d / "meta.json", {})
    items = _read(d / "items.json", {}).get("items", [])
    week = now.timestamp() - 7 * 86400
    pool = [i for i in items if (_parse(i.get("date")) or now).timestamp() >= week] or items
    pool = sorted(pool, key=lambda i: popularity(i, now), reverse=True)[:n]
    topics = {t["id"]: _zh(t.get("name")) for t in meta.get("topics", [])}
    return {
        "updated": meta.get("updated"),
        "topics": [{"id": t["id"], "name": _zh(t.get("name")), "count_7d": t.get("count_7d", 0)}
                   for t in meta.get("topics", [])],
        "picks": [{"title": _short(i["title"], 110), "url": i.get("url", ""), "date": i.get("date"),
                   "type": i.get("type"), "topics": [topics.get(t, t) for t in i.get("topics", [])][:2],
                   "summary": _short(i.get("tldr") or i.get("summary") or "", 120)} for i in pool],
    }


def build(site: Path = SITE, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        cfg = yaml.safe_load((ROOT / "config" / "markets" / "sources.yaml").read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        cfg = {}
    data = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "markets": markets_summary(site, now, cfg.get("home_quotes", [])),
        "ai": ai_summary(site, now),
    }
    out = site / "data" / "home.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data


if __name__ == "__main__":
    d = build()
    print(f"首页摘要：行情 {len(d['markets']['quotes'])} 项，快讯 {len(d['markets']['flash'])} 条，AI {len(d['ai']['picks'])} 条")
