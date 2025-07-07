"""Link scoring pipeline using AI provider."""
from __future__ import annotations

import os
from typing import Dict, List

from python_src.ai_scoring.provider import call_ai_api_batch_for_relevance
from python_src.ai_scoring.scorer import build_ai_batch_request
from python_src.config import AI_SCORING_BATCH_SIZE
from python_src.io.note_loader import read_markdown_with_frontmatter
from python_src.utils.db import get_db_connection
from python_src.utils.logger import get_logger

logger = get_logger(__name__)


def score_candidates(
    candidate_pairs: List[Dict],
    project_root_abs: str,
    embeddings_db_path: str,
    ai_scores_db_path: str,
    ai_provider: str,
    ai_api_url: str,
    ai_api_key: str,
    ai_model_name: str,
    max_content_length_for_ai_to_use: int,
    force_rescore: bool = False,
    ai_scoring_batch_size: int = AI_SCORING_BATCH_SIZE,
) -> None:
    """对候选链接对进行 AI 评分并将结果写入 SQLite。"""

    if not candidate_pairs:
        logger.info("没有候选链接对需要评分。")
        return

    conn = get_db_connection(ai_scores_db_path)
    cur = conn.cursor()

    # 建立 file_path ↔ id 双向映射
    cur.execute("SELECT id, file_path FROM file_paths")
    id_by_path: Dict[str, int] = {p: fid for fid, p in cur.fetchall()}

    def ensure_file_id(path: str) -> int:
        fid = id_by_path.get(path)
        if fid is None:
            cur.execute("INSERT INTO file_paths (file_path) VALUES (?)", (path,))
            fid = cur.lastrowid
            id_by_path[path] = fid
        return fid

    # 按批处理
    for batch_start in range(0, len(candidate_pairs), ai_scoring_batch_size):
        batch_pairs = candidate_pairs[batch_start : batch_start + ai_scoring_batch_size]
        logger.info("AI 评分批次 %s-%s/%s", batch_start + 1, batch_start + len(batch_pairs), len(candidate_pairs))

        # 构造 prompt_pairs
        prompt_pairs: List[Dict] = []
        for p in batch_pairs:
            source_abs = os.path.join(project_root_abs, p["source_path"])
            target_abs = os.path.join(project_root_abs, p["target_path"])
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

        data, headers, final_url = build_ai_batch_request(
            ai_provider,
            ai_model_name,
            ai_api_key,
            prompt_pairs,
            max_content_length_for_ai_to_use,
        )

        results = call_ai_api_batch_for_relevance(
            ai_provider,
            ai_model_name,
            ai_api_key,
            final_url,
            prompt_pairs,
            headers,
            data,
            max_retries=3,
        )

        # 将结果写入 DB
        rel_insert_rows = []
        for r in results:
            src_id = ensure_file_id(r["source_path"])
            tgt_id = ensure_file_id(r["target_path"])
            rel_insert_rows.append(
                (
                    src_id,
                    tgt_id,
                    r.get("ai_score"),
                    r.get("jina_similarity"),
                )
            )
        cur.executemany(
            """
            INSERT INTO ai_relationships (source_file_id, target_file_id, ai_score, jina_similarity, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_file_id, target_file_id) DO UPDATE SET
                ai_score=excluded.ai_score,
                jina_similarity=excluded.jina_similarity,
                updated_at=CURRENT_TIMESTAMP
            """,
            rel_insert_rows,
        )
        conn.commit()

    conn.close()
    logger.info("AI 评分流程完成。")


__all__ = ["score_candidates"] 