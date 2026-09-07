from __future__ import annotations

import json
from typing import Any

from src.llm import chat


REPORT_SYSTEM = """你是资深商业分析师。根据输入写一份 Markdown 分析报告，结构固定为：

# 数据分析报告
## 1. 数据概览
## 2. 数据质量
## 3. 关键发现
## 4. 图表解读
## 5. 建议与后续分析

要求：中文、简洁、可执行；不要编造未提供的数字。
"""


def write_report(
    filename: str,
    goal: str,
    profile: dict[str, Any],
    insights: list[str],
    chart_specs: list[dict[str, Any]],
) -> str:
    payload = {
        "filename": filename,
        "goal": goal,
        "n_rows": profile.get("n_rows"),
        "n_cols": profile.get("n_cols"),
        "duplicate_rows": profile.get("duplicate_rows"),
        "columns": [
            {
                "name": c.get("name"),
                "kind": c.get("kind"),
                "missing_pct": c.get("missing_pct"),
            }
            for c in (profile.get("columns") or [])
        ],
        "insights": insights,
        "charts": chart_specs,
    }
    return chat(
        [
            {"role": "system", "content": REPORT_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.3,
    )
