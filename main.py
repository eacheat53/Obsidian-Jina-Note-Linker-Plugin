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

def process_and_embed_notes(
    project_root_abs: str,
    files_relative_to_project_root: list,
    embeddings_db_path: str,
    jina_api_key_to_use: str,
    jina_model_name_to_use: str,
    max_chars_for_jina_to_use: int
) -> dict:
    """
    处理笔记，生成嵌入并将其存储在 SQLite 数据库中。
    返回一个与旧版兼容的字典，用于后续步骤。
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

    for i, file_rel_path in enumerate(files_relative_to_project_root):
        file_abs_path = os.path.join(project_root_abs, file_rel_path)
        print(f"处理文件 ({i+1}/{len(files_relative_to_project_root)}): {file_rel_path}")
        
        if not os.path.exists(file_abs_path):
            print(f"  错误：文件 {file_rel_path} 不存在，从数据库中删除。")
            cursor.execute("DELETE FROM file_embeddings WHERE file_path = ?", (file_rel_path,))
            if file_rel_path in all_files_data_for_return:
                del all_files_data_for_return[file_rel_path]
            continue

        try:
            original_body_content, existing_frontmatter, _ = read_markdown_with_frontmatter(file_abs_path)
        except Exception as e:
            print(f"  错误：读取文件 {file_rel_path} 失败: {e}。跳过。")
            continue
        
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
                final_embedding = None
            else:
                text_for_embedding = text_for_processing[:max_chars_for_jina_to_use]
                embedding_from_api = get_jina_embedding(text_for_embedding, jina_api_key_to_use, jina_model_name_to_use)
                if embedding_from_api:
                    final_embedding = embedding_from_api
                    embedded_count += 1
                    print(f"  成功获取嵌入: {file_rel_path} (哈希: {current_content_hash[:8]}...)")
                else:
                    final_embedding = None
                    print(f"  未能获取嵌入: {file_rel_path}")
        
        # 更新 frontmatter 中的哈希
        if existing_frontmatter.get("jina_hash") != current_content_hash:
            existing_frontmatter["jina_hash"] = current_content_hash
            try:
                write_markdown_with_frontmatter(file_abs_path, existing_frontmatter, original_body_content)
            except Exception as e_write:
                print(f"  错误：写入 frontmatter 到 {file_rel_path} 失败: {e_write}")

        # 更新数据库
        embedding_json = json.dumps(final_embedding) if final_embedding else None
        dimension = len(final_embedding) if final_embedding else 0
        
        cursor.execute(
            """
            INSERT OR REPLACE INTO file_embeddings 
            (file_path, content_hash, embedding, processed_content, embedding_dimension, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                file_rel_path,
                current_content_hash,
                embedding_json,
                text_for_processing,
                dimension,
                datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
        )

        # 更新用于返回的字典
        all_files_data_for_return[file_rel_path] = {
            "embedding": final_embedding,
            "hash": current_content_hash,
            "processed_content": text_for_processing
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
    actual_embeddings_data = {}
    if isinstance(embeddings_data_input, dict) and "files" in embeddings_data_input: # 检查新结构
        actual_embeddings_data = embeddings_data_input["files"]
    elif isinstance(embeddings_data_input, dict): # 兼容旧结构
        actual_embeddings_data = {k:v for k,v in embeddings_data_input.items() if k != "_metadata"}
    else:
        print("错误：传入 generate_candidate_pairs 的 embeddings_data_input 格式不正确。")
        return []

    processed_embeddings = {}
    for path, data_entry in actual_embeddings_data.items():
        if data_entry and isinstance(data_entry, dict) and \
           "embedding" in data_entry and data_entry["embedding"] and isinstance(data_entry["embedding"], list):
            processed_embeddings[path] = data_entry["embedding"]
        
    file_paths = list(processed_embeddings.keys())
    if len(file_paths) < 2:
        print("有效嵌入少于2个，无法生成候选对。")
        return []
    
    candidate_pairs = []
    print(f"开始从 {len(file_paths)} 个有效嵌入笔记中全新生成候选对...")
    total_comparisons = len(file_paths) * (len(file_paths) - 1) // 2
    
    processed_pairs_count = 0
    for i in range(len(file_paths)):
        for j in range(i + 1, len(file_paths)):
            path1, path2 = file_paths[i], file_paths[j]
            emb1, emb2 = processed_embeddings[path1], processed_embeddings[path2]
            similarity = cosine_similarity(emb1, emb2)
            processed_pairs_count += 1
            if processed_pairs_count % 5000 == 0 or processed_pairs_count == total_comparisons:
                print(f"  已比较 {processed_pairs_count}/{total_comparisons} 对笔记...")

            if similarity >= similarity_threshold:
                # 生成双向关系，但避免在AI打分阶段重复处理
                candidate_pairs.append({
                    "source_path": path1, 
                    "target_path": path2, 
                    "jina_similarity": similarity,
                    "pair_id": f"{min(path1, path2)}<->{max(path1, path2)}"  # 唯一标识符
                })
                candidate_pairs.append({
                    "source_path": path2, 
                    "target_path": path1, 
                    "jina_similarity": similarity,
                    "pair_id": f"{min(path1, path2)}<->{max(path1, path2)}"  # 相同的标识符
                })
    
    final_map = {}
    for p in candidate_pairs:
        src_path_norm = p["source_path"].replace(os.sep, '/')
        tgt_path_norm = p["target_path"].replace(os.sep, '/')
        key = (src_path_norm, tgt_path_norm, round(p["jina_similarity"], 6))
        if key not in final_map:
            p_norm = p.copy()
            p_norm["source_path"] = src_path_norm
            p_norm["target_path"] = tgt_path_norm
            final_map[key] = p_norm
    
    unique_sorted_pairs = sorted(
        list(final_map.values()),
        key=lambda x: (x["source_path"], -x["jina_similarity"], x["target_path"])
    )
    print(f"最终生成 {len(unique_sorted_pairs)} 个候选链接对。")
    return unique_sorted_pairs

# REMOVED: get_deepseek_api_key function. Key is passed directly.

def call_ai_api_for_pair_relevance(
    source_processed_content: str,  # 已经处理过的内容，不需要再次提取
    target_processed_content: str,  # 已经处理过的内容，不需要再次提取
    source_file_path: str,
    target_file_path: str, 
    api_key: str,
    # --- AI 提供商参数 ---
    ai_provider: str,
    ai_api_url: str,
    ai_model_name: str,
    max_content_length_for_ai_to_use: int,
    max_retries: int = 3,
    initial_delay: float = 1.0
) -> dict:
    if not api_key:
        print(f"错误：{ai_provider} API Key 未配置。无法为 {source_file_path} -> {target_file_path} 打分。")
        return {"ai_score": -1, "error": "API Key not configured"}

    source_file_name = os.path.basename(source_file_path)
    target_file_name = os.path.basename(target_file_path)

    # 直接使用已经处理过的内容，不需要再次检查哈希边界标记
    source_excerpt = source_processed_content[:max_content_length_for_ai_to_use]
    target_excerpt = target_processed_content[:max_content_length_for_ai_to_use]

    # 构建请求体和头部，根据不同AI提供商调整
    request_body, headers = build_ai_request(
        ai_provider, ai_model_name, api_key, source_file_name, target_file_name,
        source_excerpt, target_excerpt, max_content_length_for_ai_to_use
    )

    print(f"  AI打分 (调用{ai_provider} API): {source_file_path} -> {target_file_path}")
    
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            # 对于Gemini，需要在URL中添加API密钥
            if ai_provider == 'gemini':
                # 构建完整的Gemini API URL
                model_path = ai_model_name if ai_model_name else 'gemini-1.5-flash'
                full_url = f"{ai_api_url}/{model_path}:generateContent?key={api_key}"
            else:
                full_url = ai_api_url
                
            # 延迟由调用者处理 (score_candidates_and_update_frontmatter)
            response = requests.post(full_url, headers=headers, json=request_body, timeout=45)
            
            if not response.ok:
                error_message = f"{ai_provider} API 失败 {source_file_path}->{target_file_path}: HTTP {response.status_code}"
                try: error_message += f" - {response.json()}"
                except json.JSONDecodeError: error_message += f" - {response.text[:200]}"
                print(error_message)
                # 如果是客户端错误（如4xx），则不重试
                if 400 <= response.status_code < 500:
                    return {"ai_score": -1, "error": f"API Error: HTTP {response.status_code}"}
                # 对于服务器错误，进行重试
                raise requests.exceptions.RequestException(f"Server error: {response.status_code}")

            # 解析响应，根据不同AI提供商调整
            score = parse_ai_response(response, ai_provider, source_file_path, target_file_path)
            if score is not None:
                return {"ai_score": score}
            else:
                return {"ai_score": -1, "error": "Failed to parse AI response"} # 解析失败，不重试
                
        except requests.exceptions.Timeout:
            print(f"{ai_provider} API 超时 (尝试 {attempt + 1}/{max_retries}) {source_file_path}->{target_file_path}")
            time.sleep(delay)
            delay *= 2
        except requests.exceptions.RequestException as e:
            print(f"{ai_provider} API 请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            time.sleep(delay)
            delay *= 2
        except Exception as e_unknown: # 捕获更广泛的异常
            print(f"{ai_provider} API 未知错误 {source_file_path}->{target_file_path}: {e_unknown}")
            return {"ai_score": -1, "error": f"Unknown API call error: {e_unknown}"} # 未知错误，不重试
            
    print(f"错误：达到最大重试次数 {max_retries} 后，AI API 调用仍然失败。")
    return {"ai_score": -1, "error": "API call failed after multiple retries"}


def build_ai_request(ai_provider: str, model_name: str, api_key: str, 
                    source_file_name: str, target_file_name: str,
                    source_excerpt: str, target_excerpt: str, 
                    max_content_length: int) -> tuple[dict, dict]:
    """构建不同AI提供商的请求体和头部"""
    
    # 使用 .format() 来避免 f-string 嵌套大括号的问题
    prompt_template = """你是一个 Obsidian 笔记链接评估助手。请直接比较以下【源笔记内容】和【目标笔记内容】，判断它们之间的相关性。
你的任务是评估从源笔记指向目标笔记建立一个链接是否合适。
请给出 0-10 之间的整数评分，其中 10 表示极其相关，7-9 表示比较相关，6 表示你认为合格的相关性，1-5 表示弱相关，0 表示不相关或无法判断。

源笔记文件名: {source_file_name}
目标笔记文件名: {target_file_name}

【源笔记内容】(最多 {max_content_length} 字符):
---
{source_excerpt}
---

【目标笔记内容】(最多 {max_content_length} 字符):
---
{target_excerpt}
---

请严格按照以下 JSON 格式返回你的评分: {{"relevance_score": <你的评分>}}
例如: {{"relevance_score": 8}}
返回纯粹的JSON，不包含任何Markdown标记."""

    prompt = prompt_template.format(
        source_file_name=source_file_name,
        target_file_name=target_file_name,
        max_content_length=max_content_length,
        source_excerpt=source_excerpt,
        target_excerpt=target_excerpt
    )

    if ai_provider == 'claude':
        # Claude API 格式
        request_body = {
            "model": model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]
        }
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01'
        }
    elif ai_provider == 'gemini':
        # Gemini API 格式
        request_body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        headers = {
            'Content-Type': 'application/json'
        }
    else:
        # OpenAI 兼容格式 (DeepSeek, OpenAI, Custom)
        request_body = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        if ai_provider in ['deepseek', 'openai']:
            request_body["response_format"] = {"type": "json_object"}
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
    
    return request_body, headers


def parse_ai_response(response: requests.Response, ai_provider: str, 
                     source_file_path: str, target_file_path: str) -> int | None:
    """解析不同AI提供商的响应"""
    try:
        data = response.json()
        
        message_content_str = ""
        if ai_provider == 'claude':
            if data and data.get("content") and len(data["content"]) > 0:
                message_content_str = data["content"][0].get("text", "")
        elif ai_provider == 'gemini':
            if data and data.get("candidates") and len(data["candidates"]) > 0:
                content = data["candidates"][0].get("content", {})
                if content.get("parts") and len(content["parts"]) > 0:
                    message_content_str = content["parts"][0].get("text", "")
        else: # OpenAI 兼容格式
            if data and data.get("choices") and data["choices"][0].get("message", {}).get("content"):
                message_content_str = data["choices"][0]["message"]["content"]

        if not message_content_str:
            print(f"{ai_provider} API 响应格式不符或内容为空 {source_file_path}->{target_file_path}: {data}")
            return None

        # 解析JSON评分
        try:
            cleaned_json_str = re.sub(r'^```json\s*|\s*```$', '', message_content_str.strip(), flags=re.DOTALL)
            parsed_json = json.loads(cleaned_json_str)
            if isinstance(parsed_json.get("relevance_score"), (int, float)):
                score = max(0, min(10, round(float(parsed_json["relevance_score"]))))
                return score
            else:
                print(f"{ai_provider} API JSON 结构不完整 {source_file_path}->{target_file_path}: {parsed_json}")
                return None
        except json.JSONDecodeError as e_json:
            print(f"{ai_provider} API 响应非JSON {source_file_path}->{target_file_path}: '{message_content_str}', Error: {e_json}")
            return None
            
    except json.JSONDecodeError as e:
        print(f"{ai_provider} API 响应解析失败 {source_file_path}->{target_file_path}: {e}")
        return None


def normalize_path_python(path_str: str) -> str:
    if not path_str: return ""
    return path_str.replace(os.sep, '/')

def score_candidates_and_update_frontmatter(
    candidate_pairs_list: list,
    project_root_abs: str,
    embeddings_db_path: str,
    ai_scores_db_path: str,
    ai_provider: str,
    ai_api_url: str,
    ai_api_key: str,
    ai_model_name: str,
    max_content_length_for_ai_to_use: int,
    force_rescore: bool
):
    if not ai_api_key:
        print(f"错误：{ai_provider} API Key 未提供，跳过 AI 打分流程。")
        return

    print("正在对候选对进行去重以避免重复AI打分...")
    unique_pairs_for_ai = {}
    for pair in candidate_pairs_list:
        pair_id = pair.get("pair_id")
        if pair_id and pair_id not in unique_pairs_for_ai:
            unique_pairs_for_ai[pair_id] = pair

    print(f"去重后需要AI打分的唯一关系对数量: {len(unique_pairs_for_ai)} (原始: {len(candidate_pairs_list)})")

    ai_score_cache = load_ai_scores_from_db(ai_scores_db_path)

    # 从嵌入数据库一次性加载所有处理过的内容
    embeddings_conn = get_db_connection(embeddings_db_path)
    embeddings_cursor = embeddings_conn.cursor()
    embeddings_cursor.execute("SELECT file_path, processed_content FROM file_embeddings")
    processed_content_cache = {row[0]: row[1] for row in embeddings_cursor.fetchall()}
    embeddings_conn.close()
    print(f"✅ 成功从嵌入数据库加载 {len(processed_content_cache)} 条内容用于AI评分。")

    total_unique_pairs = len(unique_pairs_for_ai)
    processed_unique_pairs = 0
    
    for pair_id, pair in unique_pairs_for_ai.items():
        processed_unique_pairs += 1
        source_path = pair["source_path"]
        target_path = pair["target_path"]
        
        print(f"  AI打分唯一对 ({processed_unique_pairs}/{total_unique_pairs}): {source_path} <-> {target_path}")
        
        if not force_rescore and pair_id in ai_score_cache:
            print(f"    AI评分已存在于缓存中 (评分: {ai_score_cache[pair_id]}/10)，跳过")
            continue
        
        clean_source_body = processed_content_cache.get(source_path)
        clean_target_body = processed_content_cache.get(target_path)

        if clean_source_body is None or clean_target_body is None:
            print(f"    ❌ 无法从嵌入数据库获取内容，跳过AI打分: {source_path} 或 {target_path}")
            continue
            
        time.sleep(AI_API_REQUEST_DELAY_SECONDS)
        
        try:
            ai_result = call_ai_api_for_pair_relevance(
                clean_source_body,
                clean_target_body,
                source_path,
                target_path,
                ai_api_key,
                ai_provider,
                ai_api_url,
                ai_model_name,
                max_content_length_for_ai_to_use
            )
            
            if "ai_score" in ai_result and ai_result["ai_score"] != -1:
                ai_score = ai_result["ai_score"]
                ai_score_cache[pair_id] = ai_score
                print(f"    AI评分成功: {ai_score}/10")
            else:
                print(f"    AI评分失败: {ai_result.get('error', '未知错误')}")
        except Exception as e:
            print(f"    AI打分异常: {e}")

    print(f"\n保存AI评分结果到数据库...")
    save_ai_scores_to_db(ai_score_cache, unique_pairs_for_ai, ai_scores_db_path)
    
    print(f"\nAI 打分完成。AI评分数据已保存到: {os.path.basename(ai_scores_db_path)}")

def save_ai_scores_to_db(ai_score_cache: dict, unique_pairs_for_ai: dict, ai_scores_db_path: str):
    """将AI评分结果保存到 ai_scores.db"""
    conn = get_db_connection(ai_scores_db_path)
    cursor = conn.cursor()
    
    try:
        # 提取所有唯一文件路径
        all_paths = set()
        for pair_info in unique_pairs_for_ai.values():
            all_paths.add(pair_info['source_path'])
            all_paths.add(pair_info['target_path'])
            
        # 插入新的文件路径
        cursor.executemany("INSERT OR IGNORE INTO file_paths (file_path) VALUES (?)", [(p,) for p in all_paths])
        
        # 创建路径到ID的映射
        cursor.execute("SELECT id, file_path FROM file_paths")
        path_to_id = {path: id for id, path in cursor.fetchall()}
        
        relationships_to_update = []
        for pair_id, ai_score in ai_score_cache.items():
            if pair_id in unique_pairs_for_ai:
                pair_info = unique_pairs_for_ai[pair_id]
                source_id = path_to_id.get(pair_info["source_path"])
                target_id = path_to_id.get(pair_info["target_path"])
                
                if source_id is not None and target_id is not None:
                    relationships_to_update.append((
                        source_id,
                        target_id,
                        ai_score,
                        round(pair_info["jina_similarity"], 6),
                        datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        pair_id,
                        'full_path',
                        datetime.datetime.now(datetime.timezone.utc).isoformat()
                    ))

        if relationships_to_update:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO ai_relationships 
                (source_file_id, target_file_id, ai_score, jina_similarity, last_scored, relationship_key, key_type, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                relationships_to_update
            )
        
        # 更新元数据
        cursor.execute("UPDATE metadata SET value = ? WHERE key = 'last_updated'", (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
        cursor.execute("SELECT COUNT(*) FROM ai_relationships")
        total_relationships = cursor.fetchone()[0]
        cursor.execute("UPDATE metadata SET value = ? WHERE key = 'total_relationships'", (str(total_relationships),))

        conn.commit()
        print(f"✅ AI评分数据已保存: {len(relationships_to_update)} 个关系已更新/插入到数据库。")
            
    except Exception as e:
        conn.rollback()
        print(f"❌ 保存AI评分数据到数据库失败: {e}")
    finally:
        conn.close()

def load_ai_scores_from_db(ai_scores_db_path: str) -> dict:
    """从 ai_scores.db 加载AI评分数据"""
    ai_scores = {}
    if not os.path.exists(ai_scores_db_path):
        return ai_scores
    
    conn = get_db_connection(ai_scores_db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT relationship_key, ai_score FROM ai_relationships WHERE ai_score IS NOT NULL")
        for row in cursor.fetchall():
            ai_scores[row[0]] = row[1]
        print(f"📖 从数据库加载了 {len(ai_scores)} 个AI评分记录")
    except Exception as e:
        print(f"⚠️ 加载AI评分数据库失败: {e}")
    finally:
        conn.close()
        
    return ai_scores

# --- 数据迁移函数 ---

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

    args = parser.parse_args()
    start_time = time.time()

    project_root_abs = os.path.abspath(args.project_root)
    output_dir_abs = os.path.join(project_root_abs, args.output_dir)
    os.makedirs(output_dir_abs, exist_ok=True)

    if args.migrate:
        run_migration_process(project_root_abs, output_dir_abs)
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
        max_chars_for_jina_to_use=args.max_chars_for_jina
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
            force_rescore=(args.ai_scoring_mode == 'force')
        )
    else:
        print(f"\n⏭️ 步骤 4：跳过 AI 评分。")
    
    end_time = time.time()
    print(f"\n✅ ===== 处理完成 =====")
    print(f"⏱️ 总耗时: {end_time - start_time:.2f} 秒")

if __name__ == "__main__":
    main()