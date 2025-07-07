"""AI provider HTTP helpers (batch relevance API 调用)."""
from __future__ import annotations

import json
import time
import uuid
import os
from typing import Dict, List

import requests

from python_src.config import AI_API_REQUEST_DELAY_SECONDS
from python_src.utils.logger import get_logger
from python_src.utils.db import get_db_connection
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
    save_responses: bool = False,
    ai_scores_db_path: str = None,
    prompt_type: str = "default",
) -> List[Dict]:
    """根据 provider 调用批量评分 API，返回解析后的结果列表。
    
    Args:
        save_responses: 是否保存API请求和响应内容到数据库
        ai_scores_db_path: AI评分数据库路径（当save_responses=True时需要）
        prompt_type: 提示词类型（"default"或"custom"）
    """
    if not prompt_pairs:
        logger.info("无候选对需要评分。")
        return []

    logger.info(f"开始进行AI批量评分: {len(prompt_pairs)}对内容, 提供商: {ai_provider}, 模型: {model_name}")
    
    if isinstance(data, list):
        logger.info(f"API请求格式: 批量请求列表, 包含 {len(data)} 个请求项")
    else:
        logger.info("API请求格式: 单个请求对象")

    delay = initial_delay
    results: List[Dict] = []
    
    # 为本批次生成唯一ID
    batch_id = str(uuid.uuid4())
    logger.info(f"批次ID: {batch_id}")

    try:
        # 所有提供商现在都使用单个批量请求。
        # 对于标准提供商, `build_ai_batch_request` 返回包含一个请求项的列表。
        # 对于自定义提供商，它返回一个请求字典。
        req_data = data[0] if isinstance(data, list) and data else data

        if not req_data:
            logger.warning("未能构建请求数据，跳过AI调用。")
            return []

        for attempt in range(max_retries):
            try:
                time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                logger.debug("正在调用 %s (%s/%s)…", ai_provider, attempt + 1, max_retries)

                # gemini 需要拼接 key 到 URL
                if ai_provider == "gemini":
                    full_url = f"{api_url}/{model_name}:generateContent?key={api_key}"
                    response = requests.post(full_url, headers=headers, json=req_data, timeout=60)
                else:
                    response = requests.post(api_url, headers=headers, json=req_data, timeout=60)
                
                response.raise_for_status()
                
                response_json = response.json()
                logger.info(f"成功收到API响应: {len(str(response_json))}字节")

                # 我们现在根据所有的 prompt_pairs 来解析整个批量响应
                # Deepseek API 兼容 OpenAI 的响应格式
                parsed = parse_ai_batch_response(
                    "openai" if ai_provider == "deepseek" else ai_provider,
                    response_json,
                    prompt_pairs,
                )
                results.extend(parsed)
                
                logger.info(f"解析结果: {len(parsed)} 条评分")
                for result in parsed:
                    score = result.get('ai_score', 'N/A')
                    src = os.path.basename(result.get('source_path', '未知'))
                    tgt = os.path.basename(result.get('target_path', '未知'))
                    logger.info(f"评分: {score} - {src} ↔ {tgt}")
                
                # 如果需要，保存请求和响应到数据库
                if save_responses and ai_scores_db_path:
                    try:
                        save_api_response(
                            ai_scores_db_path,
                            batch_id,
                            ai_provider,
                            model_name,
                            json.dumps(req_data, ensure_ascii=False),
                            json.dumps(response_json, ensure_ascii=False),
                            prompt_type,
                        )
                        logger.info(f"已保存 {ai_provider} API响应到数据库")
                    except Exception as save_exc:
                        logger.error(f"保存API响应到数据库失败: {save_exc}")
                
                break  # 成功，跳出重试循环
                
            except requests.exceptions.RequestException as exc:
                logger.error("调用 %s 失败: %s", ai_provider, exc)
                if attempt == max_retries - 1:
                    logger.error("调用 %s 最终失败。", ai_provider)
                    return [] # 在最终失败时返回空列表
                
                delay *= 2
                time.sleep(delay)
                
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("调用 %s API 发生未知错误: %s", ai_provider, exc)

    logger.info(f"批量评分完成，共返回 {len(results)} 条结果")
    return results


def save_api_response(
    db_path: str,
    batch_id: str,
    ai_provider: str,
    model_name: str,
    request_content: str,
    response_content: str,
    prompt_type: str,
) -> None:
    """保存API请求和响应到数据库
    
    Args:
        db_path: 数据库路径
        batch_id: 批次ID
        ai_provider: AI提供商名称
        model_name: 模型名称
        request_content: 请求内容的JSON字符串
        response_content: 响应内容的JSON字符串
        prompt_type: 提示词类型（"default"或"custom"）
    """
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    
    try:
        cur.execute(
            """
            INSERT INTO ai_responses (
                batch_id, ai_provider, model_name, request_content, response_content, prompt_type
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (batch_id, ai_provider, model_name, request_content, response_content, prompt_type)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"保存AI响应到数据库失败: {e}")
        conn.rollback()
    finally:
        conn.close()


__all__ = ["call_ai_api_batch_for_relevance", "save_api_response"]
