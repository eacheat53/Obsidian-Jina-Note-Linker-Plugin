"""JSON <-> SQLite 数据迁移助手。"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from pathlib import Path
from typing import Dict

from python_src.utils.logger import get_logger
from python_src.config import (
    DEFAULT_EMBEDDINGS_FILE_NAME,
    DEFAULT_AI_SCORES_FILE_NAME,
)
from python_src.utils.db import get_db_connection, initialize_database
from python_src.db.schema import EMBEDDINGS_DB_SCHEMA, AI_SCORES_DB_SCHEMA

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# SQLite → JSON 导出
# ---------------------------------------------------------------------------

def sqlite_to_json(db_path: str, json_output_path: str, output_dir_name: str = ".jina-linker") -> bool:
    """将 SQLite 数据库导出为 JSON 文件（旧版兼容）。"""
    logger.info("[导出] 导出数据库 %s -> %s", db_path, json_output_path)
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        metadata: Dict[str, str] = {k: v for k, v in cur.execute("SELECT key, value FROM metadata")}

        file_id_to_path: Dict[int, str] = {fid: path for fid, path in cur.execute("SELECT id, file_path FROM file_paths")}

        ai_scores: Dict[str, Dict] = {}
        for (
            source_id,
            target_id,
            ai_score,
            jina_sim,
            last_scored,
            rel_key,
            key_type,
        ) in cur.execute(
            """
            SELECT source_file_id, target_file_id, ai_score, jina_similarity, last_scored, relationship_key, key_type
            FROM ai_relationships
            """
        ):
            if not rel_key:
                rel_key = f"{file_id_to_path.get(source_id)}|{file_id_to_path.get(target_id)}"
            ai_scores[rel_key] = {
                "source_path": file_id_to_path.get(source_id),
                "target_path": file_id_to_path.get(target_id),
                "ai_score": ai_score,
                "jina_similarity": jina_sim,
                "last_scored": last_scored or _dt.datetime.now().isoformat(),
                "key_type": key_type or "full_path",
            }

        data = {
            "_metadata": {
                "description": "AI scores (exported)",
                "last_updated": _dt.datetime.now().isoformat(),
                "total_relationships": len(ai_scores),
                "exported_from": os.path.basename(db_path),
                "storage_strategy": "sqlite_dual_db",
                "original_metadata": metadata,
            },
            "ai_scores": ai_scores,
        }

        Path(json_output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[成功] 导出 %s 条 AI 关系", len(ai_scores))
        conn.close()
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("[错误] 导出 JSON 失败: %s", exc)
        return False

# ---------------------------------------------------------------------------
# JSON → SQLite 迁移（简化）
# ---------------------------------------------------------------------------

def migrate_embeddings_json_to_sqlite(project_root_abs: str, output_dir_abs: str) -> None:
    """将 jina_embeddings.json 数据迁移到 SQLite 格式数据库。"""
    json_dir = os.path.join(project_root_abs, ".Jina-AI-Linker-Output")
    json_path = os.path.join(json_dir, "jina_embeddings.json")
    db_path = os.path.join(output_dir_abs, DEFAULT_EMBEDDINGS_FILE_NAME)

    if not os.path.exists(json_path):
        logger.warning("JSON file not found: %s, skipping embeddings migration", json_path)
        return

    if os.path.exists(db_path):
        logger.info("Database %s already exists, deleting for fresh migration", db_path)
        os.remove(db_path)

    initialize_database(db_path, EMBEDDINGS_DB_SCHEMA)
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    metadata = data.get("_metadata", {})
    files_data = data.get("files", {})

    logger.info("Migrating embeddings metadata…")
    if metadata:
        cur.execute(
            "UPDATE metadata SET value = ? WHERE key = 'jina_model_name'",
            (metadata.get("jina_model_name", "unknown"),),
        )
        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("generated_at_utc", metadata.get("generated_at_utc", "")),
        )

    logger.info("Migrating %s embeddings…", len(files_data))
    rows = []
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    for fp, det in files_data.items():
        emb = json.dumps(det.get("embedding")) if det.get("embedding") else None
        dim = len(det["embedding"]) if det.get("embedding") else 0
        rows.append(
            (
                fp,
                det.get("hash", ""),
                emb,
                det.get("processed_content", ""),
                dim,
                now_iso,
            )
        )

    cur.executemany(
        """
        INSERT INTO file_embeddings (file_path, content_hash, embedding, processed_content, embedding_dimension, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    conn.commit()
    conn.close()
    logger.info("[成功] Embeddings migration complete: %s rows", len(rows))

def migrate_ai_scores_json_to_sqlite(project_root_abs: str, output_dir_abs: str) -> None:
    """将 ai_scores.json 数据迁移到 SQLite。"""
    json_dir = os.path.join(project_root_abs, ".Jina-AI-Linker-Output")
    json_path = os.path.join(json_dir, "ai_scores.json")
    db_path = os.path.join(output_dir_abs, DEFAULT_AI_SCORES_FILE_NAME)

    if not os.path.exists(json_path):
        logger.warning("JSON file not found: %s, skipping AI scores migration", json_path)
        return

    if os.path.exists(db_path):
        logger.info("Database %s already exists, deleting for fresh migration", db_path)
        os.remove(db_path)

    initialize_database(db_path, AI_SCORES_DB_SCHEMA)
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    metadata = data.get("_metadata", {})
    ai_scores = data.get("ai_scores", {})

    if metadata:
        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("description", metadata.get("description", "")),
        )
        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("last_updated", metadata.get("last_updated", "")),
        )
        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("total_relationships", str(metadata.get("total_relationships", 0))),
        )
        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("storage_strategy", "sqlite_dual_db"),
        )

    logger.info("Migrating %s AI score relationships…", len(ai_scores))

    # insert file paths
    paths = {(e["source_path"],) for e in ai_scores.values()} | {(e["target_path"],) for e in ai_scores.values()}
    cur.executemany("INSERT OR IGNORE INTO file_paths (file_path) VALUES (?)", list(paths))

    cur.execute("SELECT id, file_path FROM file_paths")
    path_to_id = {p: i for i, p in cur.fetchall()}

    rows = []
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    for key, e in ai_scores.items():
        src_id = path_to_id.get(e["source_path"])
        tgt_id = path_to_id.get(e["target_path"])
        if src_id is None or tgt_id is None:
            continue
        rows.append(
            (
                src_id,
                tgt_id,
                e.get("ai_score"),
                e.get("jina_similarity"),
                e.get("last_scored"),
                key,
                e.get("key_type", "full_path"),
                now_iso,
            )
        )

    cur.executemany(
        """
        INSERT INTO ai_relationships (source_file_id, target_file_id, ai_score, jina_similarity, last_scored, relationship_key, key_type, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    conn.commit()
    conn.close()
    logger.info("[成功] AI scores migration complete: %s rows", len(rows))

def run_migration_process(project_root_abs: str, output_dir_abs: str) -> None:
    """执行整体迁移流程。"""
    logger.info("[开始] Starting JSON -> SQLite migration (stub)...")
    migrate_embeddings_json_to_sqlite(project_root_abs, output_dir_abs)
    migrate_ai_scores_json_to_sqlite(project_root_abs, output_dir_abs)
    logger.info("[完成] Migration process completed.")


__all__ = [
    "sqlite_to_json",
    "migrate_embeddings_json_to_sqlite",
    "migrate_ai_scores_json_to_sqlite",
    "run_migration_process",
]
