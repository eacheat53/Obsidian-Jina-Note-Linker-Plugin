"""Note output helpers (write & export)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict

import yaml

from python_src.utils.logger import get_logger
from python_src.config import (
    DEFAULT_MAIN_DB_FILE_NAME,
)
from python_src.hash_utils.hasher import HASH_BOUNDARY_MARKER

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 文件写入
# ---------------------------------------------------------------------------

def write_markdown_with_frontmatter(file_path: str, frontmatter: Dict, body: str) -> None:
    """将 front-matter 与正文组合写入 Markdown 文件，保留哈希边界标记后的内容。"""
    try:
        # 检查文件是否存在，如果存在则读取原内容，获取哈希边界后的内容
        original_content = ""
        original_post_boundary_content = ""
        
        if os.path.exists(file_path):
            try:
                original_content = Path(file_path).read_text(encoding="utf-8")
                boundary_idx = original_content.find(HASH_BOUNDARY_MARKER)
                
                if boundary_idx != -1:
                    # 保存哈希边界后的内容
                    boundary_end_idx = boundary_idx + len(HASH_BOUNDARY_MARKER)
                    original_post_boundary_content = original_content[boundary_end_idx:]
                    logger.debug("已保存哈希边界标记后的内容用于保留")
            except Exception as e:
                logger.warning(f"读取原文件时出错: {e}, 将不保留边界后内容")
        
        # 构建新文件内容
        output = ""
        if frontmatter:
            fm_dump = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
            output = f"---\n{fm_dump.strip()}\n---\n"

        # 防止正文首行空白
        body_clean = body.lstrip("\n")
        output += body_clean
        
        # 检查当前body是否已经包含哈希边界标记
        if HASH_BOUNDARY_MARKER not in body:
            # 如果body中没有哈希边界标记，但原文件中有，则添加标记和之后的内容
            if original_post_boundary_content:
                output = output.rstrip() + "\n\n" + HASH_BOUNDARY_MARKER + original_post_boundary_content
        
        path = Path(file_path)
        path.write_text(output, encoding="utf-8")
        logger.debug(f"写入文件 {file_path} 完成，已保留哈希边界后内容")
        
    except Exception as e:
        logger.error(f"写入文件 {file_path} 时出错: {e}")
        # 出错时仍尝试写入基本内容
        try:
            basic_output = ""
            if frontmatter:
                fm_dump = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
                basic_output = f"---\n{fm_dump.strip()}\n---\n"
            basic_output += body.lstrip("\n")
            Path(file_path).write_text(basic_output, encoding="utf-8")
        except:
            logger.critical(f"写入文件 {file_path} 的基本内容也失败")


# ---------------------------------------------------------------------------
# 导出 JSON
# ---------------------------------------------------------------------------

def export_embeddings_to_json(db_path: str, json_output_path: str) -> bool:
    """从嵌入 SQLite 数据库导出 JSON（兼容旧版插件）。"""
    logger.info("[导出] 导出嵌入库 %s -> %s", db_path, json_output_path)

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        metadata: Dict[str, str] = {
            key: value for key, value in cur.execute("SELECT key, value FROM metadata")
        }

        files_data: Dict[str, Dict] = {}
        for row in cur.execute(
            """
            SELECT file_path, content_hash, embedding, processed_content
            FROM file_embeddings
            """
        ):
            file_path, content_hash, embedding_json, processed_content = row
            embedding = json.loads(embedding_json) if embedding_json else None
            files_data[file_path] = {
                "hash": content_hash,
                "embedding": embedding,
                "processed_content": processed_content,
            }

        output_data = {
            "_metadata": {
                "generated_at_utc": metadata.get("created_at"),
                "jina_model_name": metadata.get("jina_model_name", "unknown"),
                "script_version": "2.0_plugin_compatible_json_export",
                "exported_from": os.path.basename(db_path),
                "storage_strategy": "sqlite_dual_db",
            },
            "files": files_data,
        }

        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
        Path(json_output_path).write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("[成功] 成功导出 %s 个文件嵌入", len(files_data))
        conn.close()
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("[错误] 导出嵌入 JSON 失败: %s", exc)
        return False


def export_ai_scores_to_json(
    project_root_abs: str,
    output_dir_abs: str,
    export_dir_name: str = ".jina-linker",
    min_score: int = 7,
) -> None:
    """导出 AI 评分数据为 JSON（新格式：ai_scores_by_source）。"""
    logger.info("[导出] 正在导出 AI 评分数据到 JSON...")

    json_dir = Path(project_root_abs) / export_dir_name
    json_dir.mkdir(parents=True, exist_ok=True)

    ai_scores_db = Path(output_dir_abs) / DEFAULT_MAIN_DB_FILE_NAME
    ai_scores_json = json_dir / "ai_scores.json"
    if not ai_scores_db.exists():
        logger.warning("AI scores DB 不存在: %s", ai_scores_db)
        return

    # 读取并分组
    conn = sqlite3.connect(ai_scores_db)
    cur = conn.cursor()
    source_map: Dict[str, list] = {}
    for src, tgt, score in cur.execute(
        "SELECT file_name_a, file_name_b, ai_score FROM scores WHERE ai_score >= ?",
        (min_score,),
    ):
        source_map.setdefault(src, []).append([tgt, score])

    # 按分数排序（降序）
    for lst in source_map.values():
        lst.sort(key=lambda x: x[1], reverse=True)

    output = {
        "_metadata": {
            "description": "AI scores (grouped by source)",
            "exported_from": ai_scores_db.name,
        },
        "ai_scores_by_source": source_map,
    }

    ai_scores_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    logger.info("[成功] 导出 %s 源笔记的 AI 评分", len(source_map))


def export_ai_tags_to_json(
    project_root_abs: str,
    output_dir_abs: str,
    export_dir_name: str = ".jina-linker",
) -> None:
    """导出 note_tags 为 JSON。"""
    logger.info("[导出] 正在导出 AI 标签到 JSON…")

    json_dir = Path(project_root_abs) / export_dir_name
    json_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(output_dir_abs) / DEFAULT_MAIN_DB_FILE_NAME
    tags_json = json_dir / "ai_tags.json"
    if not db_path.exists():
        logger.warning("DB 不存在: %s", db_path)
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    tags_map: Dict[str, list] = {}
    for note_id, tag in cur.execute("SELECT note_id, tag FROM note_tags"):
        cur2 = conn.execute("SELECT file_name FROM notes WHERE note_id = ?", (note_id,))
        row = cur2.fetchone()
        if not row:
            continue
        file_name = row[0]
        tags_map.setdefault(file_name, []).append(tag)

    output = {
        "_metadata": {
            "description": "AI generated tags (grouped by note)",
            "exported_from": db_path.name,
        },
        "ai_tags_by_note": tags_map,
    }

    tags_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    logger.info("[成功] 导出 %s 篇笔记标签", len(tags_map))

__all__ = [
    "write_markdown_with_frontmatter",
    "export_embeddings_to_json",
    "export_ai_scores_to_json",
    "export_ai_tags_to_json",
]
