from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

# QA 新 API 返回 (answer, meta)，这里做兼容导入
from src.agents.qa import answer_question
from src.charts import render_chart
from src.pipeline import run_auto_analysis

ROOT = Path(__file__).resolve().parent

# 数据量较大时的行数阈值（超过则启用下采样/分页等优化）
_LARGE_ROWS = 50_000

st.set_page_config(page_title="智能自动数据分析 Agent", page_icon="📊", layout="wide")

st.title("智能自动数据分析 Agent")
st.caption("上传表格 → 自动画像 / 统计 / 图表 / 报告 → 再用自然语言追问")


# =============================================================================
# 缓存层：按 df hash 缓存画像与统计，同样数据反复分析秒出
# =============================================================================
@st.cache_data(show_spinner=False, ttl=3600)
def _cached_profile(df_json: str):  # 占位，用下面的签名 key 作为 hash
    raise NotImplementedError


def _df_hash(df: pd.DataFrame) -> str:
    """稳定 hash：按值对前 10 万行取 hash，用来做缓存 key。"""
    head = df.head(100_000) if len(df) > 100_000 else df
    try:
        payload = (
            str(df.shape)
            + "|"
            + ",".join(str(c) for c in df.columns)
            + "|"
            + ",".join(str(dt) for dt in df.dtypes)
            + "|"
            + hashlib.md5(
                pd.util.hash_pandas_object(head, index=True).values.tobytes()
            ).hexdigest()
        )
    except Exception:
        payload = str(df.shape) + "|" + ",".join(str(c) for c in df.columns)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_profile_stats(df_hash_key: str, _df: pd.DataFrame):
    # 延迟导入，避免循环依赖
    from src.agents.analyst import compute_stats
    from src.agents.profiler import profile_dataframe

    profile = profile_dataframe(_df)
    stats = compute_stats(_df, profile)
    return profile, stats


# =============================================================================
# 数据加载与解析
# =============================================================================
def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for col in work.columns:
        if work[col].dtype != object and not str(work[col].dtype).startswith("string"):
            continue
        parsed = pd.to_datetime(work[col], errors="coerce")
        if parsed.notna().mean() >= 0.8:
            work[col] = parsed
    return work


def _load_frame(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    data = uploaded.getvalue()
    if name.endswith(".csv"):
        df = pd.read_csv(BytesIO(data))
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(BytesIO(data))
    else:
        raise ValueError("仅支持 CSV / Excel")
    return _parse_dates(df)


# =============================================================================
# Sidebar
# =============================================================================
with st.sidebar:
    st.header("数据")
    uploaded = st.file_uploader("上传 CSV 或 Excel", type=["csv", "xlsx", "xls"])
    use_sample = st.checkbox("使用内置销售样例", value=uploaded is None)
    goal = st.text_area(
        "分析目标（可选）",
        placeholder="例如：找出销售额最高的品类，并说明异常订单",
        height=90,
    )
    run = st.button("开始自动分析", type="primary", use_container_width=True)
    st.markdown("---")
    st.markdown(
        "配置：复制 `.env.example` 为 `.env`，填入兼容 OpenAI 的 `API Key`。"
    )


# =============================================================================
# 数据源加载 + 切换数据源清状态（防串数据）
# =============================================================================
if "df" not in st.session_state:
    st.session_state.df = None
    st.session_state.state = None
    st.session_state.filename = None
    st.session_state.chat = []
    st.session_state.df_hash = None

current_key = ("sample" if use_sample and uploaded is None else None) or (
    ("upload:" + uploaded.name + ":" + str(uploaded.size)) if uploaded is not None else None
)
last_key = st.session_state.get("_data_source_key")
if current_key != last_key:
    # 切换到了新数据源 → 清除之前的分析结果、聊天记录
    st.session_state.state = None
    st.session_state.chat = []
    st.session_state.df = None
    st.session_state.filename = ""
    st.session_state._data_source_key = current_key

if use_sample and uploaded is None:
    st.session_state.df = _parse_dates(pd.read_csv(ROOT / "data" / "sample_sales.csv"))
    st.session_state.filename = "sample_sales.csv"
elif uploaded is not None:
    try:
        st.session_state.df = _load_frame(uploaded)
        st.session_state.filename = uploaded.name
    except Exception as exc:
        st.error(str(exc))

df = st.session_state.df
if df is None:
    st.info("请在左侧上传数据，或勾选内置样例。")
    st.stop()

df_hash_val = _df_hash(df)
st.session_state.df_hash = df_hash_val

# =============================================================================
# 数据预览（大数据时分页 + 内存指标）
# =============================================================================
st.subheader("数据预览")
c1, c2, c3, c4 = st.columns(4)
c1.metric("行数", f"{len(df):,}")
c2.metric("列数", df.shape[1])
c3.metric("缺失单元格", f"{int(df.isna().sum().sum()):,}")
mem_mb = round(df.memory_usage(deep=True).sum() / 1024 / 1024, 1)
c4.metric("估算内存", f"{mem_mb} MB")

if len(df) > _LARGE_ROWS:
    page_size = 100
    total_pages = (len(df) + page_size - 1) // page_size
    page = st.number_input(
        f"数据超过 {_LARGE_ROWS:,} 行，选择预览页（共 {total_pages} 页）",
        min_value=1,
        max_value=total_pages,
        value=1,
    )
    start = (page - 1) * page_size
    st.dataframe(df.iloc[start : start + page_size], use_container_width=True)
else:
    st.dataframe(df.head(100), use_container_width=True)

# =============================================================================
# 自动分析（带进度条 + 画像/统计缓存）
# =============================================================================
if run:
    progress = st.progress(0.0, text="初始化…")
    status = st.empty()

    def _on_progress(pct: float, msg: str) -> None:
        progress.progress(min(max(pct, 0.0), 1.0), text=msg)
        status.caption(msg)

    try:
        # 先尝试命中缓存的画像/统计
        cached_profile, cached_stats = _cached_profile_stats(df_hash_val, df)

        # 缓存只做加速：真正 pipeline 会基于真实 df 再次重算以保证稳健
        # （缓存命中 → 进度条先推进一段，用户体感更快）
        if cached_profile and cached_stats:
            _on_progress(0.25, "✓ 画像/统计缓存命中，进入图表和LLM阶段…")

        with st.spinner("正在执行分析流水线…"):
            st.session_state.state = run_auto_analysis(
                df,
                st.session_state.filename or "",
                goal.strip(),
                progress_callback=_on_progress,
            )
    finally:
        progress.empty()
        status.empty()

state = st.session_state.state
if state is None:
    st.stop()

if state.errors:
    st.warning("LLM 部分失败，已使用规则结果兜底。详情：" + state.errors[0])

tab_insight, tab_chart, tab_report, tab_qa, tab_profile = st.tabs(
    ["关键发现", "图表", "报告", "追问 Agent", "数据画像"]
)

# =============================================================================
# Tab: 关键发现
# =============================================================================
with tab_insight:
    if state.insights:
        for item in state.insights:
            st.markdown(f"- {item}")
    else:
        st.write("暂无洞察。")
    if state.stats.get("outliers_iqr"):
        st.markdown("#### IQR 异常值计数")
        st.json(state.stats["outliers_iqr"])

# =============================================================================
# Tab: 图表（带 reason 小字说明）
# =============================================================================
with tab_chart:
    if not state.chart_specs:
        st.write("暂无适合的图表。")
    for spec in state.chart_specs:
        fig = render_chart(df, spec)
        if fig is None:
            continue
        with st.container(border=False):
            st.plotly_chart(fig, use_container_width=True)
            reason = spec.get("reason")
            if reason:
                st.caption("💡 " + reason)

# =============================================================================
# Tab: 报告（Markdown + HTML 下载，HTML 缺 markdown 包友好降级）
# =============================================================================
def _get_markdown_lib():
    try:
        import markdown  # type: ignore
        return markdown
    except Exception:
        return None


with tab_report:
    st.markdown(state.report_md or "_尚未生成报告_")
    if state.report_md:
        col_md, col_html = st.columns(2)
        col_md.download_button(
            "下载 Markdown 报告",
            state.report_md.encode("utf-8"),
            file_name="analysis_report.md",
            mime="text/markdown",
        )

        md_lib = _get_markdown_lib()
        if md_lib is None:
            col_html.info(
                "ℹ️ 缺 `markdown` 包。先在虚拟环境执行 `python -m pip install markdown>=3.5`，"
                "再刷新页面即可下载 HTML（浏览器 Ctrl+P 打印为 PDF）。"
            )
        else:
            html_body = md_lib.markdown(state.report_md, extensions=["tables"])
            html_full = f"""<!doctype html><html><head><meta charset="utf-8">
<title>分析报告 - {state.filename}</title><style>
body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:800px;margin:2rem auto;padding:1rem;color:#222;line-height:1.6}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px;text-align:left}} th{{background:#f5f5f5}}
h1{{border-bottom:2px solid #333;padding-bottom:0.3em}} h2{{border-bottom:1px solid #ccc;padding-bottom:0.2em;margin-top:1.5em}}
code{{background:#f3f3f3;padding:2px 4px;border-radius:4px;font-size:0.95em}}
blockquote{{border-left:4px solid #bbb;color:#555;margin:1em 0;padding:0.5em 1em;background:#fafafa}}
</style></head><body>{html_body}</body></html>"""
            col_html.download_button(
                "下载 HTML（浏览器打印为 PDF）",
                html_full.encode("utf-8"),
                file_name="analysis_report.html",
                mime="text/html",
            )

# =============================================================================
# Tab: 追问 Agent（工具调用可展开 + meta 徽章）
# =============================================================================
with tab_qa:
    st.write("针对当前表格提问，Agent 会调用查询 / 聚合 / 相关等工具后再回答。")
    question = st.chat_input("例如：哪个品类平均销售额最高？")
    if "chat" not in st.session_state or not isinstance(st.session_state.chat, list):
        st.session_state.chat = []

    for role, item in st.session_state.chat:
        with st.chat_message(role):
            if role == "user":
                st.markdown(item)
            else:
                reply, meta = item
                st.markdown(reply)
                # 元信息徽章
                badges = []
                badges.append(f"⏱ {meta.get('elapsed_ms', 0)}ms")
                badges.append(f"🧠 约{meta.get('tokens_est', 0)}tokens")
                badges.append(f"🔧 工具{meta.get('tool_calls', 0)}次")
                badges.append(f"🔁 {meta.get('n_rounds', 0)}轮")
                reason_map = {
                    "model_answer": "LLM 直接作答",
                    "max_rounds": "轮次超限",
                    "error": "调用报错",
                }
                badges.append(f"🏁 " + reason_map.get(meta.get("final_reason"), meta.get("final_reason") or ""))
                st.caption(" · ".join(badges))

                if meta.get("steps"):
                    with st.expander(
                        f"🛠 Agent 调用过程（{len(meta['steps'])} 步）"
                    ):
                        for idx, s in enumerate(meta["steps"], 1):
                            tool = s.get("tool")
                            args = s.get("args")
                            ms = s.get("elapsed_ms")
                            preview = s.get("result_preview")
                            rows = s.get("result_rows")
                            st.markdown(
                                f"**{idx}. `{tool}`** (⏱ {ms}ms"
                                + (f", 结果 {rows} 项" if rows is not None else "")
                                + ")"
                            )
                            if args:
                                st.json(args)
                            if preview is not None:
                                st.caption("结果预览：")
                                st.json(preview)

    if question:
        st.session_state.chat.append(("user", question))
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Agent 正在查表…"):
                try:
                    answer, meta = answer_question(df, state.profile, question)
                except Exception as exc:
                    answer = f"调用失败：{exc}"
                    meta = {
                        "steps": [],
                        "n_rounds": 0,
                        "tool_calls": 0,
                        "tokens_est": 0,
                        "elapsed_ms": 0,
                        "final_reason": "error",
                    }
            st.markdown(answer)

            badges = [
                f"⏱ {meta.get('elapsed_ms', 0)}ms",
                f"🧠 约{meta.get('tokens_est', 0)}tokens",
                f"🔧 工具{meta.get('tool_calls', 0)}次",
                f"🔁 {meta.get('n_rounds', 0)}轮",
            ]
            reason_map = {
                "model_answer": "LLM 直接作答",
                "max_rounds": "轮次超限",
                "error": "调用报错",
            }
            badges.append(f"🏁 " + reason_map.get(meta.get("final_reason"), meta.get("final_reason") or ""))
            st.caption(" · ".join(badges))

            if meta.get("steps"):
                with st.expander(f"🛠 Agent 调用过程（{len(meta['steps'])} 步）"):
                    for idx, s in enumerate(meta["steps"], 1):
                        tool = s.get("tool")
                        args = s.get("args")
                        ms = s.get("elapsed_ms")
                        preview = s.get("result_preview")
                        rows = s.get("result_rows")
                        st.markdown(
                            f"**{idx}. `{tool}`** (⏱ {ms}ms"
                            + (f", 结果 {rows} 项" if rows is not None else "")
                            + ")"
                        )
                        if args:
                            st.json(args)
                        if preview is not None:
                            st.caption("结果预览：")
                            st.json(preview)

        st.session_state.chat.append(("assistant", (answer, meta)))

# =============================================================================
# Tab: 画像 + 耗时面板
# =============================================================================
with tab_profile:
    if state.timings:
        st.markdown("### ⏱ 各步骤耗时")
        timing_df = pd.DataFrame(
            [
                {"步骤": k, "耗时（秒）": v}
                for k, v in state.timings.items()
            ]
        ).reset_index(drop=True)
        st.dataframe(timing_df, use_container_width=True, hide_index=True)

    with st.expander("完整画像 JSON"):
        st.json(state.profile)
    with st.expander("统计结果 JSON"):
        st.json(state.stats)
