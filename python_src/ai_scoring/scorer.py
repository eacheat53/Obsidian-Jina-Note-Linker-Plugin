"""AI 批量评分请求与响应解析工具。"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from python_src.config import DEFAULT_AI_CONFIGS
from python_src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 构建批量请求
# ---------------------------------------------------------------------------

def build_ai_batch_request(
    ai_provider: str,
    model_name: str,
    api_key: str,
    prompt_pairs: List[Dict],
    max_content_length: int,
) -> Tuple[List | Dict, Dict, str]:
    """根据 provider 构造 headers / body / url。

    返回 (data, headers, api_url)。"""
    scoring_guide = """
    作为笔记关联性评分专家，请评估以下多对内容的关联度。这些内容可能包括知识笔记、诗歌创作、灵感片段、散文、情感记录等多样化形式。对每对内容给出0-10的整数评分，基于以下全面标准：

    【评分标准：适用于多元内容】
    10分 - 深度关联：
      • 内容间存在明显的思想、情感或意象共鸣
      • 一篇内容直接启发、延伸或回应另一篇
      • 两篇形成完整的表达整体，共同构建一个更丰富的意境或思想
      • 同时阅读会产生"啊哈"时刻，带来新的领悟

    8-9分 - 强烈关联：
      • 共享核心情感、意象或主题
      • 表达相似的思想但通过不同角度或形式
      • 创作背景或灵感来源紧密相连
      • 一篇可以深化对另一篇的理解和欣赏

    6-7分 - 明显关联：
      • 存在清晰的主题或情绪连接
      • 使用相似的意象或表达方式
      • 关联点足够丰富，能激发新的思考
      • 并置阅读能够丰富整体体验

    4-5分 - 中等关联：
      • 有一些共通元素，但整体走向不同
      • 某些片段或意象存在呼应，但不是主体
      • 关联更加微妙或需要一定解读
      • 链接可能对部分读者有启发价值

    2-3分 - 轻微关联：
      • 关联仅限于表面术语或零星概念
      • 主题、风格或情感基调大不相同
      • 联系需要刻意寻找才能发现
      • 链接价值有限，大多数读者难以察觉关联

    0-1分 - 几乎无关联：
      • 内容、主题、意象几乎完全不同
      • 无法找到明显的思想或情感连接
      • 链接不会为读者理解任一内容增添价值
      • 并置阅读无法产生有意义的关联或启发
    """.strip()

    if ai_provider == "deepseek":
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        api_url = DEFAULT_AI_CONFIGS["deepseek"]["api_url"]
        requests_array: List[Dict] = []
        for pair in prompt_pairs:
            requests_array.append(
                {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "你是善于发现内容关联的评分专家。"},
                        {
                            "role": "user",
                            "content": f"评估这对内容的关联度，给出0到10的整数评分。\n\n内容一：{pair['source_name']}\n{pair['source_content'][:max_content_length]}\n\n内容二：{pair['target_name']}\n{pair['target_content'][:max_content_length]}\n\n{scoring_guide}\n\n请只回复一个0-10的整数评分，不要有任何解释或额外文字。",
                        },
                    ],
                    "max_tokens": 20,
                    "temperature": 0,
                    "top_p": 0.8,
                }
            )
        return requests_array, headers, api_url

    if ai_provider == "openai":
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        api_url = DEFAULT_AI_CONFIGS["openai"]["api_url"]
        requests_array = []
        for pair in prompt_pairs:
            requests_array.append(
                {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "你是善于发现内容关联的评分专家。"},
                        {
                            "role": "user",
                            "content": f"评估以下这对内容的关联度，给出0到10的整数评分。\n\n内容一：{pair['source_name']}\n{pair['source_content'][:max_content_length]}\n\n内容二：{pair['target_name']}\n{pair['target_content'][:max_content_length]}\n\n{scoring_guide}\n\n请只回复一个0-10的整数评分，不要有任何解释或额外文字。",
                        },
                    ],
                    "max_tokens": 10,
                    "temperature": 0,
                }
            )
        return requests_array, headers, api_url

    if ai_provider == "claude":
        headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        api_url = DEFAULT_AI_CONFIGS["claude"]["api_url"]
        requests_array = []
        for pair in prompt_pairs:
            requests_array.append(
                {
                    "model": model_name,
                    "max_tokens": 10,
                    "system": "你是善于发现内容关联的评分专家。请只输出评分数字，不要有任何解释或额外文字。",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"评估以下这对内容的关联度，给出0到10的整数评分。\n\n内容一：{pair['source_name']}\n{pair['source_content'][:max_content_length]}\n\n内容二：{pair['target_name']}\n{pair['target_content'][:max_content_length]}\n\n{scoring_guide}\n\n请只回复一个0-10的整数评分，不要有任何解释或额外文字。",
                        }
                    ],
                    "temperature": 0,
                }
            )
        return requests_array, headers, api_url

    if ai_provider == "gemini":
        headers = {"Content-Type": "application/json"}
        api_url_root = DEFAULT_AI_CONFIGS["gemini"]["api_url"]
        requests_array = []
        for pair in prompt_pairs:
            requests_array.append(
                {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": f"作为善于发现内容关联的评分专家，请评估以下这对内容的关联度，给出0到10的整数评分。\n\n内容一：{pair['source_name']}\n{pair['source_content'][:max_content_length]}\n\n内容二：{pair['target_name']}\n{pair['target_content'][:max_content_length]}\n\n{scoring_guide}\n\n请只回复一个0-10的整数评分，不要有任何解释或额外文字。"
                                }
                            ]
                        }
                    ],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 10},
                }
            )
        return requests_array, headers, api_url_root

    # custom provider (assumed OpenAI-like)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    messages_array = []
    for pair in prompt_pairs:
        messages_array.append(
            [
                {
                    "role": "user",
                    "content": f"作为善于发现内容关联的评分专家，请评估这对内容的关联度，给出0到10的整数评分。\n\n内容一：{pair['source_name']}\n{pair['source_content'][:max_content_length]}\n\n内容二：{pair['target_name']}\n{pair['target_content'][:max_content_length]}\n\n{scoring_guide}\n\n请只回复一个0-10的整数评分，不要有任何解释或额外文字。",
                }
            ]
        )
    data = {
        "model": model_name,
        "messages_list": messages_array,
        "max_tokens": 20,
        "temperature": 0,
    }
    return data, headers, DEFAULT_AI_CONFIGS["custom"]["api_url"]


# ---------------------------------------------------------------------------
# 解析响应
# ---------------------------------------------------------------------------

def parse_ai_batch_response(
    ai_provider: str,
    response_data: Dict | List,
    prompt_pairs: List[Dict],
) -> List[Dict]:
    """根据 provider 提取评分结果。"""
    results: List[Dict] = []

    try:
        if ai_provider == "deepseek":
            for idx, choice in enumerate(response_data.get("choices", [])):
                if idx >= len(prompt_pairs):
                    break
                content = choice.get("message", {}).get("content", "")
                score = extract_score_from_text(content)
                pair = prompt_pairs[idx]
                results.append(
                    {
                        "source_path": pair["source_path"],
                        "target_path": pair["target_path"],
                        "ai_score": score or 0,
                        "jina_similarity": pair.get("jina_similarity", 0),
                    }
                )

        elif ai_provider == "openai":
            if not prompt_pairs:
                return results
            content = (
                response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            score = extract_score_from_text(content)
            pair = prompt_pairs[0]
            results.append(
                {
                    "source_path": pair["source_path"],
                    "target_path": pair["target_path"],
                    "ai_score": score or 0,
                    "jina_similarity": pair.get("jina_similarity", 0),
                }
            )

        elif ai_provider == "claude":
            if not prompt_pairs:
                return results
            content = (
                response_data.get("content", [{}])[0].get("text", "") if response_data else ""
            )
            score = extract_score_from_text(content)
            pair = prompt_pairs[0]
            results.append(
                {
                    "source_path": pair["source_path"],
                    "target_path": pair["target_path"],
                    "ai_score": score or 0,
                    "jina_similarity": pair.get("jina_similarity", 0),
                }
            )

        elif ai_provider == "gemini":
            if not prompt_pairs:
                return results
            content = ""
            if response_data and "candidates" in response_data and response_data["candidates"]:
                parts = response_data["candidates"][0].get("content", {}).get("parts", [])
                if parts and "text" in parts[0]:
                    content = parts[0]["text"]
            score = extract_score_from_text(content)
            pair = prompt_pairs[0]
            results.append(
                {
                    "source_path": pair["source_path"],
                    "target_path": pair["target_path"],
                    "ai_score": score or 0,
                    "jina_similarity": pair.get("jina_similarity", 0),
                }
            )

        else:  # custom provider
            for idx, choice in enumerate(response_data.get("choices", [])):
                if idx >= len(prompt_pairs):
                    break
                content = choice.get("message", {}).get("content", "")
                score = extract_score_from_text(content)
                pair = prompt_pairs[idx]
                results.append(
                    {
                        "source_path": pair["source_path"],
                        "target_path": pair["target_path"],
                        "ai_score": score or 0,
                        "jina_similarity": pair.get("jina_similarity", 0),
                    }
                )

    except Exception as exc:  # pylint: disable=broad-except
        logger.error("解析 %s 响应失败: %s", ai_provider, exc)

    return results


# ---------------------------------------------------------------------------
# 提取数字
# ---------------------------------------------------------------------------

def extract_score_from_text(text: str) -> int | None:
    """从文本中抓取 0-10 整数。返回 None 表示无法提取。"""
    text = text.strip()
    try:
        score = int(text)
        if 0 <= score <= 10:
            return score
    except ValueError:
        pass

    match = re.search(r"(?<!\d)([0-9]|10)(?!\d)", text)
    if match:
        try:
            score = int(match.group(1))
            if 0 <= score <= 10:
                return score
        except ValueError:
            return None
    return None


__all__ = [
    "build_ai_batch_request",
    "parse_ai_batch_response",
    "extract_score_from_text",
]
