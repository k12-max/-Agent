from __future__ import annotations

import json
from typing import Any

import pandas as pd

# 工具返回 JSON 的字符上限（>8K 瘦身，避免撑爆 QA LLM 上下文）
_MAX_RESULT_CHARS = 8_000

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_rows",
            "description": "按条件筛选后返回前若干行。condition 为 pandas query 表达式，可为空。",
            "parameters": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string"},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": "分组聚合。agg 为 mean/sum/count/median/min/max/std。",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "value": {"type": "string"},
                    "agg": {"type": "string"},
                    "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 500},
                },
                "required": ["value", "agg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "value_counts",
            "description": "分类列频次统计。",
            "parameters": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                },
                "required": ["column"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correlation",
            "description": "数值列相关系数。columns 为空则使用全部数值列。",
            "parameters": {
                "type": "object",
                "properties": {
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
            },
        },
    },
]

_VALID_AGG = {"mean", "sum", "count", "median", "min", "max", "std"}


def _truncate(result_json: str, total_rows: int | None = None) -> str:
    """若返回 JSON 字符数过大，附加 truncated 标记并在必要时瘦身。"""
    if len(result_json) <= _MAX_RESULT_CHARS:
        return result_json
    try:
        obj = json.loads(result_json)
        obj["_truncated"] = True
        obj["_original_chars"] = len(result_json)
        if total_rows is not None:
            obj["_total_rows"] = total_rows
        # 列表类只留前 N 条
        for key in ("rows", "values", "items"):
            if isinstance(obj.get(key), list):
                obj[key] = obj[key][:30]
                obj[f"_{key}_total"] = total_rows or len(obj.get(key, []))
        out = json.dumps(obj, ensure_ascii=False, default=str)
        return out
    except Exception:
        # JSON 反解失败就原样返回，并追加提示
        return (
            result_json[: _MAX_RESULT_CHARS - 200]
            + f"\n...(已截断，原始长度 {len(result_json)} 字符)"
        )


def run_tool(df: pd.DataFrame, name: str, args: dict[str, Any]) -> str:
    try:
        if name == "query_rows":
            _validate_columns(df, args.get("columns"))
            return _query_rows(df, args)
        if name == "aggregate":
            if args.get("agg") not in _VALID_AGG:
                raise ValueError(f"agg 必须是 {sorted(_VALID_AGG)} 之一，实际：{args.get('agg')}")
            _validate_columns(df, args.get("group_by"))
            _validate_columns(df, [args.get("value")] if args.get("value") else None)
            return _aggregate(df, args)
        if name == "value_counts":
            _validate_columns(df, [args.get("column")] if args.get("column") else None)
            return _value_counts(df, args)
        if name == "correlation":
            _validate_columns(df, args.get("columns"))
            return _correlation(df, args)
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - 工具错误需回传给模型
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _validate_columns(df: pd.DataFrame, columns: list[str] | None) -> None:
    """校验 columns 是否都存在于 df，避免 KeyError 中断 Agent 推理。"""
    if not columns:
        return
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"列不存在：{missing}。可用列：{list(df.columns)}")


def _query_rows(df: pd.DataFrame, args: dict[str, Any]) -> str:
    work = df
    condition = (args.get("condition") or "").strip()
    if condition:
        try:
            work = work.query(condition, engine="python")
        except Exception as exc:
            raise ValueError(f"query 表达式无效：{exc}")
    columns = args.get("columns") or list(work.columns)
    limit = max(1, min(int(args.get("limit") or 20), 200))
    total = int(len(work))
    sample = work[columns].head(limit)
    raw = json.dumps(
        {"n_matched": total, "rows": sample.astype(str).to_dict(orient="records")},
        ensure_ascii=False,
    )
    return _truncate(raw, total_rows=total)


def _aggregate(df: pd.DataFrame, args: dict[str, Any]) -> str:
    value = args["value"]
    agg = args.get("agg") or "mean"
    group_by = args.get("group_by") or []
    limit = max(1, min(int(args.get("limit") or 30), 500))
    if agg == "count":
        if group_by:
            out = df.groupby(group_by, dropna=False).size().reset_index(name="count")
        else:
            out = pd.DataFrame({"count": [len(df)]})
    else:
        if not pd.api.types.is_numeric_dtype(df[value]):
            raise ValueError(f"列 {value} 不是数值类型，无法做 {agg} 聚合")
        series = df[value]
        if group_by:
            out = getattr(df.groupby(group_by, dropna=False)[value], agg)().reset_index()
        else:
            out = pd.DataFrame({value: [getattr(series, agg)()]})
    total = len(out)
    raw = json.dumps(out.head(limit).to_dict(orient="records"), ensure_ascii=False, default=str)
    return _truncate(raw, total_rows=total)


def _value_counts(df: pd.DataFrame, args: dict[str, Any]) -> str:
    column = args["column"]
    limit = max(1, min(int(args.get("limit") or 20), 200))
    vc = df[column].value_counts(dropna=False)
    total = int(len(vc))
    vc = vc.head(limit)
    rows = [{"value": str(idx), "count": int(cnt)} for idx, cnt in vc.items()]
    raw = json.dumps(rows, ensure_ascii=False)
    return _truncate(raw, total_rows=total)


def _correlation(df: pd.DataFrame, args: dict[str, Any]) -> str:
    columns = args.get("columns")
    work = df[columns] if columns else df.select_dtypes(include="number")
    if work.shape[1] < 2:
        raise ValueError(f"至少需要 2 个数值列才能计算相关系数，实际：{work.shape[1]}")
    corr = work.corr(numeric_only=True).round(4)
    raw = corr.to_json(force_ascii=False)
    return _truncate(raw, total_rows=int(corr.shape[0] * corr.shape[1]))
