"""Python command-line interface for Jina linker.

一个前端和Python脚本通信的CLI层（替代原来的单体main.py）。
"""
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
import logging
import time

# 将项目根目录添加到路径，以便能够导入其他模块
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# 在设置路径后导入项目模块
from python_src.config import (
    DEFAULT_MAIN_DB_FILE_NAME,
    DEFAULT_SIMILARITY_THRESHOLD,
    AI_SCORING_BATCH_SIZE,
    AI_SCORING_MAX_CHARS_PER_NOTE,
    AI_SCORING_MAX_TOTAL_CHARS,
)
from python_src.db.schema import MAIN_DB_SCHEMA
from python_src.embeddings.similarity import generate_candidate_pairs
from python_src.io.note_loader import list_markdown_files
from python_src.io.output_writer import export_ai_scores_to_json, export_ai_tags_to_json
from python_src.orchestrator.embed_pipeline import process_and_embed_notes
from python_src.orchestrator.link_scoring import score_candidates
from python_src.utils.db import initialize_database, list_database_tables, get_db_connection
from python_src.utils.logger import init_logger, get_logger
from python_src.hash_utils.hasher import HASH_BOUNDARY_MARKER
# 不再需要旧版 SQLite 迁移逻辑, 已移除

init_logger()
logger = get_logger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Jina AI 处理工具（全新架构）")
    p.add_argument("--project_root", required=True, help="项目根目录绝对路径")
    p.add_argument("--output_dir", default=".", help="输出数据库目录（相对 project_root）")
    p.add_argument("--jina_api_key", default="", help="Jina API Key (可选，无则跳过嵌入生成)")
    p.add_argument("--jina_model_name", default="jina-embeddings-v3")
    p.add_argument("--max_chars_for_jina", type=int, default=8000)

    p.add_argument("--ai_provider", default="openai")
    p.add_argument("--ai_api_url", default="")
    p.add_argument("--ai_api_key", default="")
    p.add_argument("--ai_model_name", default="gpt-4o-mini")
    p.add_argument("--max_content_length_for_ai", type=int, default=5000)
    p.add_argument("--ai_scoring_mode", choices=["force", "smart", "skip"], default="smart")

    # 添加自定义评分提示词参数
    p.add_argument("--use_custom_scoring_prompt", action="store_true", help="使用自定义评分提示词")
    p.add_argument("--custom_scoring_prompt", default="", help="自定义评分提示词内容")

    p.add_argument("--similarity_threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    p.add_argument("--scan_target_folders", nargs="*", default=[])
    p.add_argument("--excluded_folders", nargs="*", default=[])
    p.add_argument("--excluded_files_patterns", nargs="*", default=[])

    p.add_argument("--embedding_batch_size", type=int, default=10)
    p.add_argument("--ai_scoring_batch_size", type=int, default=AI_SCORING_BATCH_SIZE)
    p.add_argument("--max_chars_per_note", type=int, default=AI_SCORING_MAX_CHARS_PER_NOTE,
                   help="每个笔记在AI评分时的最大字符数")
    p.add_argument("--max_total_chars_per_request", type=int, default=AI_SCORING_MAX_TOTAL_CHARS,
                   help="每个API批量请求的最大总字符数")
    p.add_argument("--hash_boundary_marker", default=HASH_BOUNDARY_MARKER,
                   help="哈希边界标记，用于分隔内容计算哈希的部分")
    p.add_argument("--max_candidates_per_source_for_ai_scoring", type=int, default=20,
                   help="每个源文件最多发送给 AI 评分的候选数量")

    # 新增日志级别参数
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                   help="日志级别，默认为 INFO")

    p.add_argument("--export_json", action="store_true", help="导出AI评分数据到JSON")
    p.add_argument("--export_json_only", action="store_true", help="仅导出AI评分数据到JSON，不执行其他处理")
    p.add_argument("--no_export_json", action="store_true", help="不导出AI评分数据到JSON")
    # 标签生成
    p.add_argument("--tags_mode", choices=["force","smart","skip"], default="skip",
                   help="AI 标签生成模式: force=重新生成, smart=仅新笔记, skip=跳过")
    p.add_argument("--save_api_responses", action="store_true", default=True,
                   help="是否保存API请求和响应到数据库中")
    p.add_argument("--test_ai_responses_db", action="store_true", help="测试ai_responses表是否可正常使用")

    # 为兼容旧前端，保留 --min_ai_score 参数（仅用于导出 JSON 时过滤阈值）
    p.add_argument("--min_ai_score", type=int, default=7,
                   help="导出 JSON 时保留的最低 AI 分数阈值")
    return p


def main() -> None:  # pragma: no cover
    parser = build_arg_parser()
    args = parser.parse_args()

    # 根据 --log-level 重新初始化 logger（覆盖默认 INFO）
    init_logger(args.log_level.upper())

    start_time = time.time()

    project_root_abs = os.path.abspath(args.project_root)
    output_dir_abs = os.path.join(project_root_abs, args.output_dir)
    os.makedirs(output_dir_abs, exist_ok=True)

    if args.export_json_only:
        export_ai_scores_to_json(project_root_abs, output_dir_abs, min_score=args.min_ai_score)
        return

    main_db_path = os.path.join(output_dir_abs, DEFAULT_MAIN_DB_FILE_NAME)

    # 若数据库不存在则初始化结构
    initialize_database(main_db_path, MAIN_DB_SCHEMA)

    # 列出表并确保最新结构
    list_database_tables(main_db_path)

    from python_src.utils.db import check_table_exists
    missing_tables = []
    for tbl in ("note_tags", "ai_responses"):
        if not check_table_exists(main_db_path, tbl):
            missing_tables.append(tbl)

    if missing_tables:
        logger.info("检测到缺失表 %s, 将更新数据库结构", ", ".join(missing_tables))
        import sqlite3 as _sql
        conn_fix = _sql.connect(main_db_path)
        try:
            conn_fix.executescript(MAIN_DB_SCHEMA)
            conn_fix.commit()
            logger.info("已执行 MAIN_DB_SCHEMA 以补齐缺失表")
        finally:
            conn_fix.close()

    # 测试ai_responses表
    if args.test_ai_responses_db:
        logger.info("测试ai_responses表...")
        conn = get_db_connection(main_db_path)
        try:
            # 插入测试数据
            test_batch_id = f"test_{int(time.time())}"
            conn.execute(
                """
                INSERT INTO ai_responses (
                    batch_id, ai_provider, model_name, request_content, response_content, prompt_type
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (test_batch_id, "test", "test-model", "测试请求内容", "测试响应内容", "default")
            )
            conn.commit()
            logger.info("测试数据插入成功")

            # 查询测试数据
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_responses WHERE batch_id = ?", (test_batch_id,))
            rows = cursor.fetchall()
            if rows:
                logger.info(f"成功查询到测试数据: {rows}")

                # 清理测试数据
                conn.execute("DELETE FROM ai_responses WHERE batch_id = ?", (test_batch_id,))
                conn.commit()
                logger.info("测试数据已清理")
            else:
                logger.error("未能查询到刚插入的测试数据!")
        except Exception as e:
            logger.error(f"测试ai_responses表失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
        finally:
            conn.close()

        # 验证测试完成后退出
        logger.info("ai_responses表测试完成")
        return

    scan_paths = (
        [os.path.join(project_root_abs, p) for p in args.scan_target_folders]
        if args.scan_target_folders
        else [project_root_abs]
    )

    # Scan markdown files
    markdown_files: list[str] = []
    for p in scan_paths:
        markdown_files.extend(
            list_markdown_files(
                p,
                project_root_abs,
                excluded_folders=args.excluded_folders,
                excluded_files_patterns=args.excluded_files_patterns,
            )
        )
    markdown_files = sorted(set(markdown_files))
    if not markdown_files:
        logger.warning("未找到任何 Markdown 文件，流程结束。")
        return

    embeddings_data = {
        "files": {}
    }

    if args.jina_api_key:
        embeddings_data = process_and_embed_notes(
            project_root_abs,
            markdown_files,
            main_db_path,
            jina_api_key_to_use=args.jina_api_key,
            jina_model_name_to_use=args.jina_model_name,
            max_chars_for_jina_to_use=args.max_chars_for_jina,
            embedding_batch_size=args.embedding_batch_size,
        )
    else:
        logger.warning("未提供 Jina API Key, 跳过嵌入生成阶段。")

    # Candidate pairs
    candidates = generate_candidate_pairs(embeddings_data, args.similarity_threshold) if embeddings_data.get("files") else []

    if args.ai_api_key and args.ai_scoring_mode != "skip" and candidates:
        score_candidates(
            candidates,
            project_root_abs,
            main_db_path,
            ai_provider=args.ai_provider,
            ai_api_url=args.ai_api_url,
            ai_api_key=args.ai_api_key,
            ai_model_name=args.ai_model_name,
            max_content_length_for_ai_to_use=args.max_content_length_for_ai,
            force_rescore=(args.ai_scoring_mode == "force"),
            ai_scoring_batch_size=args.ai_scoring_batch_size,
            custom_scoring_prompt=args.custom_scoring_prompt,
            use_custom_scoring_prompt=args.use_custom_scoring_prompt,
            max_pairs_per_request=args.ai_scoring_batch_size,
            max_chars_per_note=args.max_chars_per_note,
            max_total_chars_per_request=args.max_total_chars_per_request,
            save_api_responses=args.save_api_responses,
        )
    elif not args.ai_api_key:
        logger.warning("未提供 AI API Key, 跳过 AI 评分阶段。")

    if not args.no_export_json or args.export_json:
        export_ai_scores_to_json(project_root_abs, output_dir_abs, min_score=args.min_ai_score)

    # 标签生成
    if args.tags_mode != "skip":
        from python_src.orchestrator.tag_generation import generate_tags  # 局部导入避免循环
        generate_tags(
            project_root_abs,
            main_db_path,
            ai_provider=args.ai_provider,
            ai_api_url=args.ai_api_url,
            ai_api_key=args.ai_api_key,
            ai_model_name=args.ai_model_name,
            max_content_length_for_ai=args.max_content_length_for_ai,
            force_regen=(args.tags_mode == "force"),
            batch_size=args.ai_scoring_batch_size,
            custom_prompt=args.custom_scoring_prompt,
            use_custom_prompt=args.use_custom_scoring_prompt,
            max_chars_per_note=args.max_chars_per_note,
            max_total_chars_per_request=args.max_total_chars_per_request,
            save_api_responses=args.save_api_responses,
        )

        export_ai_tags_to_json(project_root_abs, output_dir_abs)

    logger.info("流程完成，总耗时 %.2fs", time.time() - start_time)


if __name__ == "__main__":  # pragma: no cover
    main()
