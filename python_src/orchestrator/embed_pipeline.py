"""Note embedding pipeline (high-level orchestration)."""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List

from python_src.config import EMBEDDING_BATCH_SIZE
from python_src.embeddings.generator import get_jina_embeddings_batch
from python_src.hash_utils.hasher import (
    calculate_hash_from_content,
    extract_content_for_hashing,
)
from python_src.io.note_loader import read_markdown_with_frontmatter
from python_src.io.output_writer import write_markdown_with_frontmatter
import uuid
from python_src.utils.db import get_db_connection
from python_src.utils.logger import get_logger

logger = get_logger(__name__)


def process_and_embed_notes(
    project_root_abs: str,
    files_relative_to_project_root: List[str],
    embeddings_db_path: str,
    jina_api_key_to_use: str,
    jina_model_name_to_use: str,
    max_chars_for_jina_to_use: int,
    embedding_batch_size: int = EMBEDDING_BATCH_SIZE,
) -> Dict:
    """处理笔记，生成嵌入并保存到 SQLite。返回与旧版兼容的数据结构。"""
    conn = get_db_connection(embeddings_db_path)
    cur = conn.cursor()

    # 从数据库预先加载 notes 表数据，构建映射: file_name -> {...}
    files_data_from_db: Dict[str, Dict] = {}
    cur.execute(
        "SELECT file_name, content_hash, embedding, note_id FROM notes"
    )
    for fp, h, emb_blob, nid in cur.fetchall():
        files_data_from_db[fp] = {
            "hash": h,
            "embedding": json.loads(emb_blob) if emb_blob else None,
            "note_id": nid,
        }

    embedded_count = 0
    processed_files_this_run = 0
    all_files_data_for_return = files_data_from_db.copy()

    # 批处理
    total_files = len(files_relative_to_project_root)
    batch_size = embedding_batch_size
    for batch_start in range(0, total_files, batch_size):
        batch_files = files_relative_to_project_root[batch_start : batch_start + batch_size]
        logger.info("批量处理文件 %s-%s/%s", batch_start + 1, batch_start + len(batch_files), total_files)

        batch_contents: List[str] = []
        batch_file_info: List[Dict] = []

        for rel_path in batch_files:
            abs_path = os.path.join(project_root_abs, rel_path)
            if not os.path.exists(abs_path):
                logger.warning("文件不存在，已跳过并从 DB 删除: %s", rel_path)
                # 删除 notes 记录和相关 scores 记录
                cur.execute("SELECT note_id FROM notes WHERE file_name = ?", (rel_path,))
                row = cur.fetchone()
                if row:
                    nid_to_remove = row[0]
                    cur.execute("DELETE FROM notes WHERE note_id = ?", (nid_to_remove,))
                    cur.execute("DELETE FROM scores WHERE note_id_a = ? OR note_id_b = ?", (nid_to_remove, nid_to_remove))
                all_files_data_for_return.pop(rel_path, None)
                continue

            # 读取内容 - read_markdown_with_frontmatter 已经过滤了边界标记之后的内容
            body, fm, _ = read_markdown_with_frontmatter(abs_path)

            # 处理 note_id
            note_id = fm.get("note_id")
            if not note_id:
                note_id = str(uuid.uuid4())
                fm["note_id"] = note_id
                # 将新的 note_id 写回文件
                write_markdown_with_frontmatter(abs_path, fm, body)

            
            # 为了哈希计算，我们还是需要使用 extract_content_for_hashing
            content_to_hash = extract_content_for_hashing(body)
            if content_to_hash is None:
                # 如果没有 boundary marker，就用整个 body
                content_to_hash = body.rstrip("\r\n") + "\n"
            
            # 计算哈希
            content_hash = calculate_hash_from_content(content_to_hash)
            
            # 使用纯正文内容（没有哈希边界后的内容）进行嵌入处理
            # 限制字符数量
            processed_content = body[:max_chars_for_jina_to_use]

            existing = files_data_from_db.get(rel_path)

            # 判断是否需要重新嵌入：数据库已存同哈希且有嵌入
            if (
                existing
                and existing["hash"] == content_hash
                and existing["embedding"] is not None
            ):
                all_files_data_for_return[rel_path] = existing
                continue

            batch_contents.append(processed_content)
            batch_file_info.append(
                {
                    "file_path": rel_path,
                    "content_hash": content_hash,
                    "note_id": note_id,
                }
            )

        if not batch_contents:
            continue

        embeddings = get_jina_embeddings_batch(
            batch_contents,
            jina_api_key_to_use=jina_api_key_to_use,
            jina_model_name_to_use=jina_model_name_to_use,
        )
        for info, emb in zip(batch_file_info, embeddings):
            rel_path = info["file_path"]
            note_id_val = info["note_id"]
            cur.execute(
                """
                INSERT INTO notes (note_id, file_name, content_hash, embedding)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(note_id) DO UPDATE SET
                    file_name = excluded.file_name,
                    content_hash = excluded.content_hash,
                    embedding    = excluded.embedding
                """,
                (
                    note_id_val,
                    rel_path,
                    info["content_hash"],
                    json.dumps(emb) if emb else None,
                ),
            )
            all_files_data_for_return[rel_path] = {
                "hash": info["content_hash"],
                "embedding": emb,
                "note_id": note_id_val,
            }
            if emb:
                embedded_count += 1
            processed_files_this_run += 1

        conn.commit()

    # 更新元数据
    cur.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("generated_at_utc", _dt.datetime.now(_dt.timezone.utc).isoformat()),
    )
    cur.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("jina_model_name", jina_model_name_to_use),
    )
    conn.commit()
    conn.close()

    logger.info(
        "嵌入完成：共处理 %s 文件，生成/更新 %s 嵌入。", processed_files_this_run, embedded_count
    )

    return {
        "_metadata": {
            "generated_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "jina_model_name": jina_model_name_to_use,
            "script_version": "orchestrator.embed_pipeline",
        },
        "files": all_files_data_for_return,
    }


__all__ = ["process_and_embed_notes"] 