"""Markdown note loading helpers.

提供：
* read_markdown_with_frontmatter
* list_markdown_files
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from python_src.utils.logger import get_logger

logger = get_logger(__name__)


def read_markdown_with_frontmatter(file_path: str) -> Tuple[str, Dict, str]:
    """读取 Markdown 文件并分离 front-matter 与正文。
    
    同时处理 HASH_BOUNDARY_MARKER，只返回边界标记之前的正文内容。

    返回 (body_content, frontmatter_dict, raw_frontmatter_str)。
    若文件不含 front-matter，则字典与字符串均为空。"""
    from python_src.hash_utils.hasher import HASH_BOUNDARY_MARKER
    
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    full_content = path.read_text(encoding="utf-8")
    frontmatter_str = ""
    frontmatter_dict: Dict = {}
    body_content = full_content

    # Front-matter 检测
    if full_content.startswith("---"):
        lines = full_content.split("\n")
        frontmatter_end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), -1)
        if frontmatter_end != -1:
            frontmatter_lines = lines[1:frontmatter_end]
            frontmatter_block = "\n".join(frontmatter_lines)
            body_content = "\n".join(lines[frontmatter_end + 1 :])
            frontmatter_str = frontmatter_block
            try:
                frontmatter_dict = yaml.safe_load(frontmatter_block) or {}
            except yaml.YAMLError as exc:
                logger.warning("解析 front-matter 失败 (%s): %s", file_path, exc)
                frontmatter_dict = {}
    
    # 处理哈希边界标记，只保留边界标记之前的内容
    boundary_idx = body_content.find(HASH_BOUNDARY_MARKER)
    if boundary_idx != -1:
        body_content = body_content[:boundary_idx].rstrip()
    
    return body_content, frontmatter_dict, frontmatter_str



def list_markdown_files(
    scan_directory_abs: str,
    project_root_abs: str,
    excluded_folders: List[str] | None = None,
    excluded_files_patterns: List[str] | None = None,
) -> List[str]:
    """遍历目录，返回相对于 project_root 的 .md 文件路径列表。"""
    excluded_folders = [ef.lower() for ef in (excluded_folders or [])]
    excluded_files_patterns = excluded_files_patterns or []

    if not os.path.isdir(scan_directory_abs):
        logger.error("扫描路径 %s 不是有效文件夹。", scan_directory_abs)
        return []

    # Compile glob patterns once
    compiled_patterns: List[re.Pattern[str]] = []
    for pat in excluded_files_patterns:
        try:
            compiled_patterns.append(re.compile(fnmatch.translate(pat), re.IGNORECASE))
        except re.error as exc:
            logger.warning("无效的排除文件模式 '%s': %s", pat, exc)

    markdown_files: List[str] = []

    for root, dirs, files in os.walk(scan_directory_abs, topdown=True):
        dirs[:] = [d for d in dirs if d.lower() not in excluded_folders]

        for fname in files:
            if not fname.endswith(".md"):
                continue

            # filename pattern filter
            if any(p.search(fname.lower()) or p.search(os.path.splitext(fname)[0].lower()) for p in compiled_patterns):
                continue

            file_abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(file_abs_path, project_root_abs).replace(os.sep, "/")
            # Folder exclusion (intermediate parts)
            parts = rel_path.lower().split("/")[:-1]
            if any(p in excluded_folders for p in parts):
                continue
            markdown_files.append(rel_path)

    return markdown_files


__all__ = [
    "read_markdown_with_frontmatter",
    "list_markdown_files",
]
