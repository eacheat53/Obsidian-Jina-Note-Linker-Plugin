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

        ai_scores: Dict[str, Dict] = {}
        for (
            src_path,
            tgt_path,
            ai_score,
            jina_sim,
            last_scored,
            rel_key,
            key_type,
        ) in cur.execute(
            """
            SELECT source_path, target_path, ai_score, jina_similarity, last_scored, relationship_key, key_type
            FROM ai_relationships
            """
        ):
            if not rel_key:
                rel_key = f"{src_path}|{tgt_path}"
            ai_scores[rel_key] = {
                "source_path": src_path,
                "target_path": tgt_path,
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

def upgrade_ai_scores_schema(db_path: str) -> bool:
    """升级AI评分数据库结构以支持新的ai_responses表。
    
    Args:
        db_path: AI评分数据库路径
        
    Returns:
        bool: 是否执行了升级操作
    """
    if not os.path.exists(db_path):
        logger.warning("数据库文件不存在: %s，跳过结构升级", db_path)
        return False
    
    logger.info(f"开始检查数据库结构: {db_path}")
        
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    
    try:
        # ---- 无论如何都确保新列/新索引存在 ----
        cur.execute("PRAGMA table_info(ai_relationships)")
        existing_cols = {row[1] for row in cur.fetchall()}

        # 新列
        if "source_hash" not in existing_cols:
            logger.info("添加 source_hash 列到 ai_relationships 表")
            cur.execute("ALTER TABLE ai_relationships ADD COLUMN source_hash TEXT")
        if "target_hash" not in existing_cols:
            logger.info("添加 target_hash 列到 ai_relationships 表")
            cur.execute("ALTER TABLE ai_relationships ADD COLUMN target_hash TEXT")
        if "source_path" not in existing_cols:
            logger.info("添加 source_path 列到 ai_relationships 表")
            cur.execute("ALTER TABLE ai_relationships ADD COLUMN source_path TEXT")
        if "target_path" not in existing_cols:
            logger.info("添加 target_path 列到 ai_relationships 表")
            cur.execute("ALTER TABLE ai_relationships ADD COLUMN target_path TEXT")

        # 创建或替换新的唯一索引 (sqlite 不支持 ALTER UNIQUE, 需先尝试创建)
        try:
            cur.execute("CREATE UNIQUE INDEX idx_ai_relations_unique ON ai_relationships(source_path, target_path, source_hash, target_hash)")
            logger.info("已创建 idx_ai_relations_unique 索引")
        except sqlite3.OperationalError:
            # 索引已存在
            pass

        # 检查ai_responses表是否存在
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_responses'")
        table_exists = cur.fetchone() is not None
        
        if not table_exists:
            logger.info("升级AI评分数据库结构，添加ai_responses表...")
            
            # 创建ai_responses表
            cur.execute("""
            CREATE TABLE ai_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,          -- 批次ID，用于识别同一组请求的响应
                ai_provider TEXT NOT NULL,       -- AI提供商名称
                model_name TEXT NOT NULL,        -- 使用的模型名称
                request_content TEXT,            -- 请求内容
                response_content TEXT,           -- 完整的响应内容
                prompt_type TEXT,                -- 提示词类型（默认/自定义）
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # 创建索引
            cur.execute("CREATE INDEX idx_ai_responses_batch ON ai_responses(batch_id)")
            
            # 更新元数据
            cur.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", "1.1"),
            )
            
            conn.commit()
            logger.info("数据库结构升级成功: ai_responses表已创建")
            
            # 验证表是否成功创建
            cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='ai_responses'")
            if cur.fetchone()[0] == 1:
                logger.info("验证成功: ai_responses表已存在")
            else:
                logger.error("验证失败: ai_responses表创建失败")
            
            # 若旧表使用 *_file_id 列而无 source_path，则迁移数据
            if "source_path" not in existing_cols:
                logger.info("迁移旧 ai_relationships 结构，添加 source_path/target_path 并填充")
                cur.execute("ALTER TABLE ai_relationships ADD COLUMN source_path TEXT")
                cur.execute("ALTER TABLE ai_relationships ADD COLUMN target_path TEXT")
                # 回填数据
                cur.execute(
                    """
                    UPDATE ai_relationships
                    SET source_path = (
                        SELECT file_path FROM file_paths WHERE id = ai_relationships.source_file_id
                    ),
                        target_path = (
                        SELECT file_path FROM file_paths WHERE id = ai_relationships.target_file_id
                    )
                    WHERE source_path IS NULL OR target_path IS NULL
                    """
                )
                conn.commit()
            
            return True
        else:
            logger.info("ai_responses表已存在，无需升级")
            return False
    
    except Exception as e:
        logger.error("升级数据库结构失败: %s", e)
        import traceback
        logger.error("详细错误: %s", traceback.format_exc())
        conn.rollback()
        return False
    finally:
        conn.close()

def run_migration_process(project_root_abs: str, output_dir_abs: str) -> None:
    """执行整体迁移流程。"""
    logger.info("[开始] Starting JSON -> SQLite migration (stub)...")
    migrate_embeddings_json_to_sqlite(project_root_abs, output_dir_abs)
    migrate_ai_scores_json_to_sqlite(project_root_abs, output_dir_abs)
    
    # 检查并升级AI评分数据库结构
    ai_scores_db_path = os.path.join(output_dir_abs, DEFAULT_AI_SCORES_FILE_NAME)
    if os.path.exists(ai_scores_db_path):
        upgrade_ai_scores_schema(ai_scores_db_path)
        
    logger.info("[完成] Migration process completed.")


__all__ = [
    "sqlite_to_json",
    "migrate_embeddings_json_to_sqlite",
    "migrate_ai_scores_json_to_sqlite",
    "upgrade_ai_scores_schema",
    "run_migration_process",
]
