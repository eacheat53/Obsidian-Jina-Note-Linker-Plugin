import os
import json
import re
import argparse
import requests
import math
import time
import datetime
import hashlib # 用于 SHA256 哈希计算
import fnmatch
import yaml # 用于解析 frontmatter
import sys
import io
import sqlite3
from pathlib import Path # 用于路径操作

# 确保标准输出和标准错误使用 UTF-8 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- 嵌入处理配置常量 (只保留脚本内部固定或真正意义上的常量) ---
JINA_API_URL = "https://api.jina.ai/v1/embeddings" 
JINA_API_REQUEST_DELAY = 0.1 # Jina API 请求之间的延迟时间（秒）
# DEFAULT_EMBEDDINGS_FILE_NAME, DEFAULT_CANDIDATES_FILE_NAME etc. are used as argparse defaults below

# --- AI 打分相关配置 ---
AI_API_REQUEST_DELAY_SECONDS = 1.0 # AI API 调用之间的默认延迟时间（秒）
# 批处理相关常量
EMBEDDING_BATCH_SIZE = 10  # 嵌入批处理大小
AI_SCORING_BATCH_SIZE = 5  # AI评分批处理大小

# AI 提供商默认配置
DEFAULT_AI_CONFIGS = {
    'deepseek': {
        'api_url': 'https://api.deepseek.com/chat/completions',
        'model_name': 'deepseek-chat'
    },
    'openai': {
        'api_url': 'https://api.openai.com/v1/chat/completions',
        'model_name': 'gpt-4o-mini'
    },
    'claude': {
        'api_url': 'https://api.anthropic.com/v1/messages',
        'model_name': 'claude-3-haiku-20240307'
    },
    'gemini': {
        'api_url': 'https://generativelanguage.googleapis.com/v1beta/models',
        'model_name': 'gemini-1.5-flash'
    },
    'custom': {
        'api_url': '',
        'model_name': ''
    }
}

# --- 代码优化记录 ---
# REMOVED: get_deepseek_api_key 函数 - 不再需要，API密钥直接通过参数传递
# REMOVED: call_ai_api_for_pair_relevance 函数 - 已被批量处理函数 call_ai_api_batch_for_relevance 替代
# REMOVED: parse_ai_response 函数 - 已被批量处理函数 parse_ai_batch_response 替代
# OPTIMIZED: 更新了 build_ai_batch_request 函数，加入全面的多元化笔记评分标准

# --- 哈希边界标记常量 ---
# 此标记用于界定笔记内容哈希计算的边界，此边界后的内容不参与哈希计算
HASH_BOUNDARY_MARKER = "<!-- HASH_BOUNDARY -->"

# --- 数据库辅助函数 ---
def get_db_connection(db_path):
    """获取数据库连接"""
    return sqlite3.connect(db_path)

def initialize_database(db_path, schema_sql):
    """如果数据库不存在，则使用提供的 schema 初始化"""
    if not os.path.exists(db_path):
        print(f"数据库 {os.path.basename(db_path)} 不存在，正在初始化...")
        try:
            conn = get_db_connection(db_path)
            conn.executescript(schema_sql)
            conn.commit()
            conn.close()
            print(f"✅ 数据库 {os.path.basename(db_path)} 初始化成功。")
        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            # 如果初始化失败，删除可能已创建的空文件
            if os.path.exists(db_path):
                os.remove(db_path)
            raise

# --- 辅助函数 ---
def read_markdown_with_frontmatter(file_path: str) -> tuple[str, dict, str]:
    """
    读取 Markdown 文件，分离 frontmatter、正文和原始 frontmatter 字符串。
    返回 (正文内容, frontmatter字典, 原始frontmatter字符串)。
    如果无 frontmatter，则 frontmatter字典 为空，原始frontmatter字符串 为空。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        full_content = f.read()

    frontmatter_str = ""
    frontmatter_dict = {}
    body_content = full_content

    # 检查是否以frontmatter开头
    if full_content.startswith("---"):
        # 查找frontmatter结束标记
        lines = full_content.split('\n')
        frontmatter_end_line = -1
        
        # 从第二行开始查找结束的 ---
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                frontmatter_end_line = i
                break
        
        if frontmatter_end_line != -1:
            # 提取frontmatter内容（不包括开始和结束的 --- 行）
            frontmatter_lines = lines[1:frontmatter_end_line]
            frontmatter_block = '\n'.join(frontmatter_lines)
            
            # 提取body内容（从frontmatter结束行的下一行开始）
            body_lines = lines[frontmatter_end_line + 1:]
            body_content = '\n'.join(body_lines)
            
            frontmatter_str = frontmatter_block 
            try:
                frontmatter_dict = yaml.safe_load(frontmatter_block) or {}
            except yaml.YAMLError as e:
                print(f"警告：解析文件 {file_path} 的 frontmatter 失败: {e}")
                frontmatter_dict = {} 
    
    return body_content, frontmatter_dict, frontmatter_str


def write_markdown_with_frontmatter(file_path: str, frontmatter: dict, body: str):
    """
    将 frontmatter 和正文重新组合并写入 Markdown 文件。
    """
    output_content = ""
    if frontmatter:
        frontmatter_dump = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
        output_content = f"---\n{frontmatter_dump.strip()}\n---\n"
    
    output_content += body

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(output_content)

def extract_content_for_hashing(text_body: str) -> str | None:
    """
    提取用于计算哈希的内容。
    必须找到 HASH_BOUNDARY_MARKER，并使用标记之前的内容。
    如果未找到 HASH_BOUNDARY_MARKER，则返回 None，表示无法提取哈希内容。
    提取出的内容会进行末尾换行符的标准化处理。
    """
    marker_index = text_body.find(HASH_BOUNDARY_MARKER)

    if marker_index != -1:
        content_to_hash = text_body[:marker_index]
        if not content_to_hash.strip(): 
            return "" 
        content_to_hash = content_to_hash.rstrip('\r\n') 
        return content_to_hash + "\n" 
    else:
        return None

def calculate_hash_from_content(content: str) -> str:
    """计算给定字符串内容的 SHA256 哈希值。"""
    hasher = hashlib.sha256()
    hasher.update(content.encode('utf-8'))
    return hasher.hexdigest()

def list_markdown_files(scan_directory_abs: str, project_root_abs: str, excluded_folders: list = None, excluded_files_patterns: list = None) -> list:
    markdown_files = []
    if excluded_folders is None:
        excluded_folders = []
    if excluded_files_patterns is None:
        excluded_files_patterns = []

    if not os.path.isdir(scan_directory_abs):
        print(f"错误：扫描路径 {scan_directory_abs} 不是一个有效的文件夹。")
        return []

    compiled_excluded_patterns = []
    for p_glob in excluded_files_patterns:
        try:
            p_regex = fnmatch.translate(p_glob) 
            compiled_excluded_patterns.append(re.compile(p_regex, re.IGNORECASE))
        except re.error as e:
            print(f"警告：无法将排除文件 Glob 模式 '{p_glob}' 转换为有效正则表达式: {e}。将跳过此模式。")

    for root, dirs, files in os.walk(scan_directory_abs, topdown=True):
        dirs[:] = [d for d in dirs if d.lower() not in [ef.lower() for ef in excluded_folders]]
        
        for file in files:
            if file.endswith(".md"):
                file_abs_path = os.path.join(root, file)
                is_excluded_file = False
                for pattern in compiled_excluded_patterns:
                    if pattern.search(file.lower()) or pattern.search(os.path.splitext(file)[0].lower()):
                        is_excluded_file = True
                        break
                if is_excluded_file:
                    continue
                
                path_relative_to_project_root = os.path.relpath(file_abs_path, project_root_abs)
                path_parts = path_relative_to_project_root.lower().split(os.sep)
                if any(part in [ef.lower() for ef in excluded_folders] for part in path_parts[:-1]):
                    continue

                markdown_files.append(path_relative_to_project_root.replace(os.sep, '/'))
    return markdown_files

def get_jina_embedding(text: str, 
                       jina_api_key_to_use: str, 
                       jina_model_name_to_use: str, 
                       max_retries: int = 3, 
                       initial_delay: float = 1.0) -> list | None:
    """调用 Jina API 获取文本的嵌入向量，包含重试机制"""
    if not jina_api_key_to_use: 
        print("错误：Jina API Key 未提供。")
        return None
    if not jina_model_name_to_use:
        print("错误：Jina 模型名称未提供。")
        return None
    if not text.strip():
        print("警告：输入文本为空，跳过嵌入。")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jina_api_key_to_use}"
    }
    data = {
        "input": [text],
        "model": jina_model_name_to_use
    }
    
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            time.sleep(JINA_API_REQUEST_DELAY)
            response = requests.post(JINA_API_URL, headers=headers, data=json.dumps(data), timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get("data") and len(result["data"]) > 0 and result["data"][0].get("embedding"):
                return result["data"][0]["embedding"]
            else:
                print(f"错误：Jina API 响应格式不正确。响应: {result}")
                return None # 格式错误，不重试

        except requests.exceptions.RequestException as e:
            print(f"错误：调用 Jina API 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"响应状态码: {e.response.status_code}, 响应内容: {e.response.text[:500]}...")
                # 如果是客户端错误（如4xx），则不重试
                if 400 <= e.response.status_code < 500:
                    return None
            
            # 等待后重试
            time.sleep(delay)
            delay *= 2 # 指数退避

        except Exception as e:
            print(f"处理 Jina API 响应时发生未知错误: {e}")
            return None # 未知错误，不重试
            
    print(f"错误：达到最大重试次数 {max_retries} 后，Jina API 调用仍然失败。")
    return None

def get_jina_embeddings_batch(texts: list, jina_api_key_to_use: str, jina_model_name_to_use: str, max_retries: int = 3, initial_delay: float = 1.0) -> list:
    """批量获取多个文本的嵌入向量，包含重试机制"""
    if not texts:
        return []
    if not jina_api_key_to_use: 
        print("错误：Jina API Key 未提供。")
        return [None] * len(texts)
    if not jina_model_name_to_use:
        print("错误：Jina 模型名称未提供。")
        return [None] * len(texts)
    
    # 过滤掉空文本
    valid_texts = []
    text_indices = []
    for i, text in enumerate(texts):
        if text and text.strip():
            valid_texts.append(text)
            text_indices.append(i)
    
    if not valid_texts:
        print("警告：所有输入文本均为空，跳过嵌入。")
        return [None] * len(texts)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jina_api_key_to_use}"
    }
    data = {
        "input": valid_texts,
        "model": jina_model_name_to_use
    }
    
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            time.sleep(JINA_API_REQUEST_DELAY)
            response = requests.post(JINA_API_URL, headers=headers, data=json.dumps(data), timeout=60)  # 增加超时时间
            response.raise_for_status()
            
            result = response.json()
            if result.get("data") and len(result["data"]) == len(valid_texts):
                # 构建完整结果数组，对于无效文本保留None
                embeddings = [None] * len(texts)
                for i, idx in enumerate(text_indices):
                    if i < len(result["data"]) and result["data"][i].get("embedding"):
                        embeddings[idx] = result["data"][i]["embedding"]
                return embeddings
            else:
                print(f"错误：Jina API 批量响应格式不正确。响应: {result}")
                return [None] * len(texts)

        except requests.exceptions.RequestException as e:
            print(f"错误：批量调用 Jina API 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"响应状态码: {e.response.status_code}, 响应内容: {e.response.text[:500]}...")
                # 如果是客户端错误（如4xx），则不重试
                if 400 <= e.response.status_code < 500:
                    return [None] * len(texts)
            
            # 等待后重试
            time.sleep(delay)
            delay *= 2 # 指数退避

        except Exception as e:
            print(f"处理批量 Jina API 响应时发生未知错误: {e}")
            return [None] * len(texts) # 未知错误，不重试
            
    print(f"错误：达到最大重试次数 {max_retries} 后，批量 Jina API 调用仍然失败。")
    return [None] * len(texts)

def process_and_embed_notes(
    project_root_abs: str,
    files_relative_to_project_root: list,
    embeddings_db_path: str,
    jina_api_key_to_use: str,
    jina_model_name_to_use: str,
    max_chars_for_jina_to_use: int,
    embedding_batch_size: int = EMBEDDING_BATCH_SIZE
) -> dict:
    """
    处理笔记，生成嵌入并将其存储在 SQLite 数据库中。
    返回一个与旧版兼容的字典，用于后续步骤。
    优化版：使用批量处理来减少API调用次数。
    """
    conn = get_db_connection(embeddings_db_path)
    cursor = conn.cursor()

    # 从数据库加载现有嵌入数据到内存
    files_data_from_db = {}
    cursor.execute("SELECT file_path, content_hash, embedding, processed_content FROM file_embeddings")
    for row in cursor.fetchall():
        file_path, content_hash, embedding_blob, processed_content = row
        embedding = json.loads(embedding_blob) if embedding_blob else None
        files_data_from_db[file_path] = {
            "hash": content_hash,
            "embedding": embedding,
            "processed_content": processed_content
        }

    embedded_count = 0
    processed_files_this_run = 0
    
    # 用于存储本次运行的所有文件数据，以便返回
    all_files_data_for_return = files_data_from_db.copy()

    # 批量处理相关变量
    batch_size = embedding_batch_size
    total_files = len(files_relative_to_project_root)
    
    # 按批次处理文件
    for batch_start in range(0, total_files, batch_size):
        batch_end = min(batch_start + batch_size, total_files)
        batch_files = files_relative_to_project_root[batch_start:batch_end]
        
        print(f"批量处理文件 ({batch_start+1}-{batch_end}/{total_files})...")
        
        # 1. 预处理阶段：收集需要嵌入的文件信息
        batch_contents = []  # 要发送给API的内容
        batch_file_info = []  # 文件相关信息
        
        for file_rel_path in batch_files:
            file_abs_path = os.path.join(project_root_abs, file_rel_path)
            
            if not os.path.exists(file_abs_path):
                print(f"  错误：文件 {file_rel_path} 不存在，从数据库中删除。")
                cursor.execute("DELETE FROM file_embeddings WHERE file_path = ?", (file_rel_path,))
                if file_rel_path in all_files_data_for_return:
                    del all_files_data_for_return[file_rel_path]
                continue

            try:
                original_body_content, existing_frontmatter, _ = read_markdown_with_frontmatter(file_abs_path)
                text_for_processing = extract_content_for_hashing(original_body_content)
                
                if text_for_processing is None:
                    print(f"  错误: 笔记 '{file_rel_path}' 中未找到哈希边界标记 '{HASH_BOUNDARY_MARKER}'。跳过。")
                    continue

                current_content_hash = calculate_hash_from_content(text_for_processing)
                stored_hash_in_frontmatter = existing_frontmatter.get("jina_hash")

                needs_embedding_api_call = True
                final_embedding = None

                db_entry = files_data_from_db.get(file_rel_path)
                
                # 检查哈希是否匹配
                if stored_hash_in_frontmatter and stored_hash_in_frontmatter == current_content_hash:
                    if db_entry and db_entry.get("hash") == current_content_hash:
                        final_embedding = db_entry.get("embedding")
                        needs_embedding_api_call = False
                elif stored_hash_in_frontmatter:
                     print(f"  内容已修改 (frontmatter哈希 '{stored_hash_in_frontmatter[:8]}' vs 当前 '{current_content_hash[:8]}')。")
                else:
                    print(f"  新文件或frontmatter中无哈希。")

                if needs_embedding_api_call:
                    processed_files_this_run += 1
                    if not text_for_processing.strip():
                        print(f"  警告：文件 {file_rel_path} 有效内容为空。不嵌入。")
                    else:
                        # 收集用于批量嵌入的信息
                        text_for_embedding = text_for_processing[:max_chars_for_jina_to_use]
                        batch_contents.append(text_for_embedding)
                        batch_file_info.append({
                            "file_path": file_rel_path,
                            "abs_path": file_abs_path,
                            "content_hash": current_content_hash,
                            "frontmatter": existing_frontmatter,
                            "original_content": original_body_content,
                            "processed_content": text_for_processing,
                            "index": len(batch_contents) - 1  # 记录在batch_contents中的索引
                        })
                else:
                    # 直接更新返回数据
                    all_files_data_for_return[file_rel_path] = {
                        "embedding": final_embedding,
                        "hash": current_content_hash,
                        "processed_content": text_for_processing
                    }
                    
                # 更新frontmatter中的哈希（如果需要）
                if existing_frontmatter.get("jina_hash") != current_content_hash:
                    existing_frontmatter["jina_hash"] = current_content_hash
                    try:
                        write_markdown_with_frontmatter(file_abs_path, existing_frontmatter, original_body_content)
                    except Exception as e_write:
                        print(f"  错误：写入 frontmatter 到 {file_rel_path} 失败: {e_write}")
            
            except Exception as e:
                print(f"  错误：读取文件 {file_rel_path} 失败: {e}。跳过。")
                continue
        
        # 2. 如果有需要嵌入的内容，批量调用API
        if batch_contents:
            print(f"  调用 Jina API 获取 {len(batch_contents)} 个文件的嵌入...")
            batch_embeddings = get_jina_embeddings_batch(
                batch_contents, 
                jina_api_key_to_use, 
                jina_model_name_to_use
            )
            
            # 3. 处理API返回的嵌入结果
            for file_info in batch_file_info:
                index = file_info["index"]
                file_rel_path = file_info["file_path"]
                file_abs_path = file_info["abs_path"]
                
                embedding = None
                if index < len(batch_embeddings):
                    embedding = batch_embeddings[index]
                
                if embedding:
                    embedded_count += 1
                    print(f"  成功获取嵌入: {file_rel_path} (哈希: {file_info['content_hash'][:8]}...)")
                else:
                    print(f"  未能获取嵌入: {file_rel_path}")
                
                # 更新frontmatter中的哈希
                frontmatter = file_info["frontmatter"]
                if frontmatter.get("jina_hash") != file_info["content_hash"]:
                    frontmatter["jina_hash"] = file_info["content_hash"]
                    try:
                        write_markdown_with_frontmatter(file_abs_path, frontmatter, file_info["original_content"])
                    except Exception as e_write:
                        print(f"  错误：写入 frontmatter 到 {file_rel_path} 失败: {e_write}")

                # 更新数据库
                embedding_json = json.dumps(embedding) if embedding else None
                dimension = len(embedding) if embedding else 0
        
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO file_embeddings 
                    (file_path, content_hash, embedding, processed_content, embedding_dimension, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_rel_path,
                        file_info["content_hash"],
                        embedding_json,
                        file_info["processed_content"],
                        dimension,
                        datetime.datetime.now(datetime.timezone.utc).isoformat()
                    )
                )

                # 更新用于返回的字典
                all_files_data_for_return[file_rel_path] = {
                    "embedding": embedding,
                    "hash": file_info["content_hash"],
                    "processed_content": file_info["processed_content"]
                }

    # 更新元数据
    cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                   ('generated_at_utc', datetime.datetime.now(datetime.timezone.utc).isoformat()))
    cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                   ('jina_model_name', jina_model_name_to_use))
    
    conn.commit()
    conn.close()
    
    print(f"嵌入数据已保存到 {os.path.basename(embeddings_db_path)}。本次嵌入/更新 {embedded_count} 条。处理了 {processed_files_this_run} 个文件。")

    # 返回与旧版兼容的字典结构
    return {
        "_metadata": {
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "jina_model_name": jina_model_name_to_use,
            "script_version": "2.0_plugin_compatible_sqlite"
        },
        "files": all_files_data_for_return
    }

def cosine_similarity(vec1: list, vec2: list) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(p * q for p, q in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(p * p for p in vec1))
    magnitude2 = math.sqrt(sum(q * q for q in vec2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)

def generate_candidate_pairs(embeddings_data_input: dict, similarity_threshold: float) -> list: # candidates_file_path 已移除
    """基于嵌入相似性生成候选链接对"""
    print("  开始生成候选链接对...")
    
    candidates = []
    files_data = embeddings_data_input.get('files', {})
    
    # 获取所有有效的文件路径（有嵌入的）
    valid_file_paths = []
    for file_path, file_info in files_data.items():
        if file_info.get('embedding') is not None:
            valid_file_paths.append(file_path)
    
    total_comparisons = len(valid_file_paths) * (len(valid_file_paths) - 1) // 2
    completed_comparisons = 0
    
    print(f"  共有 {len(valid_file_paths)} 个文件待比较，总计 {total_comparisons} 个比较操作...")
    
    # 使用进度条 
    progress_step = max(1, total_comparisons // 20)  # 每5%更新一次
    next_progress_milestone = progress_step
    
    # 计算每对文件的相似度
    for i, path1 in enumerate(valid_file_paths):
        for j, path2 in enumerate(valid_file_paths[i+1:], start=i+1):
            
            completed_comparisons += 1
            if completed_comparisons >= next_progress_milestone:
                progress_percent = (completed_comparisons / total_comparisons) * 100
                print(f"  进度: {progress_percent:.1f}% 正在对比: {path1} vs {path2}...")
                next_progress_milestone += progress_step
            
            # 从embeddings_data中获取嵌入
            embedding1 = files_data[path1].get('embedding')
            embedding2 = files_data[path2].get('embedding')
            
            if embedding1 is None or embedding2 is None:
                continue
                
            # 计算相似度
            similarity_score = cosine_similarity(embedding1, embedding2)
            
            # 添加到候选列表（如果超过阈值）
            if similarity_score >= similarity_threshold:
                candidates.append({
                    'source_path': path1,
                    'target_path': path2,
                    'jina_similarity': similarity_score
                })
    
    # 按相似度降序排序
    candidates.sort(key=lambda x: x['jina_similarity'], reverse=True)
    print(f"  生成了 {len(candidates)} 个候选链接对。")
    return candidates

# 添加缺失的函数

def build_ai_batch_request(ai_provider: str, model_name: str, api_key: str, 
                          prompt_pairs: list, max_content_length: int) -> tuple:
    """构建不同AI提供商的批量请求体和头部"""
    
    # 适用于多元化笔记内容的评分指南
    comprehensive_scoring_guide = """
    作为笔记关联性评分专家，请评估以下多对内容的关联度。这些内容可能包括知识笔记、诗歌创作、灵感片段、散文、情感记录等多样化形式。对每对内容给出0-10的整数评分，基于以下全面标准：

    【评分标准：适用于多元内容】
    10分 - 深度关联：
      • 内容间存在明显的思想、情感或意象共鸣
      • 一篇内容直接启发、延伸或回应另一篇
      • 两篇形成完整的表达整体，共同构建一个更丰富的意境或思想
      • 同时阅读会产生"啊哈"时刻，带来新的领悟

    8-9分 - 强烈关联：
      • 共享核心情感、意象或主题
      • 表达相似的思想但通过不同角度或形式
      • 创作背景或灵感来源紧密相连
      • 一篇可以深化对另一篇的理解和欣赏

    6-7分 - 明显关联：
      • 存在清晰的主题或情绪连接
      • 使用相似的意象或表达方式
      • 关联点足够丰富，能激发新的思考
      • 并置阅读能够丰富整体体验

    4-5分 - 中等关联：
      • 有一些共通元素，但整体走向不同
      • 某些片段或意象存在呼应，但不是主体
      • 关联更加微妙或需要一定解读
      • 链接可能对部分读者有启发价值

    2-3分 - 轻微关联：
      • 关联仅限于表面术语或零星概念
      • 主题、风格或情感基调大不相同
      • 联系需要刻意寻找才能发现
      • 链接价值有限，大多数读者难以察觉关联

    0-1分 - 几乎无关联：
      • 内容、主题、意象几乎完全不同
      • 无法找到明显的思想或情感连接
      • 链接不会为读者理解任一内容增添价值
      • 并置阅读无法产生有意义的关联或启发
    """
    
    # 针对不同API提供商构建请求
    if ai_provider == 'deepseek':
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 修改为与OpenAI兼容的请求格式
        requests_array = []
        for i, pair in enumerate(prompt_pairs, start=1):
            source_name = pair['source_name']
            target_name = pair['target_name']
            source_content = pair['source_content'][:max_content_length]
            target_content = pair['target_content'][:max_content_length]
            
            requests_array.append({
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "你是善于发现内容关联的评分专家。"},
                    {"role": "user", "content": f"""评估这对内容的关联度，给出0到10的整数评分。

内容一：{source_name}
{source_content}

内容二：{target_name}
{target_content}

{comprehensive_scoring_guide}

请只回复一个0-10的整数评分，不要有任何解释或额外文字。"""}
                ],
                "max_tokens": 20,
                "temperature": 0,
                "top_p": 0.8
            })
        
        api_url = DEFAULT_AI_CONFIGS['deepseek']['api_url']
        return requests_array, headers, api_url
        
    elif ai_provider == 'openai':
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        requests_array = []
        for i, pair in enumerate(prompt_pairs, start=1):
            source_name = pair['source_name']
            target_name = pair['target_name']
            source_content = pair['source_content'][:max_content_length]
            target_content = pair['target_content'][:max_content_length]
            
            requests_array.append({
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "你是善于发现内容关联的评分专家。"},
                    {"role": "user", "content": f"""评估以下这对内容的关联度，给出0到10的整数评分。

内容一：{source_name}
{source_content}

内容二：{target_name}
{target_content}

{comprehensive_scoring_guide}

请只回复一个0-10的整数评分，不要有任何解释或额外文字。"""}
                ],
                "max_tokens": 10,
                "temperature": 0
            })
        
        api_url = DEFAULT_AI_CONFIGS['openai']['api_url']
        return requests_array, headers, api_url
        
    elif ai_provider == 'claude':
        headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        requests_array = []
        for i, pair in enumerate(prompt_pairs, start=1):
            source_name = pair['source_name']
            target_name = pair['target_name']
            source_content = pair['source_content'][:max_content_length]
            target_content = pair['target_content'][:max_content_length]
            
            requests_array.append({
                "model": model_name,
                "max_tokens": 10,
                "system": "你是善于发现内容关联的评分专家。请只输出评分数字，不要有任何解释或额外文字。",
                "messages": [
                    {"role": "user", "content": f"""评估以下这对内容的关联度，给出0到10的整数评分。

内容一：{source_name}
{source_content}

内容二：{target_name}
{target_content}

{comprehensive_scoring_guide}

请只回复一个0-10的整数评分，不要有任何解释或额外文字。"""}
                ],
                "temperature": 0
            })
        
        api_url = DEFAULT_AI_CONFIGS['claude']['api_url']
        return requests_array, headers, api_url
        
    elif ai_provider == 'gemini':
        headers = {
            "Content-Type": "application/json"
        }
        
        requests_array = []
        for i, pair in enumerate(prompt_pairs, start=1):
            source_name = pair['source_name']
            target_name = pair['target_name']
            source_content = pair['source_content'][:max_content_length]
            target_content = pair['target_content'][:max_content_length]
            
            api_url_with_key = f"{DEFAULT_AI_CONFIGS['gemini']['api_url']}/{model_name}:generateContent?key={api_key}"
            
            requests_array.append({
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"""作为善于发现内容关联的评分专家，请评估以下这对内容的关联度，给出0到10的整数评分。

内容一：{source_name}
{source_content}

内容二：{target_name}
{target_content}

{comprehensive_scoring_guide}

请只回复一个0-10的整数评分，不要有任何解释或额外文字。"""
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 10
                }
            })
            
        return requests_array, headers, DEFAULT_AI_CONFIGS['gemini']['api_url']
        
    else:  # 自定义API
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        messages_array = []
        for i, pair in enumerate(prompt_pairs, start=1):
            source_name = pair['source_name']
            target_name = pair['target_name']
            source_content = pair['source_content'][:max_content_length]
            target_content = pair['target_content'][:max_content_length]
            
            messages_array.append([
                {"role": "user", "content": f"""作为善于发现内容关联的评分专家，请评估这对内容的关联度，给出0到10的整数评分。

内容一：{source_name}
{source_content}

内容二：{target_name}
{target_content}

{comprehensive_scoring_guide}

请只回复一个0-10的整数评分，不要有任何解释或额外文字。"""}
            ])
        
        data = {
            "model": model_name,
            "messages_list": messages_array,
            "max_tokens": 20,
            "temperature": 0
        }
        
        return data, headers, DEFAULT_AI_CONFIGS['custom']['api_url']

def call_ai_api_batch_for_relevance(ai_provider: str, model_name: str, api_key: str, api_url: str,
                                   prompt_pairs: list, headers: dict, data: dict | list, 
                                   max_retries: int = 3, initial_delay: float = 1.0) -> list:
    """批量调用AI API评估候选对的相关性"""
    
    if not prompt_pairs:
        print("  无候选对需要评分。")
        return []
    
    delay = initial_delay
    all_results = []
    
    try:
        if ai_provider == 'deepseek':
            # 修改为逐个发送请求，与OpenAI处理方式相同
            for i, request_data in enumerate(data):
                for attempt in range(max_retries):
                    try:
                        time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                        print(f"  正在调用 DeepSeek API, 尝试 {attempt + 1}/{max_retries}...")
                        response = requests.post(
                            api_url, 
                            headers=headers, 
                            json=request_data,
                            timeout=30
                        )
                        
                        # 如果收到422响应，尝试提取详细错误信息
                        if response.status_code == 422:
                            error_detail = response.json() if response.text else "无详细错误信息"
                            print(f"  收到422错误: {error_detail}")
                            raise Exception(f"DeepSeek API返回422错误: {error_detail}")
                        
                        response.raise_for_status()
                        result = parse_ai_batch_response('openai', response.json(), [prompt_pairs[i]])
                        all_results.extend(result)
                        break
                    except requests.exceptions.HTTPError as e:
                        error_msg = f"HTTP错误: {e}"
                        if hasattr(e, 'response') and e.response.text:
                            try:
                                error_detail = e.response.json()
                                error_msg += f", 详细信息: {error_detail}"
                            except:
                                error_msg += f", 响应内容: {e.response.text[:500]}"
                        
                        print(error_msg)
                        if attempt == max_retries - 1:
                            print(f"  错误: 在尝试 {max_retries} 次后仍无法调用 {ai_provider} API: {error_msg}")
                            all_results.append({"error": str(e), "ai_score": 0, 
                                              "source_path": prompt_pairs[i]['source_path'], 
                                              "target_path": prompt_pairs[i]['target_path'],
                                              "jina_similarity": prompt_pairs[i].get('jina_similarity', 0)})
                        delay *= 2
                        print(f"  等待 {delay} 秒后重试...")
                        time.sleep(delay)
                    except Exception as e:
                        error_msg = f"未知错误: {e}"
                        print(error_msg)
                        if attempt == max_retries - 1:
                            print(f"  错误: 在尝试 {max_retries} 次后仍无法调用 {ai_provider} API: {error_msg}")
                            all_results.append({"error": str(e), "ai_score": 0,
                                              "source_path": prompt_pairs[i]['source_path'], 
                                              "target_path": prompt_pairs[i]['target_path'],
                                              "jina_similarity": prompt_pairs[i].get('jina_similarity', 0)})
                        delay *= 2
                        print(f"  等待 {delay} 秒后重试...")
                        time.sleep(delay)
        
        elif ai_provider == 'openai':
            # OpenAI API 调用每个请求
            for i, request_data in enumerate(data):
                for attempt in range(max_retries):
                    try:
                        time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                        response = requests.post(
                            api_url, 
                            headers=headers, 
                            json=request_data,
                            timeout=30
                        )
                        response.raise_for_status()
                        result = parse_ai_batch_response(ai_provider, response.json(), [prompt_pairs[i]])
                        all_results.extend(result)
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            print(f"  错误: 在尝试 {max_retries} 次后仍无法调用 OpenAI API 对对 {i+1}: {e}")
                            all_results.append({"error": str(e), "ai_score": 0})
                        delay *= 2
                        time.sleep(delay)
        
        elif ai_provider == 'claude':
            # Claude API 调用每个请求
            for i, request_data in enumerate(data):
                for attempt in range(max_retries):
                    try:
                        time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                        response = requests.post(
                            api_url, 
                            headers=headers, 
                            json=request_data,
                            timeout=30
                        )
                        response.raise_for_status()
                        result = parse_ai_batch_response(ai_provider, response.json(), [prompt_pairs[i]])
                        all_results.extend(result)
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            print(f"  错误: 在尝试 {max_retries} 次后仍无法调用 Claude API 对对 {i+1}: {e}")
                            all_results.append({"error": str(e), "ai_score": 0})
                        delay *= 2
                        time.sleep(delay)
                        
        elif ai_provider == 'gemini':
            # Gemini API 调用每个请求，需要完整URL+API密钥
            for i, request_data in enumerate(data):
                for attempt in range(max_retries):
                    try:
                        time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                        full_url = f"{api_url}/{model_name}:generateContent?key={api_key}"
                        response = requests.post(
                            full_url,
                            headers=headers, 
                            json=request_data,
                            timeout=30
                        )
                        response.raise_for_status()
                        result = parse_ai_batch_response(ai_provider, response.json(), [prompt_pairs[i]])
                        all_results.extend(result)
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            print(f"  错误: 在尝试 {max_retries} 次后仍无法调用 Gemini API 对对 {i+1}: {e}")
                            all_results.append({"error": str(e), "ai_score": 0})
                        delay *= 2
                        time.sleep(delay)
        
        else:  # 自定义API
            # 假设自定义API支持批量请求，类似DeepSeek
            for attempt in range(max_retries):
                try:
                    time.sleep(AI_API_REQUEST_DELAY_SECONDS)
                    response = requests.post(
                        api_url, 
                        headers=headers, 
                        json=data,
                        timeout=60
                    )
                    response.raise_for_status()
                    all_results = parse_ai_batch_response(ai_provider, response.json(), prompt_pairs)
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f"  错误: 在尝试 {max_retries} 次后仍无法调用自定义 API: {e}")
                        return []
                    delay *= 2
                    time.sleep(delay)
                    
    except Exception as e:
        print(f"  调用 {ai_provider} API 发生意外错误: {e}")
        return []
        
    return all_results

def parse_ai_batch_response(ai_provider: str, response_data: dict | list, prompt_pairs: list) -> list:
    """解析不同AI提供商的批量响应，提取评分"""
    results = []
    
    try:
        if ai_provider == 'deepseek':
            responses = response_data.get('choices', [])
            for i, choice in enumerate(responses):
                if i >= len(prompt_pairs):
                    break
                    
                pair = prompt_pairs[i]
                content = choice.get('message', {}).get('content', '')
                
                # 提取数字评分
                score = extract_score_from_text(content)
                
                if score is not None:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': score,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
                else:
                    print(f"  警告: 无法从响应中提取评分: {content}")
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': 0,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
            
        elif ai_provider == 'openai':
            # 单个响应
            choices = response_data.get('choices', [])
            if choices and len(prompt_pairs) > 0:
                pair = prompt_pairs[0]
                content = choices[0].get('message', {}).get('content', '')
                
                score = extract_score_from_text(content)
                
                if score is not None:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': score,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
                else:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': 0,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
            
        elif ai_provider == 'claude':
            # 单个响应
            content = response_data.get('content', [{}])[0].get('text', '')
            if content and len(prompt_pairs) > 0:
                pair = prompt_pairs[0]
                
                score = extract_score_from_text(content)
                
                if score is not None:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': score,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
                else:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': 0,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
                    
        elif ai_provider == 'gemini':
            # 单个响应
            content = ""
            if 'candidates' in response_data and len(response_data['candidates']) > 0:
                if 'content' in response_data['candidates'][0]:
                    content_parts = response_data['candidates'][0]['content'].get('parts', [])
                    if content_parts and 'text' in content_parts[0]:
                        content = content_parts[0]['text']
            
            if content and len(prompt_pairs) > 0:
                pair = prompt_pairs[0]
                score = extract_score_from_text(content)
                
                if score is not None:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': score,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
                else:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': 0,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
            
        else:  # 自定义API
            # 假设自定义API返回类似DeepSeek的格式
            responses = response_data.get('choices', [])
            for i, choice in enumerate(responses):
                if i >= len(prompt_pairs):
                    break
                    
                pair = prompt_pairs[i]
                content = choice.get('message', {}).get('content', '')
                
                score = extract_score_from_text(content)
                
                if score is not None:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': score,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
                else:
                    results.append({
                        'source_path': pair['source_path'],
                        'target_path': pair['target_path'],
                        'ai_score': 0,
                        'jina_similarity': pair.get('jina_similarity', 0)
                    })
    
    except Exception as e:
        print(f"  解析 {ai_provider} 响应时发生错误: {e}")
        
    return results

def extract_score_from_text(text: str) -> int | None:
    """从文本中提取0-10的整数评分"""
    # 尝试直接将文本转换为整数
    text = text.strip()
    try:
        score = int(text)
        if 0 <= score <= 10:
            return score
    except ValueError:
        pass
    
    # 使用正则表达式查找评分
    import re
    score_pattern = r'(?<!\d)([0-9]|10)(?!\d)'
    matches = re.search(score_pattern, text)
    if matches:
        try:
            score = int(matches.group(1))
            if 0 <= score <= 10:
                return score
        except ValueError:
            pass
    
    return None

def score_candidates_and_update_frontmatter(
    candidate_pairs: list,
    project_root_abs: str,
    embeddings_db_path: str,
    ai_scores_db_path: str,
    ai_provider: str,
    ai_api_url: str,
    ai_api_key: str,
    ai_model_name: str,
    max_content_length_for_ai_to_use: int,
    force_rescore: bool = False,
    ai_scoring_batch_size: int = AI_SCORING_BATCH_SIZE
) -> None:
    """对候选链接对进行AI评分并更新"""
    if not candidate_pairs:
        print("  没有候选链接对需要评分。")
        return

    print(f"  使用 {ai_provider} AI 对 {len(candidate_pairs)} 个候选链接对进行评分...")
    
    conn = get_db_connection(ai_scores_db_path)
    cursor = conn.cursor()
    
    # 建立文件路径到ID的映射
    file_path_to_id = {}
    cursor.execute("SELECT id, file_path FROM file_paths")
    for row in cursor.fetchall():
        file_path_to_id[row[1]] = row[0]
    
    # 为所有源和目标路径创建ID（如果不存在）
    unique_paths = set()
    for pair in candidate_pairs:
        unique_paths.add(pair['source_path'])
        unique_paths.add(pair['target_path'])
    
    for path in unique_paths:
        if path not in file_path_to_id:
            cursor.execute(
                "INSERT INTO file_paths (file_path) VALUES (?) ON CONFLICT(file_path) DO NOTHING", 
                (path,)
            )
            file_path_to_id[path] = cursor.lastrowid
    
    conn.commit()
    
    # 获取已评分的关系
    scored_relationships = {}
    cursor.execute("""
        SELECT ar.source_file_id, ar.target_file_id, ar.ai_score, ar.jina_similarity
        FROM ai_relationships ar
    """)
    
    for row in cursor.fetchall():
        source_id, target_id, ai_score, jina_similarity = row
        scored_relationships[(source_id, target_id)] = (ai_score, jina_similarity)
    
    # 确定需要评分的对
    pairs_to_score = []
    for pair in candidate_pairs:
        source_path = pair['source_path']
        target_path = pair['target_path']
        
        if source_path not in file_path_to_id or target_path not in file_path_to_id:
            continue
            
        source_id = file_path_to_id[source_path]
        target_id = file_path_to_id[target_path]
        
        # 跳过已评分的对，除非强制重新评分
        if not force_rescore and (source_id, target_id) in scored_relationships:
            continue
            
        # 读取文件内容
        try:
            source_file_path = os.path.join(project_root_abs, source_path)
            target_file_path = os.path.join(project_root_abs, target_path)
            
            if not os.path.exists(source_file_path) or not os.path.exists(target_file_path):
                print(f"  警告: 无法找到文件: {source_file_path} 或 {target_file_path}")
                continue
                
            source_content, _, _ = read_markdown_with_frontmatter(source_file_path)
            target_content, _, _ = read_markdown_with_frontmatter(target_file_path)
            
            pairs_to_score.append({
                'source_path': source_path,
                'target_path': target_path,
                'source_name': os.path.basename(source_path),
                'target_name': os.path.basename(target_path),
                'source_content': source_content,
                'target_content': target_content,
                'jina_similarity': pair['jina_similarity']
            })
        except Exception as e:
            print(f"  警告: 读取文件时发生错误: {e}")
    
    print(f"  需要评分的候选对数量: {len(pairs_to_score)}")
    
    # 分批处理评分
    all_scores = []
    
    for batch_idx in range(0, len(pairs_to_score), ai_scoring_batch_size):
        batch = pairs_to_score[batch_idx:batch_idx + ai_scoring_batch_size]
        
        print(f"  处理批次 {batch_idx // ai_scoring_batch_size + 1}/{(len(pairs_to_score) + ai_scoring_batch_size - 1) // ai_scoring_batch_size}，包含 {len(batch)} 个候选对...")
        
        try:
            data, headers, api_url = build_ai_batch_request(
                ai_provider, 
                ai_model_name, 
                ai_api_key, 
                batch,
                max_content_length_for_ai_to_use
            )
            
            batch_scores = call_ai_api_batch_for_relevance(
                ai_provider,
                ai_model_name,
                ai_api_key,
                api_url,
                batch,
                headers,
                data
            )
            
            all_scores.extend(batch_scores)
        except Exception as e:
            print(f"  批次处理中发生错误: {e}")
    
    print(f"  AI 评分完成，获得了 {len(all_scores)} 个评分结果")
    
    # 更新数据库
    for result in all_scores:
        source_path = result['source_path']
        target_path = result['target_path']
        ai_score = result['ai_score']
        jina_similarity = result['jina_similarity']
        
        if source_path not in file_path_to_id or target_path not in file_path_to_id:
            continue
            
        source_id = file_path_to_id[source_path]
        target_id = file_path_to_id[target_path]
        
        # 生成一个唯一键，用于后续查询
        relationship_key = f"{source_path}|{target_path}"
        
        # 更新或插入评分
        cursor.execute("""
            INSERT INTO ai_relationships 
            (source_file_id, target_file_id, ai_score, jina_similarity, last_scored, relationship_key)
            VALUES (?, ?, ?, ?, datetime('now'), ?)
            ON CONFLICT (source_file_id, target_file_id) 
            DO UPDATE SET 
                ai_score = excluded.ai_score,
                jina_similarity = excluded.jina_similarity,
                last_scored = datetime('now'),
                relationship_key = excluded.relationship_key
        """, (source_id, target_id, ai_score, jina_similarity, relationship_key))
    
    conn.commit()
    conn.close()
        
    print(f"  AI 评分更新完成，共更新 {len(all_scores)} 个关系。")

def migrate_embeddings_json_to_sqlite(project_root_abs, output_dir_abs):
    """将 jina_embeddings.json 迁移到 jina_embeddings.db"""
    json_dir = os.path.join(project_root_abs, ".Jina-AI-Linker-Output")
    json_path = os.path.join(json_dir, "jina_embeddings.json")
    db_path = os.path.join(output_dir_abs, DEFAULT_EMBEDDINGS_FILE_NAME)

    if not os.path.exists(json_path):
        print(f"⚠️  JSON file not found: {json_path}. Skipping embeddings migration.")
        return

    if os.path.exists(db_path):
        print(f"ℹ️  Database already exists: {db_path}. Deleting for fresh migration.")
        os.remove(db_path)
        
    initialize_database(db_path, EMBEDDINGS_DB_SCHEMA)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    metadata = data.get("_metadata", {})
    files_data = data.get("files", {})
    
    print("Migrating embeddings metadata...")
    if metadata:
        cursor.execute("UPDATE metadata SET value = ? WHERE key = 'jina_model_name'", (metadata.get('jina_model_name', 'unknown'),))
        cursor.execute("UPDATE metadata SET value = ? WHERE key = 'script_version'", (metadata.get('script_version', 'unknown'),))
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                       ('generated_at_utc', metadata.get('generated_at_utc', '')))
    
    print(f"Migrating {len(files_data)} file embeddings...")
    embeddings_to_insert = []
    for file_path, details in files_data.items():
        embedding_json = json.dumps(details.get('embedding')) if details.get('embedding') else None
        dimension = len(details['embedding']) if details.get('embedding') else 0
        
        embeddings_to_insert.append((
            file_path,
            details.get('hash', ''),
            embedding_json,
            details.get('processed_content', ''),
            dimension,
            datetime.datetime.now(datetime.timezone.utc).isoformat()
        ))
        
    cursor.executemany(
        """
        INSERT INTO file_embeddings (file_path, content_hash, embedding, processed_content, embedding_dimension, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        embeddings_to_insert
    )
    
    conn.commit()
    conn.close()
    print(f"✅ Successfully migrated {len(files_data)} embeddings to '{os.path.basename(db_path)}'.")


def migrate_ai_scores_json_to_sqlite(project_root_abs, output_dir_abs):
    """将 ai_scores.json 迁移到 ai_scores.db"""
    json_dir = os.path.join(project_root_abs, ".Jina-AI-Linker-Output")
    json_path = os.path.join(json_dir, "ai_scores.json")
    db_path = os.path.join(output_dir_abs, DEFAULT_AI_SCORES_FILE_NAME)

    if not os.path.exists(json_path):
        print(f"⚠️  JSON file not found: {json_path}. Skipping AI scores migration.")
        return

    if os.path.exists(db_path):
        print(f"ℹ️  Database already exists: {db_path}. Deleting for fresh migration.")
        os.remove(db_path)
        
    initialize_database(db_path, AI_SCORES_DB_SCHEMA)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    metadata = data.get("_metadata", {})
    ai_scores = data.get("ai_scores", {})
    
    print("Migrating AI scores metadata...")
    if metadata:
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                       ('description', metadata.get('description', '')))
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                       ('last_updated', metadata.get('last_updated', '')))
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                       ('total_relationships', str(metadata.get('total_relationships', 0))))
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", 
                       ('storage_strategy', 'sqlite_dual_db'))
    
    print(f"Migrating {len(ai_scores)} AI score relationships...")
    
    all_paths = set()
    for entry in ai_scores.values():
        all_paths.add(entry['source_path'])
        all_paths.add(entry['target_path'])
        
    cursor.executemany("INSERT OR IGNORE INTO file_paths (file_path) VALUES (?)", [(p,) for p in all_paths])
    
    cursor.execute("SELECT id, file_path FROM file_paths")
    path_to_id = {path: id for id, path in cursor.fetchall()}
    
    relationships_to_insert = []
    for key, entry in ai_scores.items():
        source_id = path_to_id.get(entry['source_path'])
        target_id = path_to_id.get(entry['target_path'])
        
        if source_id is not None and target_id is not None:
            relationships_to_insert.append((
                source_id,
                target_id,
                entry.get('ai_score'),
                entry.get('jina_similarity'),
                entry.get('last_scored'),
                key,
                entry.get('key_type', 'full_path'),
                datetime.datetime.now(datetime.timezone.utc).isoformat()
            ))
            
    cursor.executemany(
        """
        INSERT INTO ai_relationships (source_file_id, target_file_id, ai_score, jina_similarity, last_scored, relationship_key, key_type, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        relationships_to_insert
    )
    
    conn.commit()
    conn.close()
    print(f"✅ Successfully migrated {len(ai_scores)} AI relationships to '{os.path.basename(db_path)}'.")

def sqlite_to_json(db_path, json_output_path, output_dir_name=".jina-linker"):
    """将SQLite数据库转换为JSON文件，用于与旧版插件兼容"""
    print(f"📤 导出数据库到JSON: {os.path.basename(db_path)} → {os.path.basename(json_output_path)}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取元数据
        metadata = {}
        cursor.execute("SELECT key, value FROM metadata")
        for key, value in cursor.fetchall():
            metadata[key] = value
        
        # 获取所有文件路径
        file_id_to_path = {}
        cursor.execute("SELECT id, file_path FROM file_paths")
        for row in cursor.fetchall():
            file_id, file_path = row
            file_id_to_path[file_id] = file_path
        
        # 获取所有关系
        ai_scores = {}
        cursor.execute("""
            SELECT source_file_id, target_file_id, ai_score, jina_similarity, 
                  last_scored, relationship_key, key_type
            FROM ai_relationships
        """)
        
        for row in cursor.fetchall():
            source_id, target_id, ai_score, jina_similarity, last_scored, key, key_type = row
            
            # 使用relationship_key作为键，如果不存在则构建一个
            if not key:
                source_path = file_id_to_path.get(source_id)
                target_path = file_id_to_path.get(target_id)
                key = f"{source_path}|{target_path}"
            
            # 构建关系对象
            ai_scores[key] = {
                "source_path": file_id_to_path.get(source_id),
                "target_path": file_id_to_path.get(target_id),
                "ai_score": ai_score,
                "jina_similarity": jina_similarity,
                "last_scored": last_scored if last_scored else datetime.datetime.now().isoformat(),
                "key_type": key_type if key_type else "full_path"
            }
        
        # 构建完整的JSON对象
        output_data = {
            "_metadata": {
                "description": "AI评分数据 (从SQLite导出)",
                "last_updated": datetime.datetime.now().isoformat(),
                "total_relationships": len(ai_scores),
                "exported_from": os.path.basename(db_path),
                "original_metadata": metadata
            },
            "ai_scores": ai_scores
        }
        
        # 确保输出目录存在
        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
        
        # 写入JSON文件
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
            
        conn.close()
        print(f"✅ 成功导出 {len(ai_scores)} 个AI关系到 '{os.path.basename(json_output_path)}'")
        return True
    
    except Exception as e:
        print(f"❌ 导出JSON时发生错误: {e}")
        return False

def export_embeddings_to_json(db_path, json_output_path):
    """将嵌入数据库导出为JSON格式，用于与旧版插件兼容"""
    print(f"📤 导出嵌入数据库到JSON: {os.path.basename(db_path)} → {os.path.basename(json_output_path)}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取元数据
        metadata = {}
        cursor.execute("SELECT key, value FROM metadata")
        for key, value in cursor.fetchall():
            metadata[key] = value
        
        # 获取嵌入数据
        files_data = {}
        cursor.execute("""
            SELECT file_path, content_hash, embedding, processed_content, embedding_dimension
            FROM file_embeddings
        """)
        
        for row in cursor.fetchall():
            file_path, content_hash, embedding_json, processed_content, dimension = row
            
            # 解析嵌入向量
            embedding = json.loads(embedding_json) if embedding_json else None
            
            files_data[file_path] = {
                "hash": content_hash,
                "embedding": embedding,
                "processed_content": processed_content
            }
        
        # 构建完整的JSON对象
        output_data = {
            "_metadata": {
                "generated_at_utc": metadata.get('created_at', datetime.datetime.now().isoformat()),
                "jina_model_name": metadata.get('jina_model_name', 'unknown'),
                "script_version": "2.0_plugin_compatible_json_export",
                "exported_from": os.path.basename(db_path)
            },
            "files": files_data
        }
        
        # 确保输出目录存在
        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
        
        # 写入JSON文件
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
            
        conn.close()
        print(f"✅ 成功导出 {len(files_data)} 个文件嵌入到 '{os.path.basename(json_output_path)}'")
        return True
    
    except Exception as e:
        print(f"❌ 导出嵌入JSON时发生错误: {e}")
        return False

def export_data_to_json_format(project_root_abs, output_dir_abs, export_dir_name=".jina-linker"):
    """导出AI评分数据为JSON格式，用于与旧版插件兼容"""
    print("\n📦 正在将AI评分数据导出为JSON格式(用于旧版插件兼容)...")
    
    # 确定目标路径
    json_dir = os.path.join(project_root_abs, export_dir_name)
    os.makedirs(json_dir, exist_ok=True)
    
    # 导出AI评分数据
    ai_scores_db = os.path.join(output_dir_abs, DEFAULT_AI_SCORES_FILE_NAME)
    ai_scores_json = os.path.join(json_dir, "ai_scores.json")
    
    if os.path.exists(ai_scores_db):
        sqlite_to_json(ai_scores_db, ai_scores_json, export_dir_name)
    else:
        print(f"⚠️ AI评分数据库不存在: {ai_scores_db}")
    
    print("📦 JSON导出完成!")

def run_migration_process(project_root_abs, output_dir_abs):
    """主执行函数"""
    print("🚀 Starting JSON to SQLite migration...")
    
    json_dir = os.path.join(project_root_abs, ".Jina-AI-Linker-Output")
    if not os.path.exists(json_dir):
        print(f"Info: JSON source directory '{json_dir}' not found. Nothing to migrate.")

    os.makedirs(output_dir_abs, exist_ok=True)
    
    migrate_embeddings_json_to_sqlite(project_root_abs, output_dir_abs)
    print("-" * 20)
    migrate_ai_scores_json_to_sqlite(project_root_abs, output_dir_abs)
    
    print("\n🎉 Migration process completed.")

# --- Default constants for argparse ---
DEFAULT_EMBEDDINGS_FILE_NAME = "jina_embeddings.db"
DEFAULT_AI_SCORES_FILE_NAME = "ai_scores.db"
DEFAULT_SIMILARITY_THRESHOLD = 0.70

# --- 数据库 Schema 定义 ---
EMBEDDINGS_DB_SCHEMA = """
CREATE TABLE metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE file_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    content_hash TEXT NOT NULL,
    embedding BLOB,
    processed_content TEXT,
    embedding_dimension INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_file_path ON file_embeddings(file_path);
CREATE INDEX idx_content_hash ON file_embeddings(content_hash);
INSERT INTO metadata (key, value) VALUES 
    ('schema_version', '1.0'),
    ('database_type', 'embeddings'),
    ('created_at', datetime('now'));
"""

AI_SCORES_DB_SCHEMA = """
CREATE TABLE metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE file_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE ai_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_id INTEGER NOT NULL,
    target_file_id INTEGER NOT NULL,
    ai_score INTEGER,
    jina_similarity REAL,
    last_scored TIMESTAMP,
    relationship_key TEXT,
    key_type TEXT DEFAULT 'full_path',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_file_id) REFERENCES file_paths(id) ON DELETE CASCADE,
    FOREIGN KEY (target_file_id) REFERENCES file_paths(id) ON DELETE CASCADE,
    UNIQUE(source_file_id, target_file_id)
);
CREATE INDEX idx_file_paths_path ON file_paths(file_path);
CREATE INDEX idx_ai_relationships_key ON ai_relationships(relationship_key);
INSERT INTO metadata (key, value) VALUES 
    ('schema_version', '1.0'),
    ('database_type', 'ai_scores'),
    ('created_at', datetime('now'));
"""


def main():
    print("🚀 Jina AI 处理工具启动 (SQLite版)")
    parser = argparse.ArgumentParser(description="Jina AI 处理工具 - 处理笔记内容并提取嵌入。")
    parser.add_argument('--project_root', type=str, required=True, help='项目根目录的绝对路径')
    parser.add_argument('--output_dir', type=str, default='.', help='输出数据库文件的目录路径（相对于项目根目录）')
    parser.add_argument('--jina_api_key', type=str, default='', help='Jina API 密钥')
    # AI 提供商参数
    parser.add_argument('--ai_provider', type=str, default='', help='AI 提供商 (deepseek, openai, claude, gemini, custom)')
    parser.add_argument('--ai_api_url', type=str, default='', help='AI API URL')
    parser.add_argument('--ai_api_key', type=str, default='', help='AI API 密钥（用于 AI 打分）')
    parser.add_argument('--ai_model_name', type=str, default='', help='AI 模型名称')
    
    # 其他参数
    parser.add_argument('--similarity_threshold', type=float, default=0.7, help='相似度阈值（0-1之间）')
    parser.add_argument('--scan_target_folders', nargs='*', default=[], help='要扫描的文件夹（相对于项目根目录）')
    parser.add_argument('--excluded_folders', nargs='*', default=[], help='要排除的文件夹列表')
    parser.add_argument('--excluded_files_patterns', nargs='*', default=[], help='要排除的文件名模式列表')
    parser.add_argument('--jina_model_name', type=str, default='jina-embeddings-v3', help='Jina 模型名称')
    parser.add_argument('--max_chars_for_jina', type=int, default=8000, help='传递给 Jina 的最大字符数')
    parser.add_argument('--max_content_length_for_ai', type=int, default=5000, help='传递给 AI 评分的每篇笔记的最大内容长度')
    parser.add_argument('--max_candidates_per_source_for_ai_scoring', type=int, default=20, help='每个源笔记发送给 AI 评分的最大候选链接数 (此参数当前版本中未使用)')
    parser.add_argument('--ai_scoring_mode', type=str, choices=['force', 'smart', 'skip'], default='smart', help='AI 评分模式')
    parser.add_argument('--hash_boundary_marker', type=str, default='<!-- HASH_BOUNDARY -->', help='哈希计算边界标记')
    parser.add_argument('--migrate', action='store_true', help='Run data migration from JSON to SQLite.')
    parser.add_argument('--export_json', action='store_true', help='同时导出数据到JSON格式，用于旧版插件兼容')
    parser.add_argument('--export_json_only', action='store_true', help='仅从数据库导出JSON，不执行其他操作')
    parser.add_argument('--no_export_json', action='store_true', help='禁用自动JSON导出功能')
    # 批处理参数
    parser.add_argument('--embedding_batch_size', type=int, default=EMBEDDING_BATCH_SIZE, help='嵌入批处理大小，一次向Jina API发送的笔记数量')
    parser.add_argument('--ai_scoring_batch_size', type=int, default=AI_SCORING_BATCH_SIZE, help='AI评分批处理大小，一次向AI API发送的笔记对数量')

    args = parser.parse_args()
    start_time = time.time()

    project_root_abs = os.path.abspath(args.project_root)
    output_dir_abs = os.path.join(project_root_abs, args.output_dir)
    os.makedirs(output_dir_abs, exist_ok=True)

    if args.export_json_only:
        export_data_to_json_format(project_root_abs, output_dir_abs)
        return

    if args.migrate:
        run_migration_process(project_root_abs, output_dir_abs)
        # 自动导出为JSON(除非明确禁用)
        if not args.no_export_json:
            export_data_to_json_format(project_root_abs, output_dir_abs)
        return

    # 数据库路径
    embeddings_db_path = os.path.join(output_dir_abs, DEFAULT_EMBEDDINGS_FILE_NAME)
    ai_scores_db_path = os.path.join(output_dir_abs, DEFAULT_AI_SCORES_FILE_NAME)

    # 初始化数据库
    initialize_database(embeddings_db_path, EMBEDDINGS_DB_SCHEMA)
    initialize_database(ai_scores_db_path, AI_SCORES_DB_SCHEMA)

    # 处理扫描目标
    scan_paths = [os.path.join(project_root_abs, p) for p in args.scan_target_folders] if args.scan_target_folders else [project_root_abs]
    
    print(f"===== Jina处理启动 =====")
    print(f"💾 数据库位置: {args.output_dir}")
    print(f"🤖 Jina模型: {args.jina_model_name}")
    
    # 扫描文件
    print(f"\n📝 步骤 1：扫描 Markdown 文件...")
    markdown_files_to_process = []
    for path in scan_paths:
        markdown_files_to_process.extend(list_markdown_files(
            path, 
            project_root_abs,
            excluded_folders=args.excluded_folders,
            excluded_files_patterns=args.excluded_files_patterns
        ))
    markdown_files_to_process = sorted(list(set(markdown_files_to_process)))

    if not markdown_files_to_process:
        print("  没有找到符合条件的 Markdown 文件！")
        return
    print(f"  找到 {len(markdown_files_to_process)} 个 Markdown 文件。")
    
    # 生成嵌入
    print(f"\n🧠 步骤 2：处理笔记并生成嵌入...")
    embeddings_data = process_and_embed_notes(
        project_root_abs,
        markdown_files_to_process,
        embeddings_db_path,
        jina_api_key_to_use=args.jina_api_key,
        jina_model_name_to_use=args.jina_model_name,
        max_chars_for_jina_to_use=args.max_chars_for_jina,
        embedding_batch_size=args.embedding_batch_size
    )
    
    if not embeddings_data or not embeddings_data.get('files'):
        print("  错误：没有成功处理任何文件或生成嵌入。")
        return
    
    # 生成候选对
    print(f"\n🔗 步骤 3：根据相似度阈值 {args.similarity_threshold} 生成候选链接对...")
    candidate_pairs = generate_candidate_pairs(embeddings_data, args.similarity_threshold)
    print(f"  共生成 {len(candidate_pairs)} 个候选链接对。")
    
    # AI 评分
    if args.ai_api_key and args.ai_scoring_mode != 'skip' and candidate_pairs:
        print(f"\n🤖 步骤 4：使用 {args.ai_provider} AI 对候选链接进行评分...")
        score_candidates_and_update_frontmatter(
            candidate_pairs,
            project_root_abs,
            embeddings_db_path,
            ai_scores_db_path,
            ai_provider=args.ai_provider,
            ai_api_url=args.ai_api_url,
            ai_api_key=args.ai_api_key,
            ai_model_name=args.ai_model_name,
            max_content_length_for_ai_to_use=args.max_content_length_for_ai,
            force_rescore=(args.ai_scoring_mode == 'force'),
            ai_scoring_batch_size=args.ai_scoring_batch_size
        )
    else:
        print(f"\n⏭️ 步骤 4：跳过 AI 评分。")
    
    # 自动导出为JSON(除非明确禁用或显式使用export_json参数)
    if not args.no_export_json or args.export_json:
        export_data_to_json_format(project_root_abs, output_dir_abs)
    
    end_time = time.time()
    print(f"\n✅ ===== 处理完成 =====")
    print(f"⏱️ 总耗时: {end_time - start_time:.2f} 秒")

if __name__ == "__main__":
    main()