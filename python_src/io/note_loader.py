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
    """遍历目录，返回相对于 project_root 的 .md 文件路径列表。
    
    增强的排除功能:
    1. excluded_folders 支持两种格式:
       - 单一文件夹名: 如 "Scripts"、".trash" (不带路径)
       - 完整路径格式: 如 "20_巴别塔/音乐" (包含路径分隔符)
       
    2. excluded_files_patterns 支持两种模式:
       - 纯文件名模式: 如 "*.excalidraw"、"template*.md" (不含路径)
       - 路径模式: 如 "20_巴别塔/音乐/*.md" (包含路径分隔符)
    
    当使用路径模式时，匹配检查的是完整的相对路径。
    
    新增: 支持单个文件路径作为输入，而不仅仅是文件夹。
    """
    excluded_folders = excluded_folders or []
    excluded_files_patterns = excluded_files_patterns or []
    
    # 检查是否为文件路径
    if os.path.isfile(scan_directory_abs):
        # 如果输入是文件而不是目录，直接返回该文件的相对路径
        if scan_directory_abs.lower().endswith('.md'):
            rel_path = os.path.relpath(scan_directory_abs, project_root_abs).replace(os.sep, "/")
            return [rel_path]
        else:
            logger.warning("提供的路径是文件但不是Markdown文件: %s", scan_directory_abs)
            return []
    
    # 处理排除文件夹：支持完整路径和单独文件夹名
    simple_folders = []  # 单一文件夹名
    path_folders = []    # 包含路径的文件夹
    
    for ef in excluded_folders:
        ef = ef.lower().strip()
        if ef:
            if '/' in ef:
                # 是一个路径，用于完整路径匹配
                path_folders.append(ef)
            else:
                # 是一个单独的文件夹名
                simple_folders.append(ef)
    
    if not os.path.isdir(scan_directory_abs):
        logger.error("扫描路径 %s 不是有效文件夹或文件。", scan_directory_abs)
        return []

    # Compile glob patterns for file exclusion
    file_patterns = []
    path_patterns = []
    for pat in excluded_files_patterns:
        pat = pat.strip()
        if not pat:
            continue
            
        try:
            if '/' in pat:
                # 包含路径的模式，用于完整路径匹配
                path_patterns.append(re.compile(fnmatch.translate(pat), re.IGNORECASE))
            else:
                # 仅文件名的模式
                file_patterns.append(re.compile(fnmatch.translate(pat), re.IGNORECASE))
        except re.error as exc:
            logger.warning("无效的排除文件模式 '%s': %s", pat, exc)

    markdown_files: List[str] = []

    for root, dirs, files in os.walk(scan_directory_abs, topdown=True):
        # 排除单一文件夹名
        dirs[:] = [d for d in dirs if d.lower() not in simple_folders]
        
        # 排除特定路径下的文件夹
        rel_dir = os.path.relpath(root, project_root_abs).replace(os.sep, "/")
        if rel_dir == '.':
            rel_dir = ''
            
        # 检查当前目录是否匹配任何路径排除模式
        if any(rel_dir.lower().startswith(path_folder) or rel_dir.lower() == path_folder 
               for path_folder in path_folders):
            dirs[:] = []  # 清空子目录列表，不再深入
            continue

        for fname in files:
            if not fname.endswith(".md"):
                continue

            # 排除特定文件名模式
            basename = os.path.splitext(fname)[0].lower()
            if any(p.search(fname.lower()) or p.search(basename) for p in file_patterns):
                continue

            # 生成相对路径
            file_abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(file_abs_path, project_root_abs).replace(os.sep, "/")
            
            # 检查完整路径是否匹配任何路径模式
            if any(p.search(rel_path.lower()) for p in path_patterns):
                continue
                
            # 确保不在排除的路径中
            parts = rel_path.split("/")
            should_exclude = False
            for i in range(len(parts) - 1):
                partial_path = "/".join(parts[:i+1]).lower()
                if partial_path in path_folders:
                    should_exclude = True
                    break
            
            if should_exclude:
                continue
                
            markdown_files.append(rel_path)

    return markdown_files


__all__ = [
    "read_markdown_with_frontmatter",
    "list_markdown_files",
]
