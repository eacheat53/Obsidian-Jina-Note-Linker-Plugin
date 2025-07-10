"""AI 批量评分请求与响应解析工具。"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple
import os

from python_src.config import DEFAULT_AI_CONFIGS, AI_SCORING_BATCH_SIZE, AI_SCORING_MAX_CHARS_PER_NOTE, AI_SCORING_MAX_TOTAL_CHARS
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
    custom_scoring_prompt: str = None,
    max_pairs: int = None,
    max_chars_per_note: int = None,
    max_total_chars: int = None,
) -> Tuple[List | Dict, Dict, str]:
    """根据 provider 构造 headers / body / url。
    
    优化为批量请求模式，减少重复发送评分标准。

    Args:
        ai_provider: AI提供商名称
        model_name: 模型名称
        api_key: API密钥
        prompt_pairs: 需要评分的内容对列表
        max_content_length: 最大内容长度
        custom_scoring_prompt: 自定义评分提示词
        max_pairs: 每次请求最多处理的笔记对数，默认为配置中的值
        max_chars_per_note: 每个笔记最大字符数，默认为配置中的值
        max_total_chars: 每个请求最大总字符数，默认为配置中的值
        
    返回 (data, headers, api_url)。"""
    # 使用默认配置或传入参数
    max_pairs = max_pairs or AI_SCORING_BATCH_SIZE
    single_note_limit = min(max_chars_per_note or AI_SCORING_MAX_CHARS_PER_NOTE, max_content_length)
    max_total_length = max_total_chars or AI_SCORING_MAX_TOTAL_CHARS
    
    # 限制单个笔记内容长度和批量处理的对数
    if len(prompt_pairs) > max_pairs:
        prompt_pairs = prompt_pairs[:max_pairs]
        logger.info(f"批量请求超出限制，截取前{max_pairs}对内容进行处理")
    
    # 使用自定义提示词或默认提示词
    scoring_guide = custom_scoring_prompt.strip() if custom_scoring_prompt else """
    作为笔记关联性评分专家，请评估以下多对内容的关联度。这些内容可能包括知识笔记、诗歌创作、灵感片段、散文、情感记录等多样化形式。对每对内容给出0-10的整数评分，基于以下全面标准：

    【评分标准：】
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
    
    请只回复一个0-10的整数评分，不要有任何解释或额外文字！
    """.strip()

    if ai_provider == "deepseek":
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        api_url = DEFAULT_AI_CONFIGS["deepseek"]["api_url"]
        
        # 优化：构建一个批量请求
        if len(prompt_pairs) > 0:
            # 构建多对内容的批量提示
            content_pairs_text = ""
            total_length = 0
            
            for idx, pair in enumerate(prompt_pairs):
                source_content = pair['source_content'][:single_note_limit]
                target_content = pair['target_content'][:single_note_limit]
                
                pair_text = f"[内容对 {idx+1}]\n内容一：{pair['source_name']}\n{source_content}\n\n内容二：{pair['target_name']}\n{target_content}\n\n"
                pair_length = len(pair_text)
                
                # 检查添加这对内容是否会超出总字数限制
                if total_length + pair_length > max_total_length:
                    logger.info(f"已达到最大总字数限制({max_total_length}字)，只处理前{idx}对内容")
                    break
                
                content_pairs_text += pair_text
                total_length += pair_length
            
            # 修复DeepSeek请求格式，确保符合API规范
            system_prompt = "你是善于发现内容关联的评分专家。请按顺序为每对内容提供0-10的整数评分。"
            user_prompt = f"{scoring_guide}\n\n以下是需要评分的多对内容，请按顺序为每对内容提供一个0-10的整数评分，用逗号分隔每个分数。\n\n{content_pairs_text}\n请回复格式为：'分数1,分数2,分数3...'（仅包含数字和逗号，不要有其他文字）"
            
            batch_request = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 5000,
                "temperature": 0.7,
            }
            return [batch_request], headers, api_url
        
        # 如果没有内容对，返回空数组
        return [], headers, api_url

    if ai_provider == "openai":
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        api_url = DEFAULT_AI_CONFIGS["openai"]["api_url"]
        
        # 优化：构建一个批量请求
        if len(prompt_pairs) > 0:
            # 构建多对内容的批量提示
            content_pairs_text = ""
            total_length = 0
            
            for idx, pair in enumerate(prompt_pairs):
                source_content = pair['source_content'][:single_note_limit]
                target_content = pair['target_content'][:single_note_limit]
                
                pair_text = f"[内容对 {idx+1}]\n内容一：{pair['source_name']}\n{source_content}\n\n内容二：{pair['target_name']}\n{target_content}\n\n"
                pair_length = len(pair_text)
                
                # 检查添加这对内容是否会超出总字数限制
                if total_length + pair_length > max_total_length:
                    logger.info(f"已达到最大总字数限制({max_total_length}字)，只处理前{idx}对内容")
                    break
                
                content_pairs_text += pair_text
                total_length += pair_length
            
            batch_request = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "你是善于发现内容关联的评分专家。请按顺序为每对内容提供0-10的整数评分。"},
                    {"role": "user", "content": f"{scoring_guide}\n\n以下是需要评分的多对内容，请按顺序为每对内容提供一个0-10的整数评分，用逗号分隔每个分数。\n\n{content_pairs_text}\n请回复格式为：'分数1,分数2,分数3...'（仅包含数字和逗号，不要有其他文字）"}
                ],
                "max_tokens": 10000,
                "temperature": 0.7,
            }
            return [batch_request], headers, api_url
            
        # 如果没有内容对，返回空数组
        return [], headers, api_url

    if ai_provider == "claude":
        headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        api_url = DEFAULT_AI_CONFIGS["claude"]["api_url"]
        
        # 优化：构建一个批量请求
        if len(prompt_pairs) > 0:
            # 构建多对内容的批量提示
            content_pairs_text = ""
            total_length = 0
            
            for idx, pair in enumerate(prompt_pairs):
                source_content = pair['source_content'][:single_note_limit]
                target_content = pair['target_content'][:single_note_limit]
                
                pair_text = f"[内容对 {idx+1}]\n内容一：{pair['source_name']}\n{source_content}\n\n内容二：{pair['target_name']}\n{target_content}\n\n"
                pair_length = len(pair_text)
                
                # 检查添加这对内容是否会超出总字数限制
                if total_length + pair_length > max_total_length:
                    logger.info(f"已达到最大总字数限制({max_total_length}字)，只处理前{idx}对内容")
                    break
                
                content_pairs_text += pair_text
                total_length += pair_length
            
            batch_request = {
                "model": model_name,
                "max_tokens": 10000,
                "system": "你是善于发现内容关联的评分专家。请按顺序为每对内容提供0-10的整数评分，用逗号分隔，不要有多余文字。",
                "messages": [
                    {"role": "user", "content": f"{scoring_guide}\n\n以下是需要评分的多对内容，请按顺序为每对内容提供一个0-10的整数评分，用逗号分隔每个分数。\n\n{content_pairs_text}\n请回复格式为：'分数1,分数2,分数3...'（仅包含数字和逗号，不要有其他文字）"}
                ],
                "temperature": 0.7,
            }
            return [batch_request], headers, api_url
            
        # 如果没有内容对，返回空数组
        return [], headers, api_url

    if ai_provider == "gemini":
        headers = {"Content-Type": "application/json"}
        api_url_root = DEFAULT_AI_CONFIGS["gemini"]["api_url"]
        
        # 优化：构建一个批量请求
        if len(prompt_pairs) > 0:
            # 构建多对内容的批量提示
            content_pairs_text = ""
            total_length = 0
            
            for idx, pair in enumerate(prompt_pairs):
                source_content = pair['source_content'][:single_note_limit]
                target_content = pair['target_content'][:single_note_limit]
                
                pair_text = f"[内容对 {idx+1}]\n内容一：{pair['source_name']}\n{source_content}\n\n内容二：{pair['target_name']}\n{target_content}\n\n"
                pair_length = len(pair_text)
                
                # 检查添加这对内容是否会超出总字数限制
                if total_length + pair_length > max_total_length:
                    logger.info(f"已达到最大总字数限制({max_total_length}字)，只处理前{idx}对内容")
                    break
                
                content_pairs_text += pair_text
                total_length += pair_length
            
            # 修改Gemini请求格式，明确指示输出数字
            system_prompt = "你是一位善于发现内容关联的评分专家，需要对内容对进行0-10分评分。只回复逗号分隔的数字，不要有其他文字。"
            user_prompt = f"{scoring_guide}\n\n以下是需要评分的多对内容，请按顺序为每对内容提供一个0-10的整数评分。\n\n{content_pairs_text}\n请直接回复逗号分隔的数字序列，例如：'8,6,9,3,7'，不要有任何额外文字或标点符号。"
            
            batch_request = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": user_prompt
                            }
                        ]
                    }
                ],
                "systemInstruction": {
                    "role": "system",
                    "parts": [{"text": system_prompt}]
                },
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 5000},
            }
            return [batch_request], headers, api_url_root
            
        # 如果没有内容对，返回空数组
        return [], headers, api_url_root

    # custom provider (assumed OpenAI-like)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    # 优化：构建一个批量请求
    if len(prompt_pairs) > 0:
        # 构建多对内容的批量提示
        content_pairs_text = ""
        total_length = 0
        
        for idx, pair in enumerate(prompt_pairs):
            source_content = pair['source_content'][:single_note_limit]
            target_content = pair['target_content'][:single_note_limit]
            
            pair_text = f"[内容对 {idx+1}]\n内容一：{pair['source_name']}\n{source_content}\n\n内容二：{pair['target_name']}\n{target_content}\n\n"
            pair_length = len(pair_text)
            
            # 检查添加这对内容是否会超出总字数限制
            if total_length + pair_length > max_total_length:
                logger.info(f"已达到最大总字数限制({max_total_length}字)，只处理前{idx}对内容")
                break
            
            content_pairs_text += pair_text
            total_length += pair_length
        
        messages_array = [
            [
                {
                    "role": "user",
                    "content": f"{scoring_guide}\n\n以下是需要评分的多对内容，请按顺序为每对内容提供一个0-10的整数评分，用逗号分隔每个分数。\n\n{content_pairs_text}\n请回复格式为：'分数1,分数2,分数3...'（仅包含数字和逗号，不要有其他文字）"
                }
            ]
        ]
        
        data = {
            "model": model_name,
            "messages_list": messages_array,
            "max_tokens": 100,
            "temperature": 1.0,
        }
        return data, headers, DEFAULT_AI_CONFIGS["custom"]["api_url"]
        
    # 如果没有内容对，返回空对象
    data = {
        "model": model_name,
        "messages_list": [],
        "max_tokens": 100,
        "temperature": 1.0,
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
    """根据 provider 提取评分结果。
    
    优化后支持批量评分响应解析，从逗号分隔的分数列表中提取对应的分数。
    """
    results: List[Dict] = []
    
    # 如果没有提示对，直接返回
    if not prompt_pairs:
        return results

    try:
        # 解析批量评分结果
        if ai_provider == "deepseek":
            if not response_data or "choices" not in response_data:
                return results
                
            # 获取批量评分返回的内容
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # 解析逗号分隔的分数
            scores = extract_scores_from_text(content, len(prompt_pairs))
            
            # 为每对内容生成结果
            for idx, pair in enumerate(prompt_pairs):
                if idx < len(scores):
                    results.append(
                        {
                            "source_path": pair["source_path"],
                            "target_path": pair["target_path"],
                            "ai_score": scores[idx] or 0,
                            "jina_similarity": pair.get("jina_similarity", 0),
                        }
                    )
            
        elif ai_provider == "openai":
            if not response_data or "choices" not in response_data:
                return results
                
            # 获取批量评分返回的内容
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # 解析逗号分隔的分数
            scores = extract_scores_from_text(content, len(prompt_pairs))
            
            # 为每对内容生成结果
            for idx, pair in enumerate(prompt_pairs):
                if idx < len(scores):
                    results.append(
                        {
                            "source_path": pair["source_path"],
                            "target_path": pair["target_path"],
                            "ai_score": scores[idx] or 0,
                            "jina_similarity": pair.get("jina_similarity", 0),
                        }
                    )

        elif ai_provider == "claude":
            if not response_data or "content" not in response_data:
                return results
                
            # 获取批量评分返回的内容
            content = response_data.get("content", [{}])[0].get("text", "") if response_data else ""
            # 解析逗号分隔的分数
            scores = extract_scores_from_text(content, len(prompt_pairs))
            
            # 为每对内容生成结果
            for idx, pair in enumerate(prompt_pairs):
                if idx < len(scores):
                    results.append(
                        {
                            "source_path": pair["source_path"],
                            "target_path": pair["target_path"],
                            "ai_score": scores[idx] or 0,
                            "jina_similarity": pair.get("jina_similarity", 0),
                        }
                    )

        elif ai_provider == "gemini":
            if not response_data or "candidates" not in response_data:
                return results
                
            # 获取批量评分返回的内容
            content = ""
            if response_data["candidates"]:
                candidate = response_data["candidates"][0]
                content_obj = candidate.get("content", {})
                
                # 新格式: candidates[0].content.text 直接包含文本
                if "text" in content_obj:
                    content = content_obj["text"]
                # 新格式: candidates[0].text 直接包含文本
                elif "text" in candidate:
                    content = candidate["text"]
                # 旧格式: candidates[0].content.parts[0].text
                elif "parts" in content_obj:
                    parts = content_obj.get("parts", [])
                    if parts and "text" in parts[0]:
                        content = parts[0]["text"]
                    
            # 解析逗号分隔的分数
            scores = extract_scores_from_text(content, len(prompt_pairs))
            
            # 为每对内容生成结果
            for idx, pair in enumerate(prompt_pairs):
                if idx < len(scores):
                    results.append(
                        {
                            "source_path": pair["source_path"],
                            "target_path": pair["target_path"],
                            "ai_score": scores[idx] or 0,
                            "jina_similarity": pair.get("jina_similarity", 0),
                        }
                    )

        else:  # custom provider
            if not response_data or "choices" not in response_data:
                return results
                
            # 获取批量评分返回的内容
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # 解析逗号分隔的分数
            scores = extract_scores_from_text(content, len(prompt_pairs))
            
            # 为每对内容生成结果
            for idx, pair in enumerate(prompt_pairs):
                if idx < len(scores):
                    results.append(
                        {
                            "source_path": pair["source_path"],
                            "target_path": pair["target_path"],
                            "ai_score": scores[idx] or 0,
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
    """从文本中抓取单个 0-10 整数。返回 None 表示无法提取。"""
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


def extract_scores_from_text(text: str, expected_count: int) -> List[int | None]:
    """从文本中提取多个逗号分隔的 0-10 整数评分。
    
    Args:
        text: 包含评分的文本内容，通常是逗号分隔的数字
        expected_count: 期望的评分数量
        
    Returns:
        列表，包含提取出的整数评分，如果某项无法提取则为None
    """
    scores = []
    
    # 首先尝试最简单的情况：文本就是逗号分隔的数字列表
    clean_text = text.strip().replace(" ", "")
    if re.match(r'^(\d+,)*\d+$', clean_text):
        try:
            # 直接分割并转换为整数
            for num_str in clean_text.split(','):
                num = int(num_str)
                if 0 <= num <= 10:
                    scores.append(num)
                else:
                    scores.append(0)  # 超出范围的数字设为0
            
            # 如果找到的分数达到预期，直接返回
            if len(scores) == expected_count:
                return scores
        except ValueError:
            # 如果有任何转换错误，继续使用正则表达式方法
            pass
    
    # 如果简单方法失败，使用更强大的正则表达式
    try:
        # 改进正则表达式以匹配数字
        # 匹配模式:
        # 1. 独立的数字 (使用\b边界)
        # 2. 特别优先匹配10 (因为它是两位数)
        # 3. 然后匹配0-9的单个数字
        scores_matches = re.findall(r'\b(10|[0-9])\b', text)
        
        # 补充尝试匹配逗号分隔的形式
        if not scores_matches:
            comma_matches = re.findall(r'(\d+)(?:,|$)', text)
            if comma_matches:
                scores_matches = comma_matches
        
        for match in scores_matches:
            try:
                score = int(match)
                if 0 <= score <= 10:
                    scores.append(score)
                else:
                    scores.append(0)  # 超出范围的数字设为0
                    
                # 如果已经找到预期数量的分数，就提前停止
                if len(scores) == expected_count:
                    break
            except (ValueError, TypeError):
                continue # 如果转换失败，跳过这个匹配项
                
    except Exception as e:
        logger.error(f"从文本中提取分数时出错: '{text}'. 错误: {e}")
        # 失败时，返回一个包含0的列表（而不是None）
        return [0] * expected_count

    # 如果找到的分数不足，用0填充剩余部分（而不是None）
    while len(scores) < expected_count:
        scores.append(0)

    
    # 确保返回的列表长度不超过预期数量
    return scores[:expected_count]


__all__ = [
    "build_ai_batch_request",
    "parse_ai_batch_response",
    "extract_score_from_text",
    "extract_scores_from_text",
    ]
