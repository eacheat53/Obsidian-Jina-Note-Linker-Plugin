"""Link scoring pipeline using AI provider."""
from __future__ import annotations

import os
from typing import Dict, List

from python_src.ai_scoring.provider import call_ai_api_batch_for_relevance
from python_src.ai_scoring.scorer import build_ai_batch_request
from python_src.config import AI_SCORING_BATCH_SIZE, AI_SCORING_MAX_CHARS_PER_NOTE, AI_SCORING_MAX_TOTAL_CHARS
from python_src.io.note_loader import read_markdown_with_frontmatter
from python_src.utils.db import get_db_connection
from python_src.utils.logger import get_logger

logger = get_logger(__name__)


def score_candidates(
    candidate_pairs: List[Dict],
    project_root_abs: str,
    main_db_path: str,
    ai_provider: str,
    ai_api_url: str,
    ai_api_key: str,
    ai_model_name: str,
    max_content_length_for_ai_to_use: int,
    force_rescore: bool = False,
    ai_scoring_batch_size: int = AI_SCORING_BATCH_SIZE,
    custom_scoring_prompt: str = None,
    use_custom_scoring_prompt: bool = False,
    max_pairs_per_request: int = None,
    max_chars_per_note: int = None,
    max_total_chars_per_request: int = None,
    save_api_responses: bool = True,
) -> None:
    """对候选链接对进行 AI 评分并将结果写入 SQLite。
    
    注意：此函数依赖于嵌入处理的结果生成的候选对，必须在执行嵌入处理后调用。
    
    Args:
        candidate_pairs: 候选链接对列表（基于嵌入相似度生成）
        project_root_abs: 项目根目录绝对路径
        main_db_path: 主数据库路径
        ai_provider: AI 提供商名称
        ai_api_url: AI API URL
        ai_api_key: AI API 密钥
        ai_model_name: AI 模型名称
        max_content_length_for_ai_to_use: AI 评分使用的最大内容长度
        force_rescore: 是否强制重新评分
        ai_scoring_batch_size: AI 评分批量大小
        custom_scoring_prompt: 自定义的评分提示词
        use_custom_scoring_prompt: 是否使用自定义评分提示词
        max_pairs_per_request: 每个API请求最多包含的笔记对数
        max_chars_per_note: 每个笔记在AI评分时的最大字符数
        max_total_chars_per_request: 每个API批量请求的最大总字符数
        save_api_responses: 是否保存API响应内容到数据库
    """

    if not candidate_pairs:
        logger.warning("没有候选链接对需要评分！")
        logger.warning("这可能是因为：")
        logger.warning("1. 嵌入数据不足（笔记数量太少）")
        logger.warning("2. 相似度阈值设置过高")
        logger.warning("3. 嵌入处理未正确执行")
        return

    conn = get_db_connection(main_db_path)
    cur = conn.cursor()

    # 过滤出有效的候选对
    valid_pairs = []
    for pair in candidate_pairs:
        source_abs = os.path.join(project_root_abs, pair["source_path"])
        target_abs = os.path.join(project_root_abs, pair["target_path"])
        
        # 检查文件是否存在
        if not os.path.exists(source_abs):
            logger.warning("源文件不存在，跳过: %s", source_abs)
            continue
        if not os.path.exists(target_abs):
            logger.warning("目标文件不存在，跳过: %s", target_abs)
            continue
            
        valid_pairs.append(pair)
    
    # -------------------- 智能跳过已评分对 --------------------
    if not force_rescore and valid_pairs:
        logger.info("智能模式: 检查数据库，跳过已存在且哈希未变的 AI 评分…")
        # 查询所有已评分的路径对及哈希
        cur.execute(
            """
            SELECT file_name_a, file_name_b
            FROM scores
            """
        )
        existing_pairs_raw = cur.fetchall()
        existing_pairs: set[tuple[str, str]] = {(s, t) for s, t in existing_pairs_raw} | {(t, s) for s, t in existing_pairs_raw}

        before_count = len(valid_pairs)
        def need_score(p):
            return (p["source_path"], p["target_path"]) not in existing_pairs

        valid_pairs = [p for p in valid_pairs if need_score(p)]
        skipped = before_count - len(valid_pairs)
        logger.info("已跳过 %s 条已评分链接对，剩余 %s 条待评分。", skipped, len(valid_pairs))
    
    if not valid_pairs:
        logger.info("没有需要 AI 评分的候选对，提前结束。")
        return
        
    logger.info("AI 评分开始，有效候选对: %s/%s", len(valid_pairs), len(candidate_pairs))

    # 按批处理
    for batch_start in range(0, len(valid_pairs), ai_scoring_batch_size):
        batch_pairs = valid_pairs[batch_start : batch_start + ai_scoring_batch_size]
        # 减少日志输出频率，只在10%进度间隔输出
        progress_percent = int((batch_start / len(valid_pairs)) * 100)
        if progress_percent % 10 == 0 and (batch_start == 0 or (batch_start > 0 and int(((batch_start - ai_scoring_batch_size) / len(valid_pairs)) * 100) < progress_percent)):
            logger.info("AI评分进度: %s/%s (完成%d%%)", batch_start + 1, len(valid_pairs), progress_percent)

        # 构造 prompt_pairs
        prompt_pairs: List[Dict] = []
        for p in batch_pairs:
            source_abs = os.path.join(project_root_abs, p["source_path"])
            target_abs = os.path.join(project_root_abs, p["target_path"])
            
            try:
                src_body, _, _ = read_markdown_with_frontmatter(source_abs)
                tgt_body, _, _ = read_markdown_with_frontmatter(target_abs)
                
                prompt_pairs.append(
                    {
                        **p,
                        "source_name": os.path.basename(p["source_path"]),
                        "target_name": os.path.basename(p["target_path"]),
                        "source_content": src_body[:max_content_length_for_ai_to_use],
                        "target_content": tgt_body[:max_content_length_for_ai_to_use],
                    }
                )
            except Exception as e:
                logger.error("读取文件失败，跳过: %s 或 %s, 错误: %s", source_abs, target_abs, e)
                continue

        if not prompt_pairs:
            logger.warning("该批次没有有效的提示对，跳过")
            continue

        # 根据设置决定是否使用自定义提示词
        scoring_prompt = custom_scoring_prompt if use_custom_scoring_prompt else None
        
        try:
            # 传递新的批量处理参数
            data, headers, final_url = build_ai_batch_request(
                ai_provider,
                ai_model_name,
                ai_api_key,
                prompt_pairs,
                max_content_length_for_ai_to_use,
                custom_scoring_prompt=scoring_prompt,
                max_pairs=max_pairs_per_request,
                max_chars_per_note=max_chars_per_note,
                max_total_chars=max_total_chars_per_request,
            )

            # 确定提示词类型
            prompt_type = "custom" if use_custom_scoring_prompt else "default"

            results = call_ai_api_batch_for_relevance(
                ai_provider,
                ai_model_name,
                ai_api_key,
                final_url,
                prompt_pairs,
                headers,
                data,
                max_retries=3,
                save_responses=save_api_responses,
                ai_scores_db_path=main_db_path,
                prompt_type=prompt_type,
            )
        except Exception as e:
            logger.error("AI评分请求失败: %s", e)
            continue

        # note_id 需要查找或从 candidate_pairs 结构获取，假设 candidate_pairs 中包含 note_id_*.
        rel_insert_rows = []
        for r in results:
            src_path = r["source_path"]
            tgt_path = r["target_path"]

            # 从 prompt_pairs 找 note_id
            src_nid = next((pp.get("source_note_id") for pp in prompt_pairs if pp["source_path"] == src_path), "")
            tgt_nid = next((pp.get("target_note_id") for pp in prompt_pairs if pp["target_path"] == tgt_path), "")

            rel_insert_rows.append(
                (
                    src_nid,
                    src_path,
                    tgt_nid,
                    tgt_path,
                    r.get("ai_score"),
                )
            )
        cur.executemany(
            """
            INSERT INTO scores (note_id_a, file_name_a, note_id_b, file_name_b, ai_score)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(note_id_a, note_id_b) DO UPDATE SET
                ai_score = excluded.ai_score
            """,
            rel_insert_rows,
        )
        conn.commit()

    conn.close()
    logger.info("AI 评分流程完成。")


__all__ = ["score_candidates"] 