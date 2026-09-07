"""数据分析 Agent 集合：画像/统计/图表/洞察/报告/问答。"""

from src.agents.analyst import compute_stats
from src.agents.insights import generate_insights
from src.agents.profiler import profile_dataframe
from src.agents.qa import answer_question
from src.agents.reporter import write_report
from src.agents.visualizer import propose_charts

__all__ = [
    "profile_dataframe",
    "compute_stats",
    "propose_charts",
    "generate_insights",
    "write_report",
    "answer_question",
]
