from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# 超过该行数对散点/折线做均匀下采样，避免浏览器卡顿
_SCATTER_SAMPLE_ROWS = 20_000


def _maybe_sample(df: pd.DataFrame, max_rows: int = _SCATTER_SAMPLE_ROWS) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df
    step = max(1, len(df) // max_rows)
    return df.iloc[::step].copy()


def render_chart(df: pd.DataFrame, spec: dict[str, Any]):
    kind = spec.get("type")

    # --- 折线图（可按时间列聚合） ---
    if kind == "line":
        x_col, y_col = spec["x"], spec["y"]
        work = df[[x_col, y_col]].dropna()
        if pd.api.types.is_datetime64_any_dtype(work[x_col]):
            # 时间轴按天聚合（原始粒度太细导致乱线）
            grouped = work.set_index(x_col)[y_col].resample("D").mean().reset_index()
            grouped = _maybe_sample(grouped, max_rows=2_000)
            return px.line(grouped, x=x_col, y=y_col, title=spec.get("title"))
        work = work.sort_values(x_col)
        work = _maybe_sample(work)
        return px.line(work, x=x_col, y=y_col, title=spec.get("title"))

    # --- 柱状图 ---
    if kind == "bar":
        agg = spec.get("agg") or "mean"
        x_col, y_col = spec["x"], spec["y"]
        grouped = df.groupby(x_col, dropna=True)[y_col].agg(agg).reset_index()
        grouped = grouped.sort_values(y_col, ascending=False).head(20)
        return px.bar(grouped, x=x_col, y=y_col, title=spec.get("title"))

    # --- 散点图（大数据下采样 + 可选颜色分组） ---
    if kind == "scatter":
        x_col, y_col = spec["x"], spec["y"]
        keep_cols = [x_col, y_col]
        color_col = spec.get("color") if spec.get("color") and spec["color"] in df.columns else None
        if color_col:
            keep_cols.append(color_col)
        work = df[keep_cols].dropna()
        work = _maybe_sample(work)
        kwargs: dict[str, Any] = {"x": x_col, "y": y_col, "title": spec.get("title")}
        if color_col:
            kwargs["color"] = color_col
        kwargs.setdefault("opacity", 0.6)
        return px.scatter(work, **kwargs)

    # --- 直方图 ---
    if kind == "histogram":
        return px.histogram(df, x=spec["x"], title=spec.get("title"), nbins=30)

    # --- 相关性热力图（含数值标注） ---
    if kind == "heatmap":
        corr = df.select_dtypes(include="number").corr()
        if corr.empty:
            return None
        fig = go.Figure(
            data=go.Heatmap(
                z=corr.values,
                x=list(corr.columns),
                y=list(corr.index),
                colorscale="RdBu",
                zmid=0,
                text=corr.round(2).astype(str).values,
                texttemplate="%{text}",
            )
        )
        fig.update_layout(title=spec.get("title") or "相关性")
        return fig

    # --- 箱线图（按分类列分组查看数值分布） ---
    if kind == "box":
        x_col, y_col = spec.get("x"), spec.get("y")
        if not y_col:
            return None
        keep_cols = [c for c in (x_col, y_col) if c]
        work = df[keep_cols].dropna()
        if len(work) == 0:
            return None
        # 分类过多只保留 Top 10
        if x_col and work[x_col].nunique() > 10:
            top = work[x_col].value_counts().head(10).index
            work = work[work[x_col].isin(top)]
        kwargs: dict[str, Any] = {"y": y_col, "title": spec.get("title")}
        if x_col:
            kwargs["x"] = x_col
        return px.box(work, **kwargs)

    # --- 饼图（分类列占比） ---
    if kind == "pie":
        name_col = spec.get("names")
        value_col = spec.get("values")
        if not name_col:
            return None
        work = df.copy()
        if value_col and value_col in work.columns:
            grouped = (
                work.groupby(name_col, dropna=True)[value_col]
                .sum()
                .reset_index()
                .sort_values(value_col, ascending=False)
            )
        else:
            grouped = work[name_col].value_counts().reset_index()
            grouped.columns = [name_col, "count"]
            value_col = "count"
        # Top 8 + Others
        if len(grouped) > 8:
            top = grouped.head(8)
            others = pd.DataFrame(
                {name_col: ["其他"], value_col: [grouped.iloc[8:][value_col].sum()]}
            )
            grouped = pd.concat([top, others], ignore_index=True)
        return px.pie(grouped, names=name_col, values=value_col, title=spec.get("title"))

    return None
