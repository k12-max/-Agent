from __future__ import annotations

import time

from openai import OpenAI
from openai import APIError, APITimeoutError, RateLimitError

from src.config import settings

_MAX_RETRIES = settings.max_retries
_RETRY_BACKOFF = 1.5  # 秒，指数退避基数


def get_client() -> OpenAI:
    if not settings.api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，请复制 .env.example 为 .env 后填写密钥。")
    # max_retries=0：禁用 SDK 内部重试，统一由 chat() 的业务层重试控制，
    # 避免 SDK 3 次 × 业务 3 次 = 9 次叠加导致超时场景下卡死十几分钟
    return OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
        max_retries=0,
    )


def chat(messages: list[dict], temperature: float = 0.2, json_mode: bool = False) -> str:
    """带重试的 LLM 调用，处理超时/限流/服务端错误/空响应。"""
    kwargs: dict = {
        "model": settings.model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    client = get_client()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            content = (response.choices[0].message.content or "").strip()
            if not content and attempt < _MAX_RETRIES:
                # 空结果也重试一次
                raise APIError(message="模型返回空内容", request=None, body=None)
            return content
        except (APITimeoutError, RateLimitError, APIError) as exc:
            last_exc = exc
            if attempt == _MAX_RETRIES:
                break
            wait = _RETRY_BACKOFF ** attempt
            time.sleep(wait)

    raise RuntimeError(
        f"LLM 调用失败（{_MAX_RETRIES} 次重试）：{last_exc}。"
        f"请检查 OPENAI_BASE_URL（当前：{settings.base_url}）是否与服务商 Key 匹配、"
        f"以及网络连通性；也可通过 OPENAI_TIMEOUT 环境变量调大单次超时（当前 {settings.timeout}s）。"
    )
