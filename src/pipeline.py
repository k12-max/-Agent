"""自动分析流水线：画像 → 统计 → 图表规格 → LLM 洞察 → 报告。

可传入 progress_callback 实时反馈进度（0.0 ~ 1.0），用于 Streamlit 进度条。
state.timings 记录每一步耗时（秒）。
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pandas as pd

from src.agents.analyst import compute_stats
from src.agents.insights import generate_insights
from src.agents.profiler import profile_dataframe
from src.agents.reporter import write_report
from src.agents.visualizer import propose_charts
from src.state import AnalysisState

# 每步权重（画像/统计/图表/洞察/报告）
_STEP_WEIGHTS = (0.15, 0.25, 0.10, 0.25, 0.25)
_STEP_NAMES = ("profile", "stats", "charts", "insights", "report")
_STEP_LABELS = ("数据画像", "统计计算", "图表规划", "洞察生成", "报告撰写")


def run_auto_analysis(
    df: pd.DataFrame,
    filename: str,
    goal: str = "",
    progress_callback: Callable[[float, str], None] | None = None,
) -> AnalysisState:
    state = AnalysisState(filename=filename, question=goal)

    def _step(i: int, work_fn) -> Any:
        name = _STEP_NAMES[i]
        label = _STEP_LABELS[i]
        if progress_callback:
            cum_before = sum(_STEP_WEIGHTS[:i])
            progress_callback(cum_before, f"开始 {label}…")
        t0 = time.perf_counter()
        try:
            result = work_fn()
            return result
        finally:
            state.timings[name] = round(time.perf_counter() - t0, 3)
            if progress_callback:
                cum = sum(_STEP_WEIGHTS[: i + 1])
                progress_callback(cum, f"✓ {label} 完成 ({state.timings[name]}s)")

    # 1. 画像
    state.profile = _step(0, lambda: profile_dataframe(df))

    # 2. 统计
    state.stats = _step(1, lambda: compute_stats(df, state.profile))

    # 3. 图表
    state.chart_specs = _step(2, lambda: propose_charts(state.profile))

    # 4/5. LLM 洞察 + 报告（失败走兜底）
    try:
        state.insights = _step(3, lambda: generate_insights(state.profile, state.stats, goal))
        state.report_md = _step(
            4,
            lambda: write_report(
                filename=filename,
                goal=goal,
                profile=state.profile,
                insights=state.insights,
                chart_specs=state.chart_specs,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        state.errors.append(str(exc))
        t0 = time.perf_counter()
        state.insights = _fallback_insights(state.profile, state.stats)
        state.timings.setdefault("insights", round(time.perf_counter() - t0, 3))
        t0 = time.perf_counter()
        state.report_md = _fallback_report(filename, state)
        state.timings.setdefault("report", round(time.perf_counter() - t0, 3))
        if progress_callback:
            progress_callback(1.0, "LLM 不可用，已使用规则兜底结果")

    state.timings["total"] = round(sum(state.timings.values()), 3)
    return state


def _fallback_insights(profile: dict, stats: dict) -> list[str]:
    insights = [
        f"数据集共 {profile.get('n_rows')} 行、{profile.get('n_cols')} 列。",
    ]
    missing = [
        c for c in profile.get("columns", []) if (c.get("missing_pct") or 0) > 0
    ]
    if missing:
        names = "、".join(c["name"] for c in missing[:5])
        insights.append(f"存在缺失值的字段：{names}。")
    outliers = stats.get("outliers_iqr") or {}
    if outliers:
        top = max(outliers, key=outliers.get)
        insights.append(f"{top} 按 IQR 规则检出 {outliers[top]} 个潜在异常值。")
    return insights


def _fallback_report(filename: str, state: AnalysisState) -> str:
    lines = [
        "# 数据分析报告",
        f"## 1. 数据概览\n文件 `{filename}`，{state.profile.get('n_rows')} 行 × {state.profile.get('n_cols')} 列。",
        "## 2. 数据质量",
        f"重复行 {state.profile.get('duplicate_rows')}。",
        "## 3. 关键发现",
        *[f"- {x}" for x in state.insights],
        "## 4. 图表解读\n见页面图表。",
        "## 5. 建议与后续分析\n配置 LLM 密钥后可生成更完整的文字报告。",
    ]
    if state.errors:
        lines.append(f"\n> LLM 调用失败：{state.errors[0]}")
    return "\n\n".join(lines)
