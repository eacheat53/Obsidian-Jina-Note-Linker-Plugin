#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量删除Markdown文件中 <!-- HASH_BOUNDARY --> 之后的所有内容
保留YAML frontmatter和哈希边界标记之前的正文内容
"""

import os
import re
import argparse
from pathlib import Path
import shutil
from datetime import datetime

# 哈希边界标记常量
HASH_BOUNDARY_MARKER = "<!-- HASH_BOUNDARY -->"

def process_markdown_file(file_path, backup_dir=None, dry_run=False):
    """
    处理单个Markdown文件，删除哈希边界标记之后的所有内容
    """
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否包含哈希边界标记
        if HASH_BOUNDARY_MARKER not in content:
            return False, "未找到哈希边界标记"
        
        # 找到哈希边界标记的位置
        boundary_index = content.find(HASH_BOUNDARY_MARKER)
        
        # 提取哈希边界标记之前的内容（包括标记本身）
        content_before_boundary = content[:boundary_index + len(HASH_BOUNDARY_MARKER)]
        content_after_boundary = content[boundary_index + len(HASH_BOUNDARY_MARKER):]
        
        # 检查是否有内容需要删除
        if not content_after_boundary.strip():
            return False, "哈希边界标记之后无内容"
        
        # 统计要删除的内容
        lines_after = content_after_boundary.strip().split('\n')
        deleted_lines = len(lines_after)
        
        # 预览要删除的内容
        preview_content = content_after_boundary.strip()
        if len(preview_content) > 200:
            preview_content = preview_content[:200] + "..."
        
        if dry_run:
            return True, f"将删除 {deleted_lines} 行内容: {repr(preview_content)}"
        
        # 创建备份
        if backup_dir:
            backup_path = backup_dir / file_path.name
            shutil.copy2(file_path, backup_path)
        
        # 写入处理后的内容
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content_before_boundary)
        
        return True, f"已删除 {deleted_lines} 行内容"
        
    except Exception as e:
        return False, f"处理失败: {e}"

def find_markdown_files(directory, exclude_patterns=None):
    """
    递归查找所有Markdown文件
    """
    if exclude_patterns is None:
        exclude_patterns = ['.obsidian', '.git', 'node_modules']
    
    markdown_files = []
    for root, dirs, files in os.walk(directory):
        # 排除指定目录
        dirs[:] = [d for d in dirs if not any(pattern in d for pattern in exclude_patterns)]
        
        for file in files:
            if file.endswith('.md'):
                markdown_files.append(Path(root) / file)
    
    return markdown_files

def analyze_file_content(file_path):
    """
    分析文件内容，返回哈希边界标记前后的内容信息
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if HASH_BOUNDARY_MARKER not in content:
            return None, "未找到哈希边界标记"
        
        boundary_index = content.find(HASH_BOUNDARY_MARKER)
        content_before = content[:boundary_index]
        content_after = content[boundary_index + len(HASH_BOUNDARY_MARKER):]
        
        # 分析内容
        lines_before = len(content_before.split('\n'))
        lines_after = len(content_after.strip().split('\n')) if content_after.strip() else 0
        
        # 分析删除内容的类型
        after_content = content_after.strip()
        content_types = []
        
        if '## 建议链接' in after_content:
            content_types.append('建议链接')
        if '<!-- LINKS_START -->' in after_content:
            content_types.append('链接标记')
        if after_content.count('[[') > 0:
            link_count = after_content.count('[[')
            content_types.append(f'{link_count}个链接')
        
        content_type_str = ', '.join(content_types) if content_types else '其他内容'
        
        return {
            'lines_before': lines_before,
            'lines_after': lines_after,
            'content_types': content_type_str,
            'preview': after_content[:100] + "..." if len(after_content) > 100 else after_content
        }, None
        
    except Exception as e:
        return None, f"分析失败: {e}"

def main():
    parser = argparse.ArgumentParser(description='批量删除Markdown文件中哈希边界标记之后的所有内容')
    parser.add_argument('directory', help='要处理的目录路径')
    parser.add_argument('--backup', action='store_true', help='创建备份文件')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际修改文件')
    parser.add_argument('--exclude', 
                       default='.obsidian,.git,node_modules',
                       help='要排除的目录模式，用逗号分隔')
    parser.add_argument('--analyze', action='store_true', help='分析模式，详细显示每个文件的内容结构')
    
    args = parser.parse_args()
    
    # 解析参数
    directory = Path(args.directory)
    exclude_patterns = [pattern.strip() for pattern in args.exclude.split(',')]
    
    if not directory.exists():
        print(f"错误：目录 {directory} 不存在")
        return
    
    # 创建备份目录
    backup_dir = None
    if args.backup and not args.dry_run:
        backup_dir = directory / f"hash_boundary_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(exist_ok=True)
        print(f"备份目录: {backup_dir}")
    
    # 查找所有Markdown文件
    markdown_files = find_markdown_files(directory, exclude_patterns)
    
    if not markdown_files:
        print("未找到任何Markdown文件")
        return
    
    print(f"找到 {len(markdown_files)} 个Markdown文件")
    print(f"哈希边界标记: {HASH_BOUNDARY_MARKER}")
    print(f"排除目录: {', '.join(exclude_patterns)}")
    
    if args.dry_run:
        print("\n=== 预览模式 ===")
    elif args.analyze:
        print("\n=== 分析模式 ===")
    else:
        print("\n=== 开始处理 ===")
    
    processed_count = 0
    modified_count = 0
    total_deleted_lines = 0
    
    for i, file_path in enumerate(markdown_files, 1):
        relative_path = file_path.relative_to(directory)
        print(f"\n[{i}/{len(markdown_files)}] 处理: {relative_path}")
        
        if args.analyze:
            # 分析模式
            analysis, error = analyze_file_content(file_path)
            if error:
                print(f"  ❌ {error}")
                continue
            
            print(f"  📊 边界前: {analysis['lines_before']} 行")
            print(f"  📊 边界后: {analysis['lines_after']} 行")
            print(f"  📋 内容类型: {analysis['content_types']}")
            print(f"  👀 预览: {repr(analysis['preview'])}")
            
            if analysis['lines_after'] > 0:
                processed_count += 1
                total_deleted_lines += analysis['lines_after']
        else:
            # 处理模式
            success, message = process_markdown_file(file_path, backup_dir, args.dry_run)
            
            if success:
                processed_count += 1
                if not args.dry_run:
                    modified_count += 1
                print(f"  ✅ {message}")
                
                # 统计删除的行数
                if "删除" in message and "行" in message:
                    try:
                        lines = int(message.split("删除")[1].split("行")[0].strip())
                        total_deleted_lines += lines
                    except:
                        pass
            else:
                print(f"  ⏭️  跳过: {message}")
    
    # 输出总结
    print(f"\n=== 处理完成 ===")
    print(f"总文件数: {len(markdown_files)}")
    print(f"包含哈希边界标记的文件: {processed_count}")
    
    if args.analyze:
        print(f"总计将删除行数: {total_deleted_lines}")
        print("分析完成。要实际执行删除，请移除 --analyze 参数")
    elif args.dry_run:
        print(f"预计删除行数: {total_deleted_lines}")
        print("预览模式：未实际修改任何文件")
        print("要实际执行修改，请移除 --dry-run 参数")
    else:
        print(f"实际修改的文件: {modified_count}")
        print(f"总计删除行数: {total_deleted_lines}")
        if backup_dir:
            print(f"备份位置: {backup_dir}")

if __name__ == "__main__":
    main()