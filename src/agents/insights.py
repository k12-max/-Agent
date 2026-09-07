from __future__ import annotations

import json
import re
from typing import Any

from src.llm import chat


INSIGHT_SYSTEM = """你是数据分析师。根据数据画像和统计结果，输出 JSON：
{"insights": ["发现1", "发现2", ...]}
要求：
- 3 到 8 条，每条一句话，具体到列名和数量级
- 覆盖质量问题、分布、相关、分组差异、异常值（有则写）
- 不要编造表中不存在的字段或数字
- 使用中文
- ⚠️ JSON 语法符号必须用半角：英文双引号(")、英文冒号(:)、英文逗号(,)、英文花括号({})，
  严禁使用中文全角标点（“”：，），否则程序无法解析
"""


def generate_insights(profile: dict[str, Any], stats: dict[str, Any], goal: str) -> list[str]:
    payload = {
        "user_goal": goal or "全面了解这份数据并找出关键模式",
        "profile": _slim_profile(profile),
        "stats": _slim_stats(stats),
    }
    messages = [
        {"role": "system", "content": INSIGHT_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]

    # 第一次正常调用（json_mode）
    raw = chat(messages, json_mode=True)
    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        # 输出损坏（全角标点/结构错乱）→ 附上坏输出 + 修正指令，temperature=0 再试一次
        fix_messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "你上一次的输出不是合法 JSON（很可能使用了中文全角标点或结构错误），程序无法解析。"
                    "请重新输出：只输出一个合法 JSON 对象，所有符号用半角（\" : , { }），"
                    "不要输出任何解释文字或代码围栏。"
                ),
            },
        ]
        raw2 = chat(fix_messages, temperature=0.0, json_mode=True)
        data = _extract_json(raw2)

    insights = data.get("insights") or []
    return [str(x) for x in insights if str(x).strip()]


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中稳健提取 JSON 对象。

    容忍三类常见问题：```json 代码围栏、<think>…</think> 推理段（r1 系模型）、
    JSON 前后的多余文字。
    """
    cleaned = text.strip()
    # 1) 去掉 <think>…</think>（DeepSeek-R1 系推理模型会输出）
    if "<think>" in cleaned:
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()
    # 2) 直接解析
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # 3) 去掉 markdown 代码围栏后再解析
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    # 4) 提取第一个平衡的 {...} 块
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except Exception:
                        break
    # 5) 最后手段：全角标点归一化（“”→" ：→: ，→,）后再解析。
    #    此前所有尝试都失败说明输出已损坏，归一化副作用可接受；
    #    值内部的全角引号被替换可能截断字符串，但成功即赚、失败则走重试/兜底。
    normalized = (
        cleaned.replace("“", '"')
        .replace("”", '"')
        .replace("：", ":")
        .replace("，", ",")
    )
    try:
        return json.loads(normalized)
    except Exception:
        pass
    start = normalized.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(normalized)):
            if normalized[i] == "{":
                depth += 1
            elif normalized[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(normalized[start : i + 1])
                    except Exception:
                        break
    raise ValueError(f"模型输出不是合法 JSON：{text[:200]!r}")


def _slim_profile(profile: dict[str, Any]) -> dict[str, Any]:
    cols = []
    for c in profile.get("columns") or []:
        cols.append(
            {
                "name": c.get("name"),
                "kind": c.get("kind"),
                "missing_pct": c.get("missing_pct"),
                "nunique": c.get("nunique"),
                "mean": c.get("mean"),
                "min": c.get("min"),
                "max": c.get("max"),
            }
        )
    return {
        "n_rows": profile.get("n_rows"),
        "n_cols": profile.get("n_cols"),
        "duplicate_rows": profile.get("duplicate_rows"),
        "columns": cols,
        "preview": (profile.get("preview") or [])[:5],
    }


def _slim_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "outliers_iqr": stats.get("outliers_iqr"),
        "correlation": stats.get("correlation"),
        "group_summaries": (stats.get("group_summaries") or [])[:4],
    }
