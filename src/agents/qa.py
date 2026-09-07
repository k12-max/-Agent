"""带工具调用的问答 Agent：用 pandas 查询当前数据集。

返回元组 (answer, meta)：
- answer: 面向用户的最终中文回答
- meta:   dict，含 steps(工具调用过程)、n_rounds、tool_calls、tokens_est、elapsed_ms、
          final_reason(stop 原因：model 直接回答 / 轮次超限)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from openai.types.chat import ChatCompletionMessageParam

from src.config import settings
from src.llm import get_client
from src.tools.pandas_tools import TOOLS, run_tool

_MAX_ROUNDS = 6

QA_SYSTEM = """你是表格数据分析助手。必须基于工具返回的真实结果回答。
规则：
- 需要数字、分布、筛选、分组时先调用工具
- 列名必须与数据集完全一致
- 用中文回答，先给结论，再给简要依据
- 不要编造工具未返回的数据
"""

_OVER_LIMIT_HINT = (
    "当前问题比较复杂，已达到最大分析轮次。建议拆成更具体的小问题，例如：\n"
    " 1) 先用聚合工具问「各 {metric_col} 的 {agg}」\n"
    " 2) 再用筛选工具问「大于/小于 X 的 {group_col} 有哪些」\n"
    " 3) 最后用相关工具看「与目标列高度相关的数值列」"
)


@dataclass
class QAResult:
    answer: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    n_rounds: int = 0
    tool_calls: int = 0
    tokens_est: int = 0
    elapsed_ms: int = 0
    final_reason: str = "max_rounds"  # model_answer | max_rounds | error

    def as_flat_tuple(self) -> tuple[str, dict[str, Any]]:
        meta = {
            "steps": self.steps,
            "n_rounds": self.n_rounds,
            "tool_calls": self.tool_calls,
            "tokens_est": self.tokens_est,
            "elapsed_ms": self.elapsed_ms,
            "final_reason": self.final_reason,
        }
        return self.answer, meta


def _parse_tool_args(raw: str) -> dict[str, Any] | None:
    """解析工具调用参数，容忍全角标点损坏。返回 None 表示无法解析。"""
    text = (raw or "").strip() or "{}"
    candidates = [
        text,
        text.replace("“", '"')
        .replace("”", '"')
        .replace("：", ":")
        .replace("，", ","),
    ]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def answer_question(
    df: pd.DataFrame,
    profile: dict[str, Any],
    question: str,
    max_rounds: int = _MAX_ROUNDS,
) -> tuple[str, dict[str, Any]]:
    """新 API：返回 (answer_str, meta_dict)。兼容旧调用：仅取第一个值。"""
    result = QAResult(answer="", final_reason="max_rounds")
    t0 = time.perf_counter()

    try:
        client = get_client()
    except Exception as exc:  # noqa: BLE001
        result.answer = f"LLM 客户端初始化失败：{exc}"
        result.final_reason = "error"
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return result.as_flat_tuple()

    numeric_cols = profile.get("numeric_cols") or []
    cat_cols = profile.get("categorical_cols") or []
    col_brief = [f"{c['name']} ({c['kind']})" for c in (profile.get("columns") or [])]
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": QA_SYSTEM},
        {
            "role": "user",
            "content": (
                f"数据集列：{', '.join(col_brief)}\n"
                f"行数：{profile.get('n_rows')}\n"
                f"数值列：{numeric_cols}\n"
                f"分类列：{cat_cols}\n"
                f"问题：{question}"
            ),
        },
    ]

    chars_in = sum(len(str(m.get("content", ""))) for m in messages)

    for round_idx in range(1, max_rounds + 1):
        result.n_rounds = round_idx
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1,
            )
        except Exception as exc:  # noqa: BLE001
            result.answer = f"LLM 调用失败：{exc}"
            result.final_reason = "error"
            break

        msg = response.choices[0].message
        # 估算 token（非常粗略：4 中文字符/token + 英文 0.25 char/token，合计后取整）
        # 仅用于 UI 展示数量级，不计入官方用量
        reply_chars = len(str(msg.content or ""))
        result.tokens_est += int((chars_in + reply_chars) // 3)
        chars_in += reply_chars

        if not msg.tool_calls:
            result.answer = (msg.content or "").strip()
            result.final_reason = "model_answer"
            break

        messages.append(msg)
        for call in msg.tool_calls:
            result.tool_calls += 1
            args = _parse_tool_args(call.function.arguments or "")
            if args is None:
                args = {}
                error_info = {"error": "工具参数不是合法 JSON（可能含全角标点），请用半角符号重试"}
            else:
                error_info = None

            step_record: dict[str, Any] = {
                "round": round_idx,
                "tool": call.function.name,
                "args": args,
            }
            t_tool = time.perf_counter()
            if error_info:
                tool_result = json.dumps(error_info, ensure_ascii=False)
            else:
                tool_result = run_tool(df, call.function.name, args)
            step_record["elapsed_ms"] = int((time.perf_counter() - t_tool) * 1000)
            step_record["result_chars"] = len(tool_result)
            # 只给模型看完整 result；UI 展示时截断 200 字
            try:
                parsed = json.loads(tool_result)
                # 列表/字典类，记录总行数/键数
                if isinstance(parsed, list):
                    step_record["result_rows"] = len(parsed)
                    if parsed:
                        step_record["result_preview"] = parsed[:3]
                elif isinstance(parsed, dict):
                    step_record["result_rows"] = len(parsed)
                    step_record["result_preview_keys"] = list(parsed.keys())[:8]
                    step_record["result_preview"] = {k: parsed[k] for k in list(parsed.keys())[:3]}
                else:
                    step_record["result_preview"] = str(parsed)[:200]
            except Exception:
                step_record["result_preview"] = tool_result[:200]
            result.steps.append(step_record)

            tool_msg: ChatCompletionMessageParam = {
                "role": "tool",
                "tool_call_id": call.id,
                "content": tool_result,
            }
            messages.append(tool_msg)
            chars_in += len(tool_result)
    else:
        # 6 轮用完仍没出答案
        sample_num = (numeric_cols[:1] or ["数值指标"])[0]
        sample_cat = (cat_cols[:1] or ["分类维度"])[0]
        result.answer = (
            "分析轮次过多，请把问题拆得更具体一些后再问。\n\n建议拆解示例：\n"
            + _OVER_LIMIT_HINT.format(metric_col=sample_num, group_col=sample_cat, agg="均值/合计")
        )
        result.final_reason = "max_rounds"

    result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return result.as_flat_tuple()
