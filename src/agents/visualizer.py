"""根据画像自动挑选图表规格，由 UI 用 Plotly 渲染。

目前支持：line / bar / scatter / histogram / heatmap / box / pie
按数据特征推荐最多 6 张，每张 spec 都附带 reason 小字说明（UI 可展示）。
"""

from __future__ import annotations

from typing import Any


def _add(specs: list[dict[str, Any]], spec: dict[str, Any], reason: str) -> None:
    spec.setdefault("reason", reason)
    specs.append(spec)


def propose_charts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    numeric = profile.get("numeric_cols") or []
    cats = profile.get("categorical_cols") or []
    dts = profile.get("datetime_cols") or []
    specs: list[dict[str, Any]] = []

    # 1) 时间趋势折线（有时间列 + 数值列时）
    if dts and numeric:
        _add(
            specs,
            {
                "type": "line",
                "title": f"{numeric[0]} 随时间变化",
                "x": dts[0],
                "y": numeric[0],
            },
            reason=f"{dts[0]} 为时间列，可观察 {numeric[0]} 是否存在周期性/趋势性变化。",
        )

    # 2) 分类汇总柱状图
    if cats and numeric:
        _add(
            specs,
            {
                "type": "bar",
                "title": f"按 {cats[0]} 汇总 {numeric[0]}",
                "x": cats[0],
                "y": numeric[0],
                "agg": "mean",
            },
            reason=f"观察 {cats[0]} 各分类在 {numeric[0]} 上的均值差异，快速找出高低组。",
        )

    # 3) 双数值散点（至少 2 个数值列才推荐，避免空图）
    if len(numeric) >= 2:
        _add(
            specs,
            {
                "type": "scatter",
                "title": f"{numeric[0]} vs {numeric[1]}",
                "x": numeric[0],
                "y": numeric[1],
                "color": cats[0] if cats else None,
            },
            reason=f"观察 {numeric[0]} 与 {numeric[1]} 的相关性，散点越接近直线关系越强。",
        )

    # 4) 数值分布直方图
    if numeric:
        _add(
            specs,
            {
                "type": "histogram",
                "title": f"{numeric[0]} 分布",
                "x": numeric[0],
            },
            reason=f"查看 {numeric[0]} 是否正态、是否偏态、是否存在双峰或长尾异常。",
        )

    # 5) 分类 × 数值的箱线图（查看分布差异 + 异常值）
    if cats and numeric:
        _add(
            specs,
            {
                "type": "box",
                "title": f"{numeric[0]} 按 {cats[0]} 分布",
                "x": cats[0],
                "y": numeric[0],
            },
            reason=f"箱线图可同时看到 {cats[0]} 各组中位数、四分位距与离群点。",
        )

    # 6) 分类占比饼图
    if cats:
        _add(
            specs,
            {
                "type": "pie",
                "title": f"{cats[0]} 占比",
                "names": cats[0],
                "values": numeric[0] if numeric else None,
            },
            reason=(
                f"{cats[0]} 为分类列，"
                + (f"按 {numeric[0]} 贡献查看占比。" if numeric else "按记录数查看占比。")
            ),
        )

    # 7) 数值列相关性热力图（至少 2 个数值列才推荐，避免空图）
    if len(numeric) >= 2:
        _add(
            specs,
            {"type": "heatmap", "title": "数值列相关性热力图"},
            reason=f"快速发现 {len(numeric)} 个数值列之间强弱相关关系，红色正相关、蓝色负相关。",
        )

    return specs[:6]
