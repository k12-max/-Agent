from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # 单次请求超时（秒）。推理类模型较慢可调大；网络不通时快速失败靠它
    timeout: float = float(os.getenv("OPENAI_TIMEOUT", "60"))
    # 业务层重试次数（SDK 内部重试已禁用，统一在这里控制）
    max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
    max_preview_rows: int = 8
    max_categorical_levels: int = 20


settings = Settings()
