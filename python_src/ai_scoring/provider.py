"""AI provider HTTP helpers (batch relevance API 调用)."""
from __future__ import annotations

import time
from typing import Dict, List

import requests

from python_src.config import AI_API_REQUEST_DELAY_SECONDS
from python_src.utils.logger import get_logger
from python_src.ai_scoring.scorer import parse_ai_batch_response

logger = get_logger(__name__)


def call_ai_api_batch_for_relevance(
    ai_provider: str,
    model_name: str,
    api_key: str,
    api_url: str,
    prompt_pairs: List[Dict],
    headers: Dict,
    data: List | Dict,
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> List[Dict]:
    """根据 provider 调用批量评分 API，返回解析后的结果列表。"""
    if not prompt_pairs:
        logger.info("无候选对需要评分。")
        return []

    delay = initial_delay
    results: List[Dict] = []

    try:
        if ai_provider in {"deepseek", "openai", "claude", "gemini"}:
            # 这些 provider 均逐对发送请求
            for idx, req_data in enumerate(data if isinstance(data, list) else [data]):
                for attempt in range(max_retries):
                    try:
                        time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                        logger.debug("正在调用 %s (%s/%s)…", ai_provider, attempt + 1, max_retries)

                        # gemini 需要拼接 key 到 URL
                        if ai_provider == "gemini":
                            full_url = f"{api_url}/{model_name}:generateContent?key={api_key}"
                            response = requests.post(full_url, headers=headers, json=req_data, timeout=30)
                        else:
                            response = requests.post(api_url, headers=headers, json=req_data, timeout=30)
                        response.raise_for_status()

                        parsed = parse_ai_batch_response(
                            "openai" if ai_provider == "deepseek" else ai_provider,
                            response.json(),
                            [prompt_pairs[idx]],
                        )
                        results.extend(parsed)
                        break  # success
                    except requests.exceptions.RequestException as exc:
                        logger.error("调用 %s 失败: %s", ai_provider, exc)
                        if attempt == max_retries - 1:
                            pair = prompt_pairs[idx]
                            results.append(
                                {
                                    "source_path": pair["source_path"],
                                    "target_path": pair["target_path"],
                                    "ai_score": 0,
                                    "error": str(exc),
                                    "jina_similarity": pair.get("jina_similarity", 0),
                                }
                            )
                        delay *= 2
                        time.sleep(delay)
        else:  # custom provider: assume accepts batch request
            for attempt in range(max_retries):
                try:
                    time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                    response = requests.post(api_url, headers=headers, json=data, timeout=60)
                    response.raise_for_status()
                    results = parse_ai_batch_response(ai_provider, response.json(), prompt_pairs)
                    break
                except Exception as exc:  # pylint: disable=broad-except
                    if attempt == max_retries - 1:
                        logger.error("调用自定义 AI 失败: %s", exc)
                        return []
                    delay *= 2
                    time.sleep(delay)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("调用 %s API 发生未知错误: %s", ai_provider, exc)

    return results


__all__ = ["call_ai_api_batch_for_relevance"]
