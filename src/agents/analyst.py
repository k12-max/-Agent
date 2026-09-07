"""统计分析：描述统计、相关、分组对比、简单异常值。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def compute_stats(df: pd.DataFrame, profile: dict[str, Any]) -> dict[str, Any]:
    numeric_cols = profile.get("numeric_cols") or []
    cat_cols = profile.get("categorical_cols") or []

    describe: dict[str, Any] = {}
    if numeric_cols:
        describe = (
            df[numeric_cols]
            .describe()
            .round(4)
            .replace({np.nan: None})
            .to_dict()
        )

    corr: dict[str, Any] = {}
    if len(numeric_cols) >= 2:
        corr = (
            df[numeric_cols]
            .corr(numeric_only=True)
            .round(4)
            .replace({np.nan: None})
            .to_dict()
        )

    outliers: dict[str, int] = {}
    for col in numeric_cols:
        s = df[col].dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        mask = (s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)
        outliers[col] = int(mask.sum())

    group_summaries: list[dict[str, Any]] = []
    for cat in cat_cols[:3]:
        for num in numeric_cols[:3]:
            grouped = (
                df.groupby(cat, dropna=True)[num]
                .agg(["count", "mean", "median"])
                .round(4)
                .reset_index()
                .head(12)
            )
            group_summaries.append(
                {
                    "by": cat,
                    "metric": num,
                    "rows": grouped.to_dict(orient="records"),
                }
            )

    return {
        "describe": describe,
        "correlation": corr,
        "outliers_iqr": outliers,
        "group_summaries": group_summaries,
    }
