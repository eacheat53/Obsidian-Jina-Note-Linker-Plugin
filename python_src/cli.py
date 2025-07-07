"""CLI entry that uses new orchestrator pipelines."""
from __future__ import annotations

import argparse
import os
import time

from python_src.config import (
    DEFAULT_AI_SCORES_FILE_NAME,
    DEFAULT_EMBEDDINGS_FILE_NAME,
    DEFAULT_SIMILARITY_THRESHOLD,
)
from python_src.db.schema import EMBEDDINGS_DB_SCHEMA, AI_SCORES_DB_SCHEMA
from python_src.embeddings.similarity import generate_candidate_pairs
from python_src.io.note_loader import list_markdown_files
from python_src.io.output_writer import export_ai_scores_to_json
from python_src.orchestrator.embed_pipeline import process_and_embed_notes
from python_src.orchestrator.link_scoring import score_candidates
from python_src.utils.db import initialize_database
from python_src.utils.logger import init_logger, get_logger
from python_src.hash_utils.hasher import HASH_BOUNDARY_MARKER

init_logger()
logger = get_logger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Jina AI 处理工具（全新架构）")
    p.add_argument("--project_root", required=True, help="项目根目录绝对路径")
    p.add_argument("--output_dir", default=".", help="输出数据库目录（相对 project_root）")
    p.add_argument("--jina_api_key", required=True, help="Jina API Key")
    p.add_argument("--jina_model_name", default="jina-embeddings-v3")
    p.add_argument("--max_chars_for_jina", type=int, default=8000)

    p.add_argument("--ai_provider", default="openai")
    p.add_argument("--ai_api_url", default="")
    p.add_argument("--ai_api_key", default="")
    p.add_argument("--ai_model_name", default="gpt-4o-mini")
    p.add_argument("--max_content_length_for_ai", type=int, default=5000)
    p.add_argument("--ai_scoring_mode", choices=["force", "smart", "skip"], default="smart")

    p.add_argument("--similarity_threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    p.add_argument("--scan_target_folders", nargs="*", default=[])
    p.add_argument("--excluded_folders", nargs="*", default=[])
    p.add_argument("--excluded_files_patterns", nargs="*", default=[])

    p.add_argument("--embedding_batch_size", type=int, default=10)
    p.add_argument("--ai_scoring_batch_size", type=int, default=5)
    p.add_argument("--hash_boundary_marker", default=HASH_BOUNDARY_MARKER,
                   help="哈希边界标记，用于分隔内容计算哈希的部分")
    p.add_argument("--max_candidates_per_source_for_ai_scoring", type=int, default=20,
                   help="每个源文件最多发送给 AI 评分的候选数量")

    p.add_argument("--export_json", action="store_true", help="导出AI评分数据到JSON")
    p.add_argument("--export_json_only", action="store_true", help="仅导出AI评分数据到JSON，不执行其他处理")
    p.add_argument("--no_export_json", action="store_true", help="不导出AI评分数据到JSON")
    return p


def main() -> None:  # pragma: no cover
    parser = build_arg_parser()
    args = parser.parse_args()

    start_time = time.time()

    project_root_abs = os.path.abspath(args.project_root)
    output_dir_abs = os.path.join(project_root_abs, args.output_dir)
    os.makedirs(output_dir_abs, exist_ok=True)

    if args.export_json_only:
        export_ai_scores_to_json(project_root_abs, output_dir_abs)
        return

    embeddings_db_path = os.path.join(output_dir_abs, DEFAULT_EMBEDDINGS_FILE_NAME)
    ai_scores_db_path = os.path.join(output_dir_abs, DEFAULT_AI_SCORES_FILE_NAME)

    initialize_database(embeddings_db_path, EMBEDDINGS_DB_SCHEMA)
    initialize_database(ai_scores_db_path, AI_SCORES_DB_SCHEMA)

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

    # Embeddings
    embeddings_data = process_and_embed_notes(
        project_root_abs,
        markdown_files,
        embeddings_db_path,
        jina_api_key_to_use=args.jina_api_key,
        jina_model_name_to_use=args.jina_model_name,
        max_chars_for_jina_to_use=args.max_chars_for_jina,
        embedding_batch_size=args.embedding_batch_size,
    )

    # Candidate pairs
    candidates = generate_candidate_pairs(embeddings_data, args.similarity_threshold)

    if (
        args.ai_api_key
        and args.ai_scoring_mode != "skip"
        and candidates
    ):
        score_candidates(
            candidates,
            project_root_abs,
            embeddings_db_path,
            ai_scores_db_path,
            ai_provider=args.ai_provider,
            ai_api_url=args.ai_api_url,
            ai_api_key=args.ai_api_key,
            ai_model_name=args.ai_model_name,
            max_content_length_for_ai_to_use=args.max_content_length_for_ai,
            force_rescore=(args.ai_scoring_mode == "force"),
            ai_scoring_batch_size=args.ai_scoring_batch_size,
        )

    if not args.no_export_json or args.export_json:
        export_ai_scores_to_json(project_root_abs, output_dir_abs)

    logger.info("流程完成，总耗时 %.2fs", time.time() - start_time)


if __name__ == "__main__":  # pragma: no cover
    main()
