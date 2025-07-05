#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量清理Markdown文件的YAML frontmatter
只保留指定的键值对：tags, modified, created, cssclasses
"""

import os
import re
import yaml
import argparse
from pathlib import Path
import shutil
from datetime import datetime

def read_markdown_with_frontmatter(file_path):
    """
    读取 Markdown 文件，分离 frontmatter 和正文
    返回 (正文内容, frontmatter字典, 原始frontmatter字符串)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    frontmatter_dict = {}
    body_content = content
    frontmatter_str = ""
    
    # 检查是否以frontmatter开头
    if content.startswith("---"):
        lines = content.split('\n')
        frontmatter_end_line = -1
        
        # 从第二行开始查找结束的 ---
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                frontmatter_end_line = i
                break
        
        if frontmatter_end_line != -1:
            # 提取frontmatter内容
            frontmatter_lines = lines[1:frontmatter_end_line]
            frontmatter_str = '\n'.join(frontmatter_lines)
            
            # 提取body内容
            body_lines = lines[frontmatter_end_line + 1:]
            body_content = '\n'.join(body_lines)
            
            try:
                frontmatter_dict = yaml.safe_load(frontmatter_str) or {}
            except yaml.YAMLError as e:
                print(f"警告：解析文件 {file_path} 的 frontmatter 失败: {e}")
                frontmatter_dict = {}
    
    return body_content, frontmatter_dict, frontmatter_str

def write_markdown_with_frontmatter(file_path, frontmatter, body):
    """
    将 frontmatter 和正文重新组合并写入 Markdown 文件
    """
    output_content = ""
    if frontmatter:
        frontmatter_dump = yaml.dump(frontmatter, 
                                    allow_unicode=True, 
                                    default_flow_style=False, 
                                    sort_keys=False,
                                    width=1000)  # 避免长行被折断
        output_content = f"---\n{frontmatter_dump.strip()}\n---\n"
    
    output_content += body
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(output_content)

def clean_frontmatter(frontmatter_dict, keep_keys):
    """
    清理frontmatter，只保留指定的键
    """
    if not frontmatter_dict:
        return {}
    
    cleaned = {}
    for key in keep_keys:
        if key in frontmatter_dict:
            cleaned[key] = frontmatter_dict[key]
    
    return cleaned

def process_markdown_file(file_path, keep_keys, backup_dir=None):
    """
    处理单个Markdown文件
    """
    try:
        # 创建备份
        if backup_dir:
            backup_path = backup_dir / file_path.name
            shutil.copy2(file_path, backup_path)
        
        # 读取文件
        body_content, frontmatter_dict, original_frontmatter = read_markdown_with_frontmatter(file_path)
        
        # 如果没有frontmatter，跳过
        if not frontmatter_dict:
            return False, "无frontmatter"
        
        # 清理frontmatter
        cleaned_frontmatter = clean_frontmatter(frontmatter_dict, keep_keys)
        
        # 检查是否有变化
        if cleaned_frontmatter == frontmatter_dict:
            return False, "无需修改"
        
        # 写入文件
        write_markdown_with_frontmatter(file_path, cleaned_frontmatter, body_content)
        
        # 统计删除的键
        removed_keys = set(frontmatter_dict.keys()) - set(cleaned_frontmatter.keys())
        return True, f"删除了键: {', '.join(removed_keys)}"
        
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

def main():
    parser = argparse.ArgumentParser(description='批量清理Markdown文件的YAML frontmatter')
    parser.add_argument('directory', help='要处理的目录路径')
    parser.add_argument('--keep-keys', 
                       default='tags,modified,created,cssclasses',
                       help='要保留的键，用逗号分隔 (默认: tags,modified,created,cssclasses)')
    parser.add_argument('--backup', action='store_true', help='创建备份文件')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际修改文件')
    parser.add_argument('--exclude', 
                       default='.obsidian,.git,node_modules',
                       help='要排除的目录模式，用逗号分隔')
    
    args = parser.parse_args()
    
    # 解析参数
    directory = Path(args.directory)
    keep_keys = [key.strip() for key in args.keep_keys.split(',')]
    exclude_patterns = [pattern.strip() for pattern in args.exclude.split(',')]
    
    if not directory.exists():
        print(f"错误：目录 {directory} 不存在")
        return
    
    # 创建备份目录
    backup_dir = None
    if args.backup and not args.dry_run:
        backup_dir = directory / f"frontmatter_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(exist_ok=True)
        print(f"备份目录: {backup_dir}")
    
    # 查找所有Markdown文件
    markdown_files = find_markdown_files(directory, exclude_patterns)
    
    if not markdown_files:
        print("未找到任何Markdown文件")
        return
    
    print(f"找到 {len(markdown_files)} 个Markdown文件")
    print(f"保留的键: {', '.join(keep_keys)}")
    print(f"排除目录: {', '.join(exclude_patterns)}")
    
    if args.dry_run:
        print("\n=== 预览模式 ===")
    else:
        print("\n=== 开始处理 ===")
    
    processed_count = 0
    modified_count = 0
    
    for i, file_path in enumerate(markdown_files, 1):
        relative_path = file_path.relative_to(directory)
        print(f"[{i}/{len(markdown_files)}] 处理: {relative_path}")
        
        try:
            # 读取并分析文件
            body_content, frontmatter_dict, _ = read_markdown_with_frontmatter(file_path)
            
            if not frontmatter_dict:
                print(f"  跳过: 无frontmatter")
                continue
            
            # 清理frontmatter
            cleaned_frontmatter = clean_frontmatter(frontmatter_dict, keep_keys)
            removed_keys = set(frontmatter_dict.keys()) - set(cleaned_frontmatter.keys())
            
            if not removed_keys:
                print(f"  跳过: 无需修改")
                continue
            
            print(f"  将删除键: {', '.join(sorted(removed_keys))}")
            print(f"  保留键: {', '.join(sorted(cleaned_frontmatter.keys()))}")
            
            processed_count += 1
            
            # 如果不是预览模式，实际修改文件
            if not args.dry_run:
                success, message = process_markdown_file(file_path, keep_keys, backup_dir)
                if success:
                    modified_count += 1
                    print(f"  ✅ 已修改")
                else:
                    print(f"  ❌ {message}")
            else:
                print(f"  📋 预览: 将修改")
                
        except Exception as e:
            print(f"  ❌ 错误: {e}")
    
    # 输出总结
    print(f"\n=== 处理完成 ===")
    print(f"总文件数: {len(markdown_files)}")
    print(f"需要处理的文件: {processed_count}")
    
    if not args.dry_run:
        print(f"实际修改的文件: {modified_count}")
        if backup_dir:
            print(f"备份位置: {backup_dir}")
    else:
        print("预览模式：未实际修改任何文件")
        print("要实际执行修改，请移除 --dry-run 参数")

if __name__ == "__main__":
    main()