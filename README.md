# 智能自动数据分析 Agent

上传 CSV / Excel，自动完成**数据画像 → 统计 → 图表 → 文字报告**，再用带工具调用的问答 Agent 用自然语言追问表格。

## 主要能力

- 🧱 **确定性流水线 + LLM 双保险**：画像/统计/图表完全可复现；洞察和报告由 LLM 生成，失败时自动退回规则兜底，**无 API Key 也能跑**
- ⏳ **实时进度条**：按「画像 15% → 统计 25% → 图表 10% → 洞察 25% → 报告 25%」展示当前步骤和每步耗时
- ⏱ **流水线耗时统计**：画像 Tab 顶部以表格展示 profile/stats/charts/insights/report/total 各步骤秒数
- 🧮 **画像/统计结果缓存**：同一数据集反复分析自动命中缓存（按 df hash，TTL 1 小时）
- 📊 **7 种图表自动推荐**（line / bar / scatter / histogram / heatmap / box / pie）
  - 每张图下方带 **reason 小字可解释性说明**（为什么选这张）
  - 时间折线自动按天聚合；散点/折线在大数据时自动**下采样**（>2 万行）避免浏览器卡顿
  - 箱线图 Top10 分类裁剪；饼图 Top8 + Others 合并
  - 相关性热力图**显示数值标注**，一眼看出强弱
  - scatter/heatmap 仅在 ≥2 个数值列时推荐，杜绝空图
- 📑 **报告双格式导出**：Markdown + 样式化 HTML（浏览器打印即 PDF）；缺 `markdown` 包时**不报错**，提示安装命令
- 🔍 **大数据友好预览**：>5 万行时自动分页（每页 100 条），并展示「估算内存占用」指标
- 🔄 **切换数据源自动清状态**：上传新文件/切换样例按钮时，旧分析结果和聊天记录自动清空，防串数据
- 🤖 **问答 Agent（完整可视化）**：
  - 调用 `query_rows / aggregate / value_counts / correlation` 前会校验**列名存在性 / agg 白名单 / 列类型 / limit 上下限**
  - 对 LLM 调用做 **3 次指数退避重试**（超时/限流/空响应/服务端错误）
  - 工具返回结果字符数 >8K 自动**瘦身**（附 `_truncated` 标记 + 总行数），避免撑爆上下文
  - 每条回复右上角显示徽章：`⏱ 耗时ms · 🧠 约X tokens · 🔧工具Y次 · 🔁 Z轮 · 🏁 停止原因`
  - 回复下方带可展开器：逐步展示「用了哪个工具、入参 JSON、结果预览、每条工具耗时」
  - 轮次超限时不再只有一句话，附带**3 条拆分建议**（聚合 → 筛选 → 相关）
- ✅ **一键环境自检**：根目录 `python check_env.py` 5 秒输出环境状态（Python 路径、依赖版本、.env 是否存在、样例数据是否可读、示例 import 是否成功）
- 🔐 **安全**：`.env.example` 仅为占位符模板，杜绝真实密钥随示例文件泄露

## 设计思路

自动分析不适合纯 ReAct 乱试：画像和统计应可复现。本项目拆成两层：

1. **流水线（确定性）**：画像 → 描述统计 / 相关 / 分组 / 异常值 → 图表规格 → LLM 写洞察和报告
2. **问答 Agent（工具调用）**：对当前表执行筛选、聚合、频次、相关，再组织中文答案

```
用户数据
   │
   ▼
┌─────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐
│ Profiler│ → │ Analyst │ → │Visualizer│ → │ Insights│ → │ Reporter│
└─────────┘   └─────────┘   └──────────┘   └─────────┘   └─────────┘
        ⏱            ⏱            ⏱            ⏱            ⏱
 (timings 记录每步耗时 + 缓存 profile/stats 加速)
                                                          │
                                                          ▼
          Streamlit：进度条 + 报告/图表/画像 Tab / timings面板
                                                          │
                                                          ▼
      QA Agent + 4 个 pandas 工具（列校验 + 结果截断 + LLM重试 + 调用可视化）
```

无 API Key 时，流水线仍会产出画像、统计和图表；文字洞察退回规则兜底。

## 快速开始

> ⚡ 启动前建议先做**一键环境自检**：`python check_env.py`（5 秒出结果，Windows 多 pip 场景最容易定位问题）

### 1. 建虚拟环境并安装依赖

Windows PowerShell（**统一用 `python -m pip`，避免 pip 和 python 不是同一个解释器**）：

```powershell
cd agent项目
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 配置 API Key

> ⚠️ 安全提示：`.env.example` 只是模板，里面 **`sk-your-api-key-here` 是占位符**，请不要直接修改它。

```powershell
copy .env.example .env
```

在 `.env` 中填写兼容 OpenAI 的接口。**`OPENAI_BASE_URL` 必须与 Key 所属服务商匹配，否则会超时或 401**（常见错误：阿里云 `sk-ws-` 开头的 Key 却配了 `api.openai.com` → 请求超时）。

```bash
# 例 1：阿里云百炼（Key 以 sk-ws- 开头，国内站）
OPENAI_API_KEY=sk-ws-xxx
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=deepseek-v4-flash

# 例 2：DeepSeek 官方
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat

# 例 3：OpenAI 官方
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

也支持 Ollama（`http://localhost:11434/v1`）/ 通义国际站 / 硅基流动 等 OpenAI 兼容接口。可选环境变量：`OPENAI_TIMEOUT`（单次超时秒数，默认 60）、`OPENAI_MAX_RETRIES`（重试次数，默认 3）。

### 3. 启动

```bash
streamlit run app.py
```

✅ **成功标志**：浏览器打开后，左侧勾选「内置样例」→ 点开始分析 → 看到**进度条走完** → 图表 Tab 出现**最多 6 张图**（含箱线图 + 饼图 + 热力图标注）→ 报告 Tab 有 MD 和 HTML 两个下载按钮。

## 5 个界面 Tab

| Tab | 内容 |
| --- | --- |
| 关键发现 | LLM 生成的 3~8 条洞察（失败时显示规则兜底）+ IQR 异常值计数 |
| 图表 | 最多 6 张自动推荐 Plotly 图（line/bar/scatter/histogram/box/pie/heatmap），每张下方带 `💡 reason` 说明 |
| 报告 | LLM 撰写的 5 段结构 Markdown 报告，支持 **MD / HTML** 下载；缺 `markdown` 包时不报错，给出安装命令 |
| 追问 Agent | 自然语言对话；每条回复含**徽章元信息**（耗时/token/工具次数/轮次/停止原因），下方带**🛠 Agent 调用过程**可展开器逐步展示；轮次超限附 3 条拆分建议 |
| 数据画像 | **顶部表格展示各步骤耗时**；下方折叠面板查看完整画像 JSON 和统计结果 JSON |

## 一键环境自检脚本（Windows 多 Python/多 pip 必备）

根目录执行：

```bash
python check_env.py
```

5 秒内输出：

| 检查项 | 示例 |
|---|---|
| 🐍 Python 解释器路径 | `.venv\Scripts\python.exe` |
| 📦 已装依赖版本 | pandas 2.2.3 / numpy 1.26.4 / plotly / streamlit / openai / dotenv / openpyxl / markdown |
| 📄 `.env` 是否存在 + API Key 是否空 | ✅ `.env` 存在且已配置密钥 / ❌ `.env` 不存在（运行 copy .env.example .env） |
| 📂 样例 CSV 是否可读 + 行列数 | ✅ data/sample_sales.csv：1000 行 × 10 列 |
| 🧪 示例 import 能否成功 | ✅ `import src.config / src.agents / src.tools` 全部 OK |

## 目录

| 路径 | 作用 |
| --- | --- |
| `check_env.py` | ⭐ 一键环境自检脚本（5 秒定位依赖/Key/样例问题） |
| `app.py` | Streamlit 界面：缓存 + 大数据分页 + 进度条 + timings + QA可视化 + Markdown降级 + 报告双导出 |
| `src/pipeline.py` | 流水线编排：5 步权重、`progress_callback` 回调、每步 `timings`、LLM 失败兜底 |
| `src/config.py` | Settings dataclass，从 `.env` 加载 3 个 LLM 配置 + 预览/分类基数阈值 |
| `src/llm.py` | OpenAI 客户端 + `chat()`（JSON 模式 / **3 次指数退避重试** / 空响应重试） |
| `src/state.py` | `AnalysisState`：新增 `timings` 字段（profile/stats/charts/insights/report/total） |
| `src/charts.py` | 7 种图表渲染器 + 大数据下采样 + 时间轴按天聚合 + 热力图标注 |
| `src/agents/profiler.py` | 画像：类型/缺失/基数/numeric 描述统计/categorical Top8（**纯规则，稳定可复现**） |
| `src/agents/analyst.py` | 统计：describe / 相关矩阵 / IQR 异常值 / 3×3 分组汇总 |
| `src/agents/visualizer.py` | 图表规划：最多 6 张 + **跳过空图条件**（scatter/heatmap 仅 ≥2 numeric 才推荐）+ **每张附 reason** |
| `src/agents/insights.py` | LLM JSON 模式生成洞察（`_slim_profile/_slim_stats` 减小 token） |
| `src/agents/reporter.py` | LLM 生成 5 段固定结构 Markdown 报告 |
| `src/agents/qa.py` | ReAct 问答 Agent：返回 `(answer, meta)`，元信息含**所有工具调用步骤**+耗时/轮次超限拆分建议 |
| `src/tools/pandas_tools.py` | 4 个查表工具 + **列名/类型/agg 白名单校验** + **>8K 字符结果自动瘦身** |
| `src/agents/__init__.py` | 导出 6 个 Agent 公共函数 |
| `src/tools/__init__.py` | 导出 `TOOLS` + `run_tool` |
| `data/sample_sales.csv` | 销售样例：10 列（订单号/日期/地区/品类/产品/数量/单价/折扣/销售额/是否退货）含少量缺失 |

## 依赖说明（`requirements.txt`）

| 包 | 用途 | 最低版本 |
| --- | --- | --- |
| `pandas` / `numpy` | 数据处理与统计 | 2.2 / 1.26 |
| `plotly` | 7 种交互图表（散点 opacity=0.6 优化重叠显示） | 5.24 |
| `streamlit` | 页面与交互组件 | 1.40 |
| `openai` | LLM 聊天与工具调用（兼容其他 OpenAI 协议服务） | 1.50 |
| `python-dotenv` | `.env` 环境变量加载 | 1.0 |
| `openpyxl` | Excel（xlsx/xls）读取 | 3.1 |
| `pydantic` | 后续可扩展结构化输出 | 2.9 |
| `markdown` | 报告 → HTML 渲染（浏览器 Ctrl+P 直接生成 PDF） | 3.5 |

## QA Agent 可调用的 4 个工具

| 工具 | 作用 | 关键参数校验 | 结果长度保护 |
| --- | --- | --- | --- |
| `query_rows` | 按 `condition`（pandas query 语法）筛选行，返回前 N 行 | 列名存在性 / query 语法捕获 / **limit clamp [1,200]** | `_truncate()` + 总行数标记 |
| `aggregate` | 按 `group_by` 分组后对 `value` 做 `agg` 聚合 | agg ∈ {mean,sum,count,median,min,max,std}；非数值列提前报错 / **limit clamp [1,500]** | `_truncate()` + 总行数标记 |
| `value_counts` | 单列频次统计 | 列名存在性 / **limit clamp [1,200]** | `_truncate()` + 总行数标记 |
| `correlation` | 数值列相关系数 | 至少 2 个数值列 / 列名存在性 | `_truncate()` + 矩阵元素总数 |

## 后续可扩展

- 用 LangGraph 把流水线改成带状态回退的图（任一子步骤失败可跳过重试）
- 增加清洗 Agent（缺失值策略、盖帽法处理异常、类型推断增强：百分号/货币字符串→浮点、是/否→bool）
- 接入数据库 / 多表 Join（新增 SQL 生成工具 + 行数限制 + SQL-in-list 保护）
- 把报告导出为真正的 PDF（`weasyprint` 或 `pdfkit + wkhtmltopdf`）
- 定时跑批 + 邮件推送（保存「数据集路径 + 分析目标 + 收件人」，`APScheduler` 调度，`smtplib` 发送）
- QA Agent 工具调用结果加 mini-chart（返回 aggregate 结果时 UI 同时渲染一张小条形图）
- 画像/统计缓存持久化：从 Streamlit 内存缓存升级到 SQLite 磁盘缓存，跨会话命中
