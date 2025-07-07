"""Embeddings generation helpers.

真正实现 `get_jina_embedding` 与 `get_jina_embeddings_batch`，后续将脱离 legacy_full。"""
from __future__ import annotations

import time
from typing import List, Optional

import requests

from python_src.utils.logger import get_logger
from python_src.config import JINA_API_URL, JINA_API_REQUEST_DELAY

logger = get_logger(__name__)

def get_jina_embedding(
    text: str,
    jina_api_key_to_use: str,
    jina_model_name_to_use: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> Optional[List[float]]:
    """调用 Jina API 获取单条文本嵌入。

    带有指数退避重试逻辑，任何错误都会记录到日志中而不会抛出到上层。
    若最终仍失败则返回 ``None``。"""
    if not jina_api_key_to_use:
        logger.error("错误：Jina API Key 未提供。")
        return None
    if not jina_model_name_to_use:
        logger.error("错误：Jina 模型名称未提供。")
        return None
    if not text.strip():
        logger.warning("警告：输入文本为空，跳过嵌入。")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jina_api_key_to_use}",
    }
    data = {"input": [text], "model": jina_model_name_to_use}

    delay = initial_delay
    for attempt in range(max_retries):
        try:
            time.sleep(JINA_API_REQUEST_DELAY)
            response = requests.post(
                JINA_API_URL,
                headers=headers,
                json=data,
                timeout=30,
            )
            response.raise_for_status()

            result = response.json()
            if (
                result.get("data")
                and len(result["data"]) > 0
                and result["data"][0].get("embedding")
            ):
                return result["data"][0]["embedding"]  # type: ignore[return-value]
            logger.error("错误：Jina API 响应格式不正确。响应: %s", result)
            return None  # 格式问题不重试
        except requests.exceptions.RequestException as exc:
            logger.error(
                "错误：调用 Jina API 失败 (尝试 %s/%s): %s", attempt + 1, max_retries, exc
            )
            if hasattr(exc, "response") and exc.response is not None:  # type: ignore[attr-defined]
                logger.error(
                    "响应状态码: %s, 响应内容: %.500s",
                    exc.response.status_code,  # type: ignore[attr-defined]
                    exc.response.text,  # type: ignore[attr-defined]
                )
                if 400 <= exc.response.status_code < 500:  # type: ignore[attr-defined]
                    return None  # 客户端错误无需重试
            time.sleep(delay)
            delay *= 2  # 指数退避
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("处理 Jina API 响应时发生未知错误: %s", exc)
            return None

    logger.error("错误：达到最大重试次数 %s 后，Jina API 调用仍然失败。", max_retries)
    return None


def get_jina_embeddings_batch(
    texts: List[str],
    jina_api_key_to_use: str,
    jina_model_name_to_use: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> List[Optional[List[float]]]:
    """批量获取多条文本嵌入，保持与 `get_jina_embedding` 一致的错误处理。"""
    if not texts:
        return []
    if not jina_api_key_to_use:
        logger.error("错误：Jina API Key 未提供。")
        return [None] * len(texts)
    if not jina_model_name_to_use:
        logger.error("错误：Jina 模型名称未提供。")
        return [None] * len(texts)

    valid_texts: List[str] = []
    text_indices: List[int] = []
    for idx, text in enumerate(texts):
        if text and text.strip():
            valid_texts.append(text)
            text_indices.append(idx)

    if not valid_texts:
        logger.warning("警告：所有输入文本均为空，跳过嵌入。")
        return [None] * len(texts)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jina_api_key_to_use}",
    }
    data = {"input": valid_texts, "model": jina_model_name_to_use}

    delay = initial_delay
    for attempt in range(max_retries):
        try:
            time.sleep(JINA_API_REQUEST_DELAY)
            response = requests.post(
                JINA_API_URL,
                headers=headers,
                json=data,
                timeout=60,
            )
            response.raise_for_status()

            result = response.json()
            if result.get("data") and len(result["data"]) == len(valid_texts):
                embeddings: List[Optional[List[float]]] = [None] * len(texts)
                for i, original_idx in enumerate(text_indices):
                    if i < len(result["data"]) and result["data"][i].get("embedding"):
                        embeddings[original_idx] = result["data"][i]["embedding"]  # type: ignore[index]
                return embeddings
            logger.error("错误：Jina API 批量响应格式不正确。响应: %s", result)
            return [None] * len(texts)
        except requests.exceptions.RequestException as exc:
            logger.error(
                "错误：批量调用 Jina API 失败 (尝试 %s/%s): %s", attempt + 1, max_retries, exc
            )
            if hasattr(exc, "response") and exc.response is not None:  # type: ignore[attr-defined]
                logger.error(
                    "响应状态码: %s, 响应内容: %.500s",
                    exc.response.status_code,  # type: ignore[attr-defined]
                    exc.response.text,  # type: ignore[attr-defined]
                )
                if 400 <= exc.response.status_code < 500:  # type: ignore[attr-defined]
                    return [None] * len(texts)
            time.sleep(delay)
            delay *= 2
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("处理批量 Jina API 响应时发生未知错误: %s", exc)
            return [None] * len(texts)

    logger.error("错误：达到最大重试次数 %s 后，批量 Jina API 调用仍然失败。", max_retries)
    return [None] * len(texts)


__all__ = ["get_jina_embedding", "get_jina_embeddings_batch"]
