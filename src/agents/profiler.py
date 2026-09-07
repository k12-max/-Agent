"""数据画像：类型、缺失、基数、样例。不调用 LLM，保证稳定可复现。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.config import settings


def _col_kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    nunique = series.nunique(dropna=True)
    if nunique <= settings.max_categorical_levels:
        return "categorical"
    return "text"


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for name in df.columns:
        s = df[name]
        kind = _col_kind(s)
        item: dict[str, Any] = {
            "name": str(name),
            "kind": kind,
            "dtype": str(s.dtype),
            "missing": int(s.isna().sum()),
            "missing_pct": round(float(s.isna().mean() * 100), 2),
            "nunique": int(s.nunique(dropna=True)),
        }
        if kind == "numeric":
            desc = s.describe()
            item["min"] = _to_json_number(desc.get("min"))
            item["max"] = _to_json_number(desc.get("max"))
            item["mean"] = _to_json_number(desc.get("mean"))
            item["std"] = _to_json_number(desc.get("std"))
        elif kind == "categorical":
            item["top"] = (
                s.astype(str).value_counts(dropna=True).head(8).to_dict()
            )
        columns.append(item)

    numeric_cols = [c["name"] for c in columns if c["kind"] == "numeric"]
    cat_cols = [c["name"] for c in columns if c["kind"] == "categorical"]
    dt_cols = [c["name"] for c in columns if c["kind"] == "datetime"]

    return {
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "columns": columns,
        "numeric_cols": numeric_cols,
        "categorical_cols": cat_cols,
        "datetime_cols": dt_cols,
        "preview": df.head(settings.max_preview_rows).astype(str).to_dict(orient="records"),
        "duplicate_rows": int(df.duplicated().sum()),
    }


def _to_json_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)
