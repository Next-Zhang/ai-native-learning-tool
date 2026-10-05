r"""指标导出 CLI（PRD §3.3.4 必过项④：`python -m coach.metrics.export --format csv`）。

用法（在 App_landing 目录下）：

    # 只看汇总（token / 成本 / p50-p95 延迟 / 每轮调用次数 / 判定分布）
    .\.venv\Scripts\python.exe -m coach.metrics.export

    # 导出原始事件
    .\.venv\Scripts\python.exe -m coach.metrics.export --out data\metrics\events.csv
    .\.venv\Scripts\python.exe -m coach.metrics.export --format jsonl --out data\metrics\events.jsonl

    # 指定事件文件
    .\.venv\Scripts\python.exe -m coach.metrics.export --path data\metrics\events.jsonl
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from coach.metrics.recorder import SCHEMA_FIELDS, default_events_path
from coach.metrics.summary import load_events, render_summary, summarize


def export_events(events: list[dict], out_path: Path, fmt: str) -> Path:
    """把原始事件写盘；返回实际写入路径。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(SCHEMA_FIELDS))
            writer.writeheader()
            for event in events:
                writer.writerow({name: event.get(name) for name in SCHEMA_FIELDS})
    else:
        with out_path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出学习教练的指标事件（本机 JSONL）")
    parser.add_argument("--path", help="事件文件路径（默认 data/metrics/events.jsonl）")
    parser.add_argument("--out", help="导出目标路径；不填则只打印汇总")
    parser.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    parser.add_argument("--summary-only", action="store_true", help="只打印汇总，不导出")
    args = parser.parse_args(argv)

    events_path = Path(args.path) if args.path else default_events_path()
    events = load_events(events_path)

    if not events:
        print(f"未找到可读事件：{events_path}")
        print("提示：指标默认在**运行 app（python app.py）时**采集；"
              "也可用 COACH_METRICS=on 让库调用也采集。")
        return 0

    print(f"事件文件：{events_path}")
    print(render_summary(summarize(events)))

    if args.out and not args.summary_only:
        written = export_events(events, Path(args.out), args.format)
        print(f"\n已导出 {len(events)} 条事件：{written}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
