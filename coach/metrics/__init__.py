"""指标采集层：事件记录、汇总与导出（PRD S-07 / §3.5）。

    recorder  事件 schema + JSONL 记录器（fail-safe）
    summary   读取事件并汇总出 §3.1/§3.2 的指标
    export    CLI：python -m coach.metrics.export

约束：本层只读/写本机 `data/metrics/`，不参与业务判断；
采集失败绝不影响主流程。
"""
