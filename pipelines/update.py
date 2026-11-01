"""统一调度：工作流每 30 分钟调用一次，按各部分的更新间隔决定这次运行哪些。

    python -m pipelines.update                      # 运行到期的部分
    python -m pipelines.update --plan               # 只打印本次会运行哪些部分（工作流据此决定是否启动 RSSHub）
    python -m pipelines.update --parts ai,news      # 强制运行指定部分；all 表示全部
    python -m pipelines.update --event push         # 推送代码后：额外编译知识库，并按新配置离线重新分类

各部分与默认间隔（可在 INTERVALS 里改）：
    markets     行情、快讯、公告、宏观          每次（约 30 分钟）
    news        管理资讯与政策 + 知识库         6 小时
    ai          AI 论文、代码、模型             每天
    financials  上市公司财报                    每周

上次运行时间记录在 site/data/runs.json，随网站一起发布，下次运行前从 public 分支取回。
某个部分失败不影响其他部分；失败的部分在 RETRY_AFTER 之后重试，不会每次都重跑。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "site" / "data" / "runs.json"
log = logging.getLogger("update")

ORDER = ["markets", "news", "financials", "ai"]
# 间隔比名义值略短，避免 GitHub 定时任务推迟几分钟就错过一轮
INTERVALS = {
    "markets": timedelta(0),
    "news": timedelta(hours=5, minutes=40),
    "ai": timedelta(hours=22),
    "financials": timedelta(days=6, hours=18),
}
RETRY_AFTER = {"markets": timedelta(0), "news": timedelta(hours=1), "ai": timedelta(hours=3),
               "financials": timedelta(hours=12)}
NAMES = {"markets": "行情快讯", "news": "资讯与知识库", "ai": "AI 前沿", "financials": "上市公司财报"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_runs(path: Path | None = None) -> dict:
    path = path or RUNS  # 调用时才读取 RUNS，测试里替换 RUNS 才会生效
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def due_parts(runs: dict, now: datetime) -> list[str]:
    out = []
    for part in ORDER:
        r = runs.get(part) or {}
        ok, tried = _parse(r.get("last_ok")), _parse(r.get("last_try"))
        if ok and now - ok < INTERVALS[part]:
            continue
        if tried and (not ok or tried > ok) and now - tried < RETRY_AFTER[part]:
            continue  # 上次失败了，等一会儿再试
        out.append(part)
    return out


def _run_part(part: str, offline: bool = False) -> int:
    if part == "markets":
        from .markets import run as m
        return m.main(["--offline"] if offline else [])
    if part == "ai":
        from .ai import run as a
        return a.main(["--reclassify"] if offline else [])
    if part == "news":
        from .desk import run as d
        return d.main(["--only", "news,kb"])
    if part == "financials":
        from .desk import run as d
        return d.main(["--only", "financials"])
    if part == "kb":
        from .desk import run as d
        return d.main(["--only", "kb"])
    raise ValueError(part)


def plan(args, runs: dict, now: datetime) -> list[str]:
    if args.parts:
        if args.parts.strip() == "none":  # 工作流里“没有到期的部分”时传 none，只重建首页摘要
            return []
        wanted = ORDER if args.parts.strip() == "all" else [p.strip() for p in args.parts.split(",") if p.strip()]
        unknown = set(wanted) - set(ORDER)
        if unknown:
            raise SystemExit(f"未知的部分：{','.join(sorted(unknown))}；可选：{','.join(ORDER)} 或 all")
        return [p for p in ORDER if p in wanted]
    return due_parts(runs, now)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按更新间隔运行各栏目的数据抓取")
    ap.add_argument("--parts", help="强制运行这些部分（逗号分隔）：" + ",".join(ORDER) + "；all 为全部，none 为都不运行")
    ap.add_argument("--event", default="", help="触发事件；push 表示推送了代码或配置")
    ap.add_argument("--plan", action="store_true", help="只打印本次会运行的部分")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    now = utcnow()
    runs = load_runs()
    parts = plan(args, runs, now)
    if args.plan:
        print(",".join(parts))
        return 0

    results = {}
    for part in parts:
        log.info("==== %s ====", NAMES[part])
        t0 = time.monotonic()
        try:
            code = _run_part(part)
        except Exception as exc:  # noqa: BLE001  某个部分出错不影响其他部分
            log.exception("%s 失败：%s", NAMES[part], exc)
            code = 1
        stamp = _iso(utcnow())
        r = runs.setdefault(part, {})
        r["last_try"] = stamp
        if code == 0:
            r["last_ok"] = stamp
            r.pop("error", None)
        else:
            r["error"] = f"退出码 {code}，详见 Actions 日志"
        r["seconds"] = round(time.monotonic() - t0, 1)
        results[part] = code

    if args.event == "push":
        # 推送了代码或配置：知识库重新编译；行情和 AI 按新关键词离线重新分类（不联网）
        if "news" not in parts:
            _safe("kb", lambda: _run_part("kb"))
        if "markets" not in parts and (ROOT / "site/markets/data/items.json").exists():
            _safe("markets --offline", lambda: _run_part("markets", offline=True))
        if "ai" not in parts and (ROOT / "site/ai/data/items.json").exists():
            _safe("ai --reclassify", lambda: _run_part("ai", offline=True))

    from . import home
    d = home.build()
    log.info("首页摘要：行情 %d 项，快讯 %d 条，AI %d 条", len(d["markets"]["quotes"]),
             len(d["markets"]["flash"]), len(d["ai"]["picks"]))

    runs["updated"] = _iso(utcnow())
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    RUNS.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")

    ran = ", ".join(f"{NAMES[p]}{'✓' if c == 0 else '✗'}" for p, c in results.items()) or "没有到期的部分"
    log.info("本次运行：%s", ran)
    # 全部失败才返回非零，让工作流标红；部分失败照常发布，失败的部分沿用上次数据
    return 1 if results and all(c != 0 for c in results.values()) else 0


def _safe(name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        log.warning("%s 失败：%s", name, exc)


if __name__ == "__main__":
    sys.exit(main())
