"""Batch AI tag generation pipeline."""
from __future__ import annotations

import os
import json
import uuid
import time
import requests
from typing import List, Dict

from python_src.config import (
    AI_API_REQUEST_DELAY_SECONDS,
    AI_SCORING_MAX_CHARS_PER_NOTE,
    AI_SCORING_MAX_TOTAL_CHARS,
    DEFAULT_AI_CONFIGS,
)
from python_src.ai_scoring.provider import save_api_response  # 用于落库请求/响应
from python_src.ai_scoring.scorer import build_ai_batch_request  # 复用构造器
from python_src.config import AI_SCORING_BATCH_SIZE
from python_src.utils.db import get_db_connection
from python_src.io.note_loader import read_markdown_with_frontmatter
from python_src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TAG_PROMPT = """
你是一位知识管理与卡片笔记法（Zettelkasten）专家，擅长构建结构清晰、易于连接和检索的个人知识库。

你的任务是：针对我提供的每一篇笔记正文，为其生成一组精准、精炼且具有系统性的「中文标签」。这些标签应揭示笔记的核心思想，并帮助我将其融入到更广阔的知识网络中。

请严格遵循以下原则：
1. 【核心主题】识别笔记最关键、最核心的主题或关键词。
2. 【抽象概念】提炼能抽象出更高层次思想的概念。
3. 【知识领域】尽量使用分层标签定位知识领域，格式如：哲学/古希腊哲学、计算机科学/人工智能。
4. 【关联性】思考本笔记可与哪些主题产生有意义的连接。

输出规则：
• 每篇笔记最多 5 个标签；
• 标签全部使用中文；
• 标签之间使用英文逗号","分隔，逗号后不加空格；
• 每个标签内部不得包含空格；
• 只回复一行，且严格使用以下格式（注意冒号后有一个空格）：
  <笔记标题>: 标签1,标签2,标签3

除了这行标签信息之外，不要输出任何额外的说明、解释或多余文字！
"""


# ---------------------------------------------------------------------------
# 构建批量标签请求
# ---------------------------------------------------------------------------


def build_tag_batch_request(
    ai_provider: str,
    model_name: str,
    api_key: str,
    notes: List[Dict],
    prompt_template: str,
    max_chars_per_note: int | None = AI_SCORING_MAX_CHARS_PER_NOTE,
    max_total_chars: int | None = AI_SCORING_MAX_TOTAL_CHARS,
    base_api_url: str | None = None,
):
    """根据 provider 构造批量标签请求 (data, headers, api_url)。"""

    single_note_limit = max_chars_per_note or AI_SCORING_MAX_CHARS_PER_NOTE
    max_total_length = max_total_chars or AI_SCORING_MAX_TOTAL_CHARS

    # 拼装所有笔记内容
    notes_text = ""
    total_length = 0
    for idx, note in enumerate(notes):
        title = note.get("title", f"Note{idx+1}")
        content = (note.get("content") or "")[:single_note_limit]
        note_block = f"[笔记 {idx+1}]\n标题：{title}\n{content}\n\n"
        if total_length + len(note_block) > max_total_length:
            break
        notes_text += note_block
        total_length += len(note_block)

    # 无论是默认提示词还是自定义提示词，都添加固定的格式要求和结尾提示
    fixed_ending = "请严格按要求输出，不要输出多余的任何解释！"
    
    # 生成请求体
    system_prompt = "你是一位善于提炼知识标签的专家。"
    user_prompt = (
        f"{prompt_template}\n\n以下是待生成标签的多篇笔记，请保持顺序，一行输出一篇笔记的标签：\n\n{notes_text}\n" +
        f"{fixed_ending}"
    )

    if ai_provider in {"openai", "deepseek", "custom"}:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        # 如果用户传入自定义 base_api_url 优先使用；否则从默认映射表取
        api_url = base_api_url or DEFAULT_AI_CONFIGS.get(ai_provider, {}).get("api_url", "")

        # 对 OpenAI 兼容型接口，若 URL 看起来像域根或缺少 /chat/completions，则补全
        if ai_provider in {"openai", "deepseek", "custom"}:
            if api_url.rstrip("/").endswith("api.openai.com") or api_url.rstrip("/").endswith("api.deepseek.com"):
                api_url = api_url.rstrip("/") + "/v1/chat/completions" if ai_provider == "openai" else api_url.rstrip("/") + "/chat/completions"
        batch_request = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 5000,
            "temperature": 1.0,
        }
        return batch_request, headers, api_url

    if ai_provider == "claude":
        headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        api_url = DEFAULT_AI_CONFIGS["claude"]["api_url"]
        batch_request = {
            "model": model_name,
            "max_tokens": 5000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 1.0,
        }
        return batch_request, headers, api_url

    if ai_provider == "gemini":
        headers = {"Content-Type": "application/json"}
        api_url_root = base_api_url or DEFAULT_AI_CONFIGS["gemini"]["api_url"]
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
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 5000},
        }
        return batch_request, headers, api_url_root

    raise ValueError(f"Unsupported ai_provider: {ai_provider}")


# ---------------------------------------------------------------------------
# 解析批量标签响应
# ---------------------------------------------------------------------------


def parse_tag_batch_response(ai_provider: str, response_data: Dict | List):
    """提取模型返回的多行标签文本，返回纯文本。"""
    content = ""
    if ai_provider in {"openai", "custom", "deepseek"}:
        content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
    elif ai_provider == "claude":
        content = response_data.get("content", [{}])[0].get("text", "") if response_data else ""
    elif ai_provider == "gemini":
        if response_data.get("candidates"):
            # 处理新旧两种格式的Gemini API响应
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
    
    return content.strip()


# ---------------------------------------------------------------------------
# 调用 AI API 并落库 (标签生成专用)
# ---------------------------------------------------------------------------


def call_ai_api_batch_for_tags(
    ai_provider: str,
    model_name: str,
    api_key: str,
    api_url: str,
    prompt_notes: List[Dict],
    headers: Dict,
    data: Dict,
    max_retries: int = 3,
    save_responses: bool = True,
    db_path: str | None = None,
    prompt_type: str = "tagging_default",
):
    """调用批量标签生成 API, 返回 [{'note_id': .., 'ai_response': line_text}, ...]"""

    if not prompt_notes:
        return []

    batch_id = str(uuid.uuid4())
    logger.info("开始批量标签生成...")

    for attempt in range(max_retries):
        try:
            time.sleep(AI_API_REQUEST_DELAY_SECONDS)

            # gemini 需要拼接 key
            if ai_provider == "gemini":
                full_url = f"{api_url}/{model_name}:generateContent?key={api_key}"
                resp = requests.post(full_url, headers=headers, json=data, timeout=60)
            else:
                resp = requests.post(api_url, headers=headers, json=data, timeout=60)

            resp.raise_for_status()
            resp_json = resp.json()

            # 保存请求/响应
            if save_responses and db_path:
                try:
                    save_api_response(
                        db_path,
                        batch_id,
                        ai_provider,
                        model_name,
                        json.dumps(data, ensure_ascii=False),
                        json.dumps(resp_json, ensure_ascii=False),
                        prompt_type,
                    )
                except Exception as exc:
                    logger.error("保存标签API响应失败: %s", exc)

            content_text = parse_tag_batch_response("openai" if ai_provider == "deepseek" else ai_provider, resp_json)

            lines = [ln.strip() for ln in content_text.splitlines() if ln.strip()]
            results = []
            for idx, line in enumerate(lines):
                note_id = prompt_notes[idx]["note_id"] if idx < len(prompt_notes) else None
                results.append({"note_id": note_id, "ai_response": line})

            return results
        except requests.exceptions.RequestException as exc:
            logger.error("标签生成API 调用失败 (%s/%s): %s", attempt + 1, max_retries, exc)
            time.sleep(2 ** attempt)

    logger.error("标签生成API 最终失败，放弃该批次")
    return []


def generate_tags(
    project_root_abs: str,
    main_db_path: str,
    ai_provider: str,
    ai_api_url: str,
    ai_api_key: str,
    ai_model_name: str,
    max_content_length_for_ai: int,
    force_regen: bool = False,
    batch_size: int = AI_SCORING_BATCH_SIZE,
    custom_prompt: str | None = None,
    use_custom_prompt: bool = False,
    max_chars_per_note: int | None = AI_SCORING_MAX_CHARS_PER_NOTE,
    max_total_chars_per_request: int | None = AI_SCORING_MAX_TOTAL_CHARS,
    save_api_responses: bool = True,
):
    """为已嵌入的笔记生成 AI 标签并保存到数据库。
    
    注意：此函数依赖于嵌入处理的结果，必须在执行嵌入处理后调用。
    支持处理单个笔记或批量处理多个笔记。
    """
    conn = get_db_connection(main_db_path)
    cur = conn.cursor()

    # 选择需要生成标签的笔记
    cur.execute("SELECT note_id, file_name FROM notes WHERE embedding IS NOT NULL")
    all_notes = cur.fetchall()

    if not all_notes:
        logger.error("数据库中没有找到已嵌入的笔记！")
        logger.error("请确保已完成嵌入处理，数据库中有有效的嵌入数据")
        conn.close()
        return

    if not force_regen:
        # 智能模式：过滤已有标签的笔记
        cur.execute("SELECT DISTINCT note_id FROM note_tags")
        existing_ids = {row[0] for row in cur.fetchall()}
        to_process = [(nid, fp) for nid, fp in all_notes if nid not in existing_ids]
        logger.info("智能模式：跳过已有标签的 %d 个笔记，待处理 %d 个笔记", 
                   len(existing_ids), len(to_process))
    else:
        # 强制模式：处理所有笔记
        to_process = all_notes
        logger.info("强制模式：将为所有 %d 个笔记重新生成标签", len(to_process))

    if not to_process:
        logger.info("没有需要生成标签的笔记（所有笔记都已有标签）")
        conn.close()
        return

    # 调整日志信息，支持单个或多个笔记
    if len(to_process) == 1:
        logger.info("开始为单个笔记生成 AI 标签")
    else:
        logger.info("开始 AI 标签生成，总笔记数: %s", len(to_process))

    prompt_template = custom_prompt if use_custom_prompt else DEFAULT_TAG_PROMPT

    # 批量处理，减少日志输出频率
    for batch_start in range(0, len(to_process), batch_size):
        batch_end = min(batch_start + batch_size, len(to_process))
        current_batch = to_process[batch_start:batch_end]
        
        # 仅在每10%进度时输出日志
        progress_percent = int((batch_start / len(to_process)) * 100)
        if progress_percent % 10 == 0 and (batch_start == 0 or (batch_start > 0 and int(((batch_start - batch_size) / len(to_process)) * 100) < progress_percent)):
            logger.info("AI标签生成进度: %s/%s (完成%d%%)", batch_start + 1, len(to_process), progress_percent)

        prompt_notes: List[Dict] = []
        for note_id, rel_path in current_batch:
            abs_path = os.path.join(project_root_abs, rel_path)
            try:
                body, _, _ = read_markdown_with_frontmatter(abs_path)
                prompt_notes.append({
                    "note_id": note_id,
                    "file_path": rel_path,
                    "title": os.path.splitext(os.path.basename(rel_path))[0],
                    "content": body[:max_content_length_for_ai],
                })
            except Exception as exc:
                logger.warning("读取笔记失败 %s: %s", rel_path, exc)

        if not prompt_notes:
            continue

        # 构建批量标签请求
        data, headers, final_url = build_tag_batch_request(
            ai_provider,
            ai_model_name,
            ai_api_key,
            prompt_notes,
            prompt_template,
            max_chars_per_note=max_chars_per_note,
            max_total_chars=max_total_chars_per_request,
            base_api_url=ai_api_url,
        )

        results = call_ai_api_batch_for_tags(
            ai_provider,
            ai_model_name,
            ai_api_key,
            final_url,
            prompt_notes,
            headers,
            data,
            save_responses=save_api_responses,
            db_path=main_db_path,
            prompt_type="tagging_custom" if use_custom_prompt else "tagging_default",
        )

        # 解析返回 -> [(nid, tag, conf)]
        insert_rows = []
        for raw in results:
            note_id = raw.get("note_id")
            tags_line = raw.get("ai_response", "")
            # 粗解析: title: tag1, tag2
            if ':' in tags_line:
                _, tags_str = tags_line.split(':', 1)
            else:
                tags_str = tags_line
            for tag in [t.strip() for t in tags_str.split(',') if t.strip()]:
                insert_rows.append((note_id, tag, None))

        cur.executemany(
            """
            INSERT OR IGNORE INTO note_tags (note_id, tag, confidence)
            VALUES (?, ?, ?)
            """,
            insert_rows,
        )
        conn.commit()
        logger.info("已写入 %s 条标签", len(insert_rows))

    conn.close()
    logger.info("AI 标签生成流程完成")

__all__ = ["generate_tags"] 