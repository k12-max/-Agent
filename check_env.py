r"""一键环境自检脚本：5 秒输出 Python/pip/依赖/.env/样例/import 六大类健康状态。

用法（Windows PowerShell 推荐，先激活虚拟环境再跑）：
    .venv\Scripts\Activate.ps1
    python check_env.py
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
NC = "\033[0m"

ALL_CHECKS_PASS = True
# 警告计数（仅展示，不影响最终通过状态）
WARN_COUNT = 0


def _pass(msg: str) -> None:
    print(f"{GREEN}✅ {msg}{NC}")


def _warn(msg: str) -> None:
    global WARN_COUNT
    WARN_COUNT += 1
    print(f"{YELLOW}⚠️  {msg}{NC}")


def _fail(msg: str, fix: str = "") -> None:
    global ALL_CHECKS_PASS
    ALL_CHECKS_PASS = False
    print(f"{RED}❌ {msg}{NC}")
    if fix:
        print(f"   → 修复：{YELLOW}{fix}{NC}")


# ---------------------------------------------------------------------------
# 1. Python 解释器 & 版本
# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
print(" 1/6 · Python 环境")
print("=" * 72)
py_path = sys.executable
py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
_pass(f"解释器路径：{py_path}")
_pass(f"版本：Python {py_ver}")
if sys.version_info < (3, 10):
    _warn(
        f"Python 版本低于 3.10（当前 {py_ver}），部分语法（X|Y 联合类型）可能不兼容。",
        "建议升级到 Python 3.10+。",
    )

# pip 是否是同一个解释器
import site  # noqa: E402

site_packages = site.getsitepackages() or [site.getusersitepackages()]
_pass(f"site-packages：{site_packages[0]}")


# ---------------------------------------------------------------------------
# 2. 依赖安装完整性 & 版本
# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
print(" 2/6 · 依赖（requirements.txt）")
print("=" * 72)

EXPECTED = [
    ("pandas", "2.2.0", "pip list | Select-String pandas"),
    ("numpy", "1.26.0", None),
    ("plotly", "5.24.0", None),
    ("streamlit", "1.40.0", None),
    ("openai", "1.50.0", None),
    ("dotenv", "1.0.1", "python -m pip install python-dotenv>=1.0.1   # pip 包名是 python-dotenv"),
    ("openpyxl", "3.1.5", None),
    ("pydantic", "2.9.0", None),
    ("markdown", "3.5", "python -m pip install markdown>=3.5           # 报告 HTML 导出需要"),
]

installed = {}
for pkg_mod, min_ver, fix_cmd in EXPECTED:
    try:
        mod = importlib.import_module(pkg_mod)
        ver = getattr(mod, "__version__", None)
        if not ver and pkg_mod == "dotenv":
            from importlib.metadata import version as _v
            ver = _v("python-dotenv")
        installed[pkg_mod] = ver
        # 粗略版本比对（字符串分段）
        ok = True
        if ver and min_ver:
            cur = [int(x) for x in str(ver).split(".") if x.isdigit()]
            mn = [int(x) for x in min_ver.split(".") if x.isdigit()]
            for a, b in zip(cur, mn):
                if a > b:
                    break
                if a < b:
                    ok = False
                    break
        status = (
            _pass(f"{pkg_mod:12s} {ver or '(unknown)':<12s} ≥ {min_ver}")
            if ok
            else _warn(f"{pkg_mod:12s} {ver or '(unknown)':<12s} 低于 {min_ver}")
        )
    except Exception as exc:
        installed[pkg_mod] = None
        _fail(
            f"{pkg_mod} 未安装：{exc}",
            fix_cmd or f"python -m pip install {pkg_mod}>={min_ver}",
        )


# ---------------------------------------------------------------------------
# 3. .env 文件 & LLM 配置
# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
print(" 3/6 · LLM 配置（.env）")
print("=" * 72)

env_path = ROOT / ".env"
env_ex_path = ROOT / ".env.example"
if not env_ex_path.exists():
    _warn(".env.example 不存在，项目模板可能不完整。")
else:
    _pass(f".env.example 存在：{env_ex_path}")

if not env_path.exists():
    _fail(
        ".env 不存在，LLM 功能将无法启用（流水线仍可用规则兜底）。",
        "Windows:  copy .env.example .env   然后在 .env 中填入真实 API Key。",
    )
else:
    _pass(f".env 存在：{env_path}")
    try:
        from dotenv import dotenv_values  # type: ignore

        env_dict = dotenv_values(env_path)
    except Exception:
        # dotenv 包可能缺，手动 fallback 解析简单 key=value
        env_dict = {}
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_dict[k.strip()] = v.strip().strip('"').strip("'")

    api_key = env_dict.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    base_url = env_dict.get("OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL", ""))
    model = env_dict.get("OPENAI_MODEL", os.getenv("OPENAI_MODEL", ""))

    if not api_key:
        _fail("OPENAI_API_KEY 为空，LLM 将无法调用。", "在 .env 中填入兼容 OpenAI 的真实密钥。")
    elif api_key.startswith("sk-your-"):
        _fail("OPENAI_API_KEY 仍是占位符（sk-your-api-key-here）。", "将 .env 中密钥替换为真实值。")
    else:
        mask = api_key[:6] + "****" + api_key[-4:]
        _pass(f"OPENAI_API_KEY 已配置：{mask}")
    _pass(f"OPENAI_BASE_URL = {base_url or '(默认) https://api.openai.com/v1'}")
    _pass(f"OPENAI_MODEL   = {model or '(默认) gpt-4o-mini'}")


# ---------------------------------------------------------------------------
# 4. 样例 CSV 可读性
# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
print(" 4/6 · 样例数据（data/sample_sales.csv）")
print("=" * 72)

sample_path = ROOT / "data" / "sample_sales.csv"
if not sample_path.exists():
    _fail(f"样例文件不存在：{sample_path}", "检查 data 目录下的 sample_sales.csv 是否被误删。")
else:
    try:
        import pandas as pd  # noqa: E402

        df = pd.read_csv(sample_path)
        _pass(f"读取成功：{sample_path.name}（{len(df):,} 行 × {df.shape[1]} 列）")
        _pass(f"列：{list(df.columns)}")
        if df.isna().sum().sum() > 0:
            _warn(f"数据含 {int(df.isna().sum().sum()):,} 个缺失单元格（样例正常）。")
    except Exception as exc:
        _fail(f"读取失败：{exc}", "确认 pandas/openpyxl 已正确安装（见第 2/6 步）。")


# ---------------------------------------------------------------------------
# 5. 示例 import 链路（是否能真正 import 所有 src 包）
# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
print(" 5/6 · 代码可导入性检查")
print("=" * 72)

IMPORT_TARGETS = [
    ("src.config", ""),
    ("src.state", ""),
    ("src.llm", ""),
    ("src.pipeline", ""),
    ("src.charts", ""),
    ("src.agents.profiler", "src 包路径"),
    ("src.agents.analyst", ""),
    ("src.agents.visualizer", ""),
    ("src.agents.insights", "（首次 import 会同时校验 src.llm）"),
    ("src.agents.reporter", ""),
    ("src.agents.qa", "（首次 import 会同时校验 src.tools / openai 依赖）"),
    ("src.tools.pandas_tools", ""),
    ("src.agents", "__init__ 公共导出"),
    ("src.tools", "__init__ 公共导出"),
]

# 保证 ROOT 在 sys.path 里，便于 import src.xxx
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for target, note in IMPORT_TARGETS:
    try:
        importlib.import_module(target)
        _pass(f"{target:30s} OK" + (f"  （{note}）" if note else ""))
    except Exception as exc:
        _fail(
            f"{target:30s} 失败：{exc!r}",
            "请先执行第 1/6 步（确认 python 路径对） + 第 2/6 步（缺依赖补上）。",
        )


# ---------------------------------------------------------------------------
# 6. 启动指南
# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
print(" 6/6 · 启动速查")
print("=" * 72)

print(
    f"""
  ① 安装缺失依赖（如上面有 ❌）：
     {GREEN}python -m pip install -r requirements.txt{NC}

  ② 启动 Streamlit：
     {GREEN}streamlit run app.py{NC}

  ③ 成功标志：
     浏览器打开后，左侧勾选「内置样例」→ 点「开始自动分析」→
     看到 5 段进度条走完，图表 Tab 出现 5~6 张图。
"""
)

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
print("=" * 72)
if ALL_CHECKS_PASS:
    tail = "" if WARN_COUNT == 0 else f"（另有 {WARN_COUNT} 条黄色提示，注意下即可）"
    print(f"{GREEN}🎉 环境自检全部通过！可以直接 streamlit run app.py 启动。{NC} {tail}")
    sys.exit(0)
else:
    print(
        f"{RED}❌ 环境未通过。上面列出的红色 ❌ 必须修复后才能稳定使用；"
        f"按每项的「→ 修复：」处理后，再运行一次本脚本确认。{NC}"
    )
    if WARN_COUNT:
        print(f"{YELLOW}   （另外有 {WARN_COUNT} 条黄色 ⚠️ 提示为非致命提醒。）{NC}")
    sys.exit(1)
