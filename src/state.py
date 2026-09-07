from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisState:
    filename: str = ""
    question: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    insights: list[str] = field(default_factory=list)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    report_md: str = ""
    answer: str = ""
    errors: list[str] = field(default_factory=list)
    # 每步耗时（秒），键为步骤名：profile / stats / charts / insights / report
    timings: dict[str, float] = field(default_factory=dict)
