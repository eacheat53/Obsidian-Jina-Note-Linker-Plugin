# -*- coding: utf-8 -*-
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
from pathlib import Path # For path operations

# Ensure stdout and stderr use UTF-8 encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

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

# --- Frontmatter Key 常量 ---
# 此键名现在由脚本内部固定，应与 TypeScript 插件中的常量保持一致
AI_JUDGED_CANDIDATES_FM_KEY = "ai_judged_candidates"

# --- 哈希边界标记常量 ---
# 此标记用于界定笔记内容哈希计算的边界，此边界后的内容不参与哈希计算
HASH_BOUNDARY_MARKER = "<!-- HASH_BOUNDARY -->"

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

    trimmed_content = full_content.lstrip()
    if trimmed_content.startswith("---"):
        end_frontmatter_index = trimmed_content.find("---", 3)
        if end_frontmatter_index != -1:
            frontmatter_block = trimmed_content[3:end_frontmatter_index].strip()
            body_content = trimmed_content[end_frontmatter_index + 3:].lstrip()
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
        # Use ruamel.yaml for better round-trip preservation if needed, but for simple dump, pyyaml is fine.
        # For consistency with 1.py, let's use ruamel.yaml's dump if possible, but it's not imported globally.
        # Sticking to pyyaml's dump for now as it's already imported.
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
                       jina_model_name_to_use: str) -> list | None: # Added params
    """调用 Jina API 获取文本的嵌入向量"""
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
    try:
        time.sleep(JINA_API_REQUEST_DELAY) # Still uses global constant, could be made a param
        response = requests.post(JINA_API_URL, headers=headers, data=json.dumps(data), timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if result.get("data") and len(result["data"]) > 0 and result["data"][0].get("embedding"):
            return result["data"][0]["embedding"]
        else:
            print(f"错误：Jina API 响应格式不正确。响应: {result}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"错误：调用 Jina API 失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"响应状态码: {e.response.status_code}, 响应内容: {e.response.text[:500]}...")
        return None
    except Exception as e:
        print(f"处理 Jina API 响应时发生未知错误: {e}")
        return None

class EmbeddingEncoder(json.JSONEncoder):
    def iterencode(self, obj, _one_shot=False):
        if isinstance(obj, dict):
            for chunk in super().iterencode(obj, _one_shot):
                yield chunk
        elif isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], (int, float)):
            if len(obj) > 50: 
                yield '['
                yield ', '.join(f"{x:.8f}" for x in obj) 
                yield ']'
            else:
                for chunk in super().iterencode(obj, _one_shot):
                    yield chunk
        else:
            for chunk in super().iterencode(obj, _one_shot):
                yield chunk

def process_and_embed_notes(
    project_root_abs: str,
    files_relative_to_project_root: list,
    embeddings_file_path: str,
    # --- Added parameters ---
    jina_api_key_to_use: str,
    jina_model_name_to_use: str,
    max_chars_for_jina_to_use: int
) -> dict:
    loaded_json_structure = {}
    files_data_from_json = {}
    metadata_from_json = {}  

    if os.path.exists(embeddings_file_path):
        try:
            with open(embeddings_file_path, 'r', encoding='utf-8') as f:
                loaded_json_structure = json.load(f)
                if isinstance(loaded_json_structure, dict):
                    files_data_from_json = loaded_json_structure.get("files", {})
                    metadata_from_json = loaded_json_structure.get("_metadata", {})
                    if not isinstance(files_data_from_json, dict):
                        files_data_from_json = {}
                    if not isinstance(metadata_from_json, dict):
                        metadata_from_json = {}
                else:
                    print(f"警告：JSON文件 {embeddings_file_path} 顶层不是字典。") # Clearer warning
        except Exception as e:
            print(f"警告：加载嵌入数据文件 {embeddings_file_path} 失败: {e}。")

    embedded_count = 0
    processed_files_this_run = 0
    
    for i, file_rel_path in enumerate(files_relative_to_project_root):
        file_abs_path = os.path.join(project_root_abs, file_rel_path)
        print(f"处理文件 ({i+1}/{len(files_relative_to_project_root)}): {file_rel_path}")
        
        if not os.path.exists(file_abs_path):
            print(f"  错误：文件 {file_rel_path} 不存在，跳过。")
            if file_rel_path in files_data_from_json:
                del files_data_from_json[file_rel_path]
            continue

        original_body_content_from_read_fn = ""
        existing_frontmatter = {}
        try:
            original_body_content_from_read_fn, existing_frontmatter, _ = read_markdown_with_frontmatter(file_abs_path)
        except Exception as e:
            print(f"  错误：读取文件 {file_rel_path} 失败: {e}。跳过。")
            if file_rel_path in files_data_from_json:
                del files_data_from_json[file_rel_path]
            continue
        
        text_for_processing = extract_content_for_hashing(original_body_content_from_read_fn)
        
        if text_for_processing is None:
            print(f"  错误: 笔记 '{file_rel_path}' 中未找到哈希边界标记 '{HASH_BOUNDARY_MARKER}'。跳过。")
            if file_rel_path in files_data_from_json:
                del files_data_from_json[file_rel_path]
            continue

        current_content_hash = calculate_hash_from_content(text_for_processing)
        stored_hash_in_frontmatter = existing_frontmatter.get("jina_hash")

        needs_embedding_api_call = True
        final_embedding_for_json = None

        if stored_hash_in_frontmatter and stored_hash_in_frontmatter == current_content_hash:
            json_entry = files_data_from_json.get(file_rel_path)
            if json_entry and isinstance(json_entry, dict) and json_entry.get("hash") == current_content_hash:
                if json_entry.get("embedding") is not None:
                    final_embedding_for_json = json_entry["embedding"]
                    needs_embedding_api_call = False
                else: 
                    final_embedding_for_json = None
                    needs_embedding_api_call = False
        elif stored_hash_in_frontmatter:
             print(f"  内容已修改 (frontmatter哈希 '{stored_hash_in_frontmatter[:8]}' vs 当前 \'{current_content_hash[:8]}\')。")
        else:
            print(f"  新文件或frontmatter中无哈希。")

        if needs_embedding_api_call:
            processed_files_this_run += 1
            if not text_for_processing.strip():
                print(f"  警告：文件 {file_rel_path} 有效内容为空。不嵌入。")
                final_embedding_for_json = None
            else:
                if len(text_for_processing) > max_chars_for_jina_to_use:
                    print(f"  警告：文件 {file_rel_path} 内容过长 ({len(text_for_processing)} chars)，截断至 {max_chars_for_jina_to_use} 进行嵌入。")
                    text_for_processing_truncated = text_for_processing[:max_chars_for_jina_to_use]
                else:
                    text_for_processing_truncated = text_for_processing

                embedding_from_api = get_jina_embedding(text_for_processing_truncated, jina_api_key_to_use, jina_model_name_to_use)
                if embedding_from_api:
                    final_embedding_for_json = embedding_from_api
                    embedded_count += 1
                    print(f"  成功获取嵌入: {file_rel_path} (哈希: {current_content_hash[:8]}...)")
                else:
                    final_embedding_for_json = None
                    print(f"  未能获取嵌入: {file_rel_path}")
        
        existing_frontmatter["jina_hash"] = current_content_hash
        try:
            write_markdown_with_frontmatter(file_abs_path, existing_frontmatter, original_body_content_from_read_fn)
        except Exception as e_write:
            print(f"  错误：写入 frontmatter 到 {file_rel_path} 失败: {e_write}")

        files_data_from_json[file_rel_path] = {
            "embedding": final_embedding_for_json,
            "hash": current_content_hash
        }

    final_metadata = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "jina_model_name": jina_model_name_to_use, # Use passed model name
        "script_version": "2.0_plugin_compatible" 
    }
    
    output_for_return_and_saving = {
        "_metadata": final_metadata,
        "files": files_data_from_json
    }
    
    needs_saving = os.path.exists(embeddings_file_path) or processed_files_this_run > 0

    if needs_saving:
        try:
            with open(embeddings_file_path, 'w', encoding='utf-8') as f:
                json.dump(output_for_return_and_saving, f, ensure_ascii=False, indent=4, cls=EmbeddingEncoder)
            print(f"嵌入数据已保存到 {embeddings_file_path}。本次嵌入/更新 {embedded_count} 条。处理了 {processed_files_this_run} 个文件。")
        except Exception as e:
            print(f"错误：保存嵌入数据到 {embeddings_file_path} 失败: {e}")
            
    return output_for_return_and_saving

def cosine_similarity(vec1: list, vec2: list) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(p * q for p, q in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(p * p for p in vec1))
    magnitude2 = math.sqrt(sum(q * q for q in vec2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)

def generate_candidate_pairs(embeddings_data_input: dict, similarity_threshold: float) -> list: # candidates_file_path removed
    actual_embeddings_data = {}
    if isinstance(embeddings_data_input, dict) and "files" in embeddings_data_input: # Check new structure
        actual_embeddings_data = embeddings_data_input["files"]
    elif isinstance(embeddings_data_input, dict): # Compatibility for old structure
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
    source_body_content: str, 
    target_body_content: str, 
    source_file_path: str,
    target_file_path: str, 
    api_key: str,
    # --- AI provider parameters ---
    ai_provider: str,
    ai_api_url: str,
    ai_model_name: str,
    max_content_length_for_ai_to_use: int,
    hash_boundary_marker_to_use: str
) -> dict:
    if not api_key:
        print(f"错误：{ai_provider} API Key 未配置。无法为 {source_file_path} -> {target_file_path} 打分。")
        return {"ai_score": -1, "error": "API Key not configured"}

    source_file_name = os.path.basename(source_file_path)
    target_file_name = os.path.basename(target_file_path)

    processed_source_body = extract_content_for_hashing(source_body_content)
    processed_target_body = extract_content_for_hashing(target_body_content)

    if processed_source_body is None or processed_target_body is None:
        missing_marker_info = []
        if processed_source_body is None: missing_marker_info.append(f"源笔记({source_file_path})")
        if processed_target_body is None: missing_marker_info.append(f"目标笔记({target_file_path})")
        error_msg = f"Missing HASH_BOUNDARY_MARKER ('{hash_boundary_marker_to_use}') in {', '.join(missing_marker_info)}"
        print(f"{ai_provider} API 跳过: {error_msg}")
        return {"ai_score": -1, "error": error_msg}

    source_excerpt = processed_source_body[:max_content_length_for_ai_to_use]
    target_excerpt = processed_target_body[:max_content_length_for_ai_to_use]

    # 构建请求体和头部，根据不同AI提供商调整
    request_body, headers = build_ai_request(
        ai_provider, ai_model_name, api_key, source_file_name, target_file_name,
        source_excerpt, target_excerpt, max_content_length_for_ai_to_use
    )

    print(f"  AI打分 (调用{ai_provider} API): {source_file_path} -> {target_file_path}")
    try:
        # 对于Gemini，需要在URL中添加API密钥
        if ai_provider == 'gemini':
            # 构建完整的Gemini API URL
            model_path = ai_model_name if ai_model_name else 'gemini-1.5-flash'
            full_url = f"{ai_api_url}/{model_path}:generateContent?key={api_key}"
        else:
            full_url = ai_api_url
            
        # Delay is handled by the caller (score_candidates_and_update_frontmatter)
        response = requests.post(full_url, headers=headers, json=request_body, timeout=45)
        
        if not response.ok:
            error_message = f"{ai_provider} API 失败 {source_file_path}->{target_file_path}: HTTP {response.status_code}"
            try: error_message += f" - {response.json()}"
            except json.JSONDecodeError: error_message += f" - {response.text[:200]}"
            print(error_message)
            return {"ai_score": -1, "error": f"API Error: HTTP {response.status_code}"}

        # 解析响应，根据不同AI提供商调整
        score = parse_ai_response(response, ai_provider, source_file_path, target_file_path)
        if score is not None:
            return {"ai_score": score}
        else:
            return {"ai_score": -1, "error": "Failed to parse AI response"}
            
    except requests.exceptions.Timeout:
        print(f"{ai_provider} API 超时 {source_file_path}->{target_file_path}")
        return {"ai_score": -1, "error": "API call timed out"}
    except Exception as e_unknown: # Catch broader exceptions
        print(f"{ai_provider} API 未知错误 {source_file_path}->{target_file_path}: {e_unknown}")
        return {"ai_score": -1, "error": f"Unknown API call error: {e_unknown}"}


def build_ai_request(ai_provider: str, model_name: str, api_key: str, 
                    source_file_name: str, target_file_name: str,
                    source_excerpt: str, target_excerpt: str, 
                    max_content_length: int) -> tuple[dict, dict]:
    """构建不同AI提供商的请求体和头部"""
    
    prompt = f"""你是一个 Obsidian 笔记链接评估助手。请直接比较以下【源笔记内容】和【目标笔记内容】，判断它们之间的相关性。
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
返回纯粹的JSON，不包含任何Markdown标记。"""

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
        
        if ai_provider == 'claude':
            # Claude 响应格式
            if data and data.get("content") and len(data["content"]) > 0:
                message_content_str = data["content"][0].get("text", "")
            else:
                print(f"Claude API 响应格式不符 {source_file_path}->{target_file_path}: {data}")
                return None
        elif ai_provider == 'gemini':
            # Gemini 响应格式
            if data and data.get("candidates") and len(data["candidates"]) > 0:
                content = data["candidates"][0].get("content", {})
                if content.get("parts") and len(content["parts"]) > 0:
                    message_content_str = content["parts"][0].get("text", "")
                else:
                    print(f"Gemini API 响应格式不符 {source_file_path}->{target_file_path}: {data}")
                    return None
            else:
                print(f"Gemini API 响应格式不符 {source_file_path}->{target_file_path}: {data}")
                return None
        else:
            # OpenAI 兼容格式
            if data and data.get("choices") and data["choices"][0].get("message", {}).get("content"):
                message_content_str = data["choices"][0]["message"]["content"]
            else:
                print(f"{ai_provider} API 响应格式不符 {source_file_path}->{target_file_path}: {data}")
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
    # --- AI provider parameters ---
    ai_provider: str,
    ai_api_url: str,
    ai_api_key: str,
    ai_model_name: str,
    # --- Other parameters ---
    max_content_length_for_ai_to_use: int,
    max_candidates_per_source_for_ai_scoring_to_use: int,
    hash_boundary_marker_to_use: str,
    force_rescore: bool
):
    if not ai_api_key: # This check is now primary
        print(f"错误：{ai_provider} API Key 未提供，跳过 AI 打分流程。")
        return

    updated_files_count = 0
    
    # 🔥 新增：AI打分去重逻辑
    print("正在对候选对进行去重以避免重复AI打分...")
    unique_pairs_for_ai = {}  # 存储唯一的关系对，用于AI打分
    ai_score_cache = {}       # 缓存AI评分结果
    
    # 🔥 新增：加载已有的AI评分数据
    ai_scores_file_path = os.path.join(os.path.dirname(project_root_abs), ".Jina-AI-Linker-Output", "ai_scores.json")
    if os.path.exists(os.path.join(project_root_abs, ".Jina-AI-Linker-Output")):
        ai_scores_file_path = os.path.join(project_root_abs, ".Jina-AI-Linker-Output", "ai_scores.json")
    
    existing_ai_scores = load_ai_scores_from_json(ai_scores_file_path)
    ai_score_cache.update(existing_ai_scores)  # 预填充缓存
    
    # 第一步：识别唯一的关系对（用于AI打分）
    for pair in candidate_pairs_list:
        pair_id = pair.get("pair_id")
        if pair_id and pair_id not in unique_pairs_for_ai:
            # 选择字典序较小的作为AI打分的"主"方向
            source_path = pair["source_path"]
            target_path = pair["target_path"]
            if source_path < target_path:
                unique_pairs_for_ai[pair_id] = pair
            # 如果当前pair的source > target，等待反向pair
        elif pair_id and pair_id in unique_pairs_for_ai:
            # 检查是否需要更新为字典序更小的方向
            existing_pair = unique_pairs_for_ai[pair_id]
            if pair["source_path"] < existing_pair["source_path"]:
                unique_pairs_for_ai[pair_id] = pair
    
    print(f"去重后需要AI打分的唯一关系对数量: {len(unique_pairs_for_ai)} (原始: {len(candidate_pairs_list)})")
    
    # 第二步：对唯一的关系对进行AI打分
    total_unique_pairs = len(unique_pairs_for_ai)
    processed_unique_pairs = 0
    
    for pair_id, pair in unique_pairs_for_ai.items():
        processed_unique_pairs += 1
        source_path = pair["source_path"]
        target_path = pair["target_path"]
        
        print(f"  AI打分唯一对 ({processed_unique_pairs}/{total_unique_pairs}): {source_path} <-> {target_path}")
        
        # 检查是否已经有AI评分（如果不是强制重新评分）
        if not force_rescore and pair_id in ai_score_cache:
            print(f"    AI评分已存在于缓存中 (评分: {ai_score_cache[pair_id]}/10)，跳过")
            continue
        
        # 读取文件内容进行AI打分
        source_abs_path = os.path.join(project_root_abs, source_path)
        target_abs_path = os.path.join(project_root_abs, target_path)
        
        if not os.path.exists(source_abs_path) or not os.path.exists(target_abs_path):
            print(f"    警告：文件不存在，跳过AI打分")
            continue
            
        try:
            source_body, _, _ = read_markdown_with_frontmatter(source_abs_path)
            target_body, _, _ = read_markdown_with_frontmatter(target_abs_path)
            
            clean_source_body = extract_content_for_hashing(source_body)
            clean_target_body = extract_content_for_hashing(target_body)
            
            if clean_source_body is None or clean_target_body is None:
                print(f"    警告：缺少哈希边界标记，跳过AI打分")
                continue
                
            # 执行AI打分（只调用一次API）
            time.sleep(AI_API_REQUEST_DELAY_SECONDS)
            
            ai_result = call_ai_api_for_pair_relevance(
                clean_source_body,
                clean_target_body,
                source_path,
                target_path,
                ai_api_key,
                ai_provider,
                ai_api_url,
                ai_model_name,
                max_content_length_for_ai_to_use,
                hash_boundary_marker_to_use
            )
            
            if "ai_score" in ai_result and ai_result["ai_score"] != -1:
                ai_score = ai_result["ai_score"]
                ai_score_cache[pair_id] = ai_score
                print(f"    AI评分成功: {ai_score}/10")
            else:
                print(f"    AI评分失败: {ai_result.get('error', '未知错误')}")
                
        except Exception as e:
            print(f"    AI打分异常: {e}")
    
    # 第三步：将AI评分结果写入所有相关文件的frontmatter
    print(f"\n开始将AI评分结果写入文件frontmatter...")
    candidates_by_source = {}
    for pair in candidate_pairs_list:
        source_path = pair["source_path"]
        candidates_by_source.setdefault(source_path, []).append(pair)

    total_pairs_for_ai_consideration = 0
    limited_candidates_by_source = {}
    for source_path, pairs in candidates_by_source.items():
        sorted_pairs = sorted(pairs, key=lambda p: p.get("jina_similarity", 0.0), reverse=True)
        limited_pairs = sorted_pairs[:max_candidates_per_source_for_ai_scoring_to_use] # Use param
        limited_candidates_by_source[source_path] = limited_pairs
        total_pairs_for_ai_consideration += len(limited_pairs)

    print(f"\n开始对约 {total_pairs_for_ai_consideration} 个候选链接对进行 AI 打分...")
    processed_ai_pairs_this_run = 0

    for source_rel_path, pairs_for_source in limited_candidates_by_source.items():
        source_abs_path = os.path.join(project_root_abs, source_rel_path)
        current_source_pairs_to_process = len(pairs_for_source)
        pairs_processed_for_current_source = 0

        if not os.path.exists(source_abs_path):
            print(f"  警告：源文件 {source_rel_path} 不存在，跳过其 AI 打分。")
            processed_ai_pairs_this_run += current_source_pairs_to_process
            continue

        try:
            source_body_for_fm, source_fm_dict, _ = read_markdown_with_frontmatter(source_abs_path)
            if AI_JUDGED_CANDIDATES_FM_KEY not in source_fm_dict or \
               not isinstance(source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY], list):
                source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY] = []
            
            existing_judged_targets_info = {
                item.get("targetPath"): item 
                for item in source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY] 
                if isinstance(item, dict) and "targetPath" in item
            }
            
            made_change_to_this_file = False
            src_content_body_for_ai_analysis, _, _ = read_markdown_with_frontmatter(source_abs_path) # Read full body
            clean_src_body_for_ai = extract_content_for_hashing(src_content_body_for_ai_analysis)

            if clean_src_body_for_ai is None:
                print(f"  警告：源文件 {source_rel_path} 缺少哈希边界 \'{HASH_BOUNDARY_MARKER}\'，跳过 AI 打分。")
                processed_ai_pairs_this_run += current_source_pairs_to_process
                continue
            if not clean_src_body_for_ai.strip():
                print(f"  警告：源文件 {source_rel_path} 哈希边界前内容为空，跳过 AI 打分。")
                processed_ai_pairs_this_run += current_source_pairs_to_process
                continue

            for pair_info in pairs_for_source:
                processed_ai_pairs_this_run += 1
                pairs_processed_for_current_source +=1
                target_rel_path = pair_info["target_path"]
                target_abs_path = os.path.join(project_root_abs, target_rel_path)

                print(f"  更新frontmatter ({processed_ai_pairs_this_run}/{total_pairs_for_ai_consideration} - 源内 {pairs_processed_for_current_source}/{current_source_pairs_to_process}): {source_rel_path} -> {target_rel_path}")

                # 🔥 使用缓存的AI评分结果
                pair_id = pair_info.get("pair_id")
                ai_score_value = None
                
                if pair_id and pair_id in ai_score_cache:
                    # 使用缓存的AI评分
                    ai_score_value = ai_score_cache[pair_id]
                    print(f"    使用缓存的AI评分: {ai_score_value}/10")
                elif not force_rescore and target_rel_path in existing_judged_targets_info:
                    # 使用已存在的AI评分
                    existing_entry = existing_judged_targets_info[target_rel_path]
                    if isinstance(existing_entry, dict) and "aiScore" in existing_entry:
                        ai_score_value = existing_entry["aiScore"]
                        print(f"    使用已存在的AI评分: {ai_score_value}/10")
                    else:
                        print(f"    AI打分已存在但格式无效，跳过。")
                        continue
                else:
                    print(f"    无可用的AI评分，跳过。")
                    continue

                if ai_score_value is not None:
                    new_ai_entry = {
                        "targetPath": target_rel_path,      
                        "aiScore": ai_score_value,        
                        "jinaScore": round(pair_info["jina_similarity"], 6) 
                    }
                    # Update or add, ensuring targetPath uniqueness
                    source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY] = [
                        item for item in source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY]
                        if not (isinstance(item, dict) and item.get("targetPath") == target_rel_path) 
                    ]
                    source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY].append(new_ai_entry)
                    made_change_to_this_file = True
                    print(f"    AI评分 ({ai_score_value}/10) 已更新到 {source_rel_path} frontmatter")

            if made_change_to_this_file:
                source_fm_dict[AI_JUDGED_CANDIDATES_FM_KEY].sort(
                    key=lambda x: (x.get("aiScore", -1), x.get("jinaScore", 0.0)), 
                    reverse=True
                )
                try:
                    write_markdown_with_frontmatter(source_abs_path, source_fm_dict, source_body_for_fm)
                    updated_files_count +=1
                except Exception as e_write:
                    print(f"  错误：写入 AI 打分结果到 {source_rel_path} 失败: {e_write}")
        
        except Exception as e_outer:
            print(f"  处理源文件 {source_rel_path} AI 打分时发生外部错误: {e_outer}")

    # 🔥 新增：保存AI评分到独立JSON文件
    save_ai_scores_to_json(ai_score_cache, unique_pairs_for_ai, ai_scores_file_path)
    
    print(f"\nAI 打分及 Frontmatter 更新完成。更新了 {updated_files_count} 个源文件。处理了 {processed_ai_pairs_this_run}/{total_pairs_for_ai_consideration} 对候选。")
    print(f"AI评分数据已保存到: {ai_scores_file_path}")

def save_ai_scores_to_json(ai_score_cache: dict, unique_pairs_for_ai: dict, ai_scores_file_path: str):
    """
    保存AI评分结果到独立的JSON文件
    使用智能路径策略：优先使用文件名，冲突时使用完整路径
    """
    try:
        # 加载现有的AI评分数据
        existing_ai_scores = {}
        if os.path.exists(ai_scores_file_path):
            try:
                with open(ai_scores_file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_ai_scores = existing_data.get("ai_scores", {})
            except Exception as e:
                print(f"警告：读取现有AI评分文件失败: {e}")
        
        # 使用完整路径存储，无需冲突检测
        
        def get_smart_key(path1: str, path2: str) -> str:
            """生成标准化的键名：使用完整相对路径，按字典序排序"""
            # 标准化路径分隔符
            norm_path1 = path1.replace(os.sep, '/')
            norm_path2 = path2.replace(os.sep, '/')
            
            # 按字典序排序，确保一致性
            return f"{min(norm_path1, norm_path2)}<->{max(norm_path1, norm_path2)}"
        
        # 更新AI评分数据
        updated_count = 0
        for pair_id, ai_score in ai_score_cache.items():
            if pair_id in unique_pairs_for_ai:
                pair_info = unique_pairs_for_ai[pair_id]
                source_path = pair_info["source_path"]
                target_path = pair_info["target_path"]
                
                # 生成智能键名
                smart_key = get_smart_key(source_path, target_path)
                
                # 创建评分条目
                score_entry = {
                    "ai_score": ai_score,
                    "jina_similarity": round(pair_info["jina_similarity"], 6),
                    "last_scored": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "source_path": source_path,
                    "target_path": target_path,
                    "key_type": "full_path"
                }
                
                existing_ai_scores[smart_key] = score_entry
                updated_count += 1
        
        # 构建最终数据结构
        final_data = {
            "_metadata": {
                "version": "1.0",
                "description": "AI评分数据 - 完整路径存储",
                "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "total_relationships": len(existing_ai_scores),
                "storage_strategy": "full_path"
            },
            "ai_scores": existing_ai_scores
        }
        
        # 保存到文件
        os.makedirs(os.path.dirname(ai_scores_file_path), exist_ok=True)
        with open(ai_scores_file_path, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ AI评分数据已保存: {updated_count} 个关系 (使用完整路径存储)")
            
    except Exception as e:
        print(f"❌ 保存AI评分数据失败: {e}")

def load_ai_scores_from_json(ai_scores_file_path: str) -> dict:
    """
    从JSON文件加载AI评分数据
    返回 {pair_id: ai_score} 格式的字典
    """
    ai_scores = {}
    if not os.path.exists(ai_scores_file_path):
        return ai_scores
    
    try:
        with open(ai_scores_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            stored_scores = data.get("ai_scores", {})
            
            for key, entry in stored_scores.items():
                if isinstance(entry, dict) and "ai_score" in entry:
                    # 将存储的键转换回pair_id格式
                    source_path = entry.get("source_path", "")
                    target_path = entry.get("target_path", "")
                    
                    if source_path and target_path:
                        # 生成标准的pair_id
                        pair_id = f"{min(source_path, target_path)}<->{max(source_path, target_path)}"
                        ai_scores[pair_id] = entry["ai_score"]
        
        print(f"📖 从AI评分文件加载了 {len(ai_scores)} 个评分记录")
        
    except Exception as e:
        print(f"⚠️ 加载AI评分文件失败: {e}")
    
    return ai_scores

def build_file_index(vault_root_abs: str, excluded_folders: list = None, excluded_files_patterns: list = None) -> dict[str, str]:
    """
    Recursively scans the vault and creates a map of
    filename -> new relative path (using forward slashes).
    """
    print(f"[INFO] Building file index for vault at: {vault_root_abs}...")
    index = {}
    
    all_md_files = list_markdown_files(vault_root_abs, vault_root_abs, excluded_folders, excluded_files_patterns)
    
    for file_rel_path in all_md_files:
        file_name = os.path.basename(file_rel_path)
        index[file_name] = file_rel_path
    print(f"[INFO] Index created with {len(index)} files.")
    return index

def update_target_paths_in_frontmatter_for_single_file(
    file_abs_path: str, 
    file_index: dict, 
    unfound_targets: set
) -> bool:
    """
    Reads a file, updates the targetPath in its YAML, and writes it back.
    Returns True if the file was modified, False otherwise.
    """
    try:
        original_body_content, yaml_data, _ = read_markdown_with_frontmatter(file_abs_path)
    except Exception as e:
        print(f"[ERROR] Could not read file {file_abs_path}: {e}")
        return False

    if not yaml_data or AI_JUDGED_CANDIDATES_FM_KEY not in yaml_data:
        return False # No relevant YAML to update

    was_modified = False
    candidates = yaml_data.get(AI_JUDGED_CANDIDATES_FM_KEY, [])
    if not isinstance(candidates, list):
        return False # Skip if the structure is not a list as expected

    for candidate in candidates:
        if isinstance(candidate, dict) and 'targetPath' in candidate:
            old_path_str = candidate['targetPath']
            target_filename = os.path.basename(old_path_str)
            
            # Look up the new path in our index
            if target_filename in file_index:
                new_path = file_index[target_filename]
                if old_path_str != new_path:
                    candidate['targetPath'] = new_path
                    was_modified = True
            else:
                # If not found in the index, log it for the final report
                unfound_targets.add(target_filename)
    
    if was_modified:
        try:
            # Use the existing write_markdown_with_frontmatter
            write_markdown_with_frontmatter(file_abs_path, yaml_data, original_body_content)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to write updated YAML to {file_abs_path}: {e}")
            return False
            
    return False

def update_all_target_paths_in_vault(
    project_root_abs: str,
    excluded_folders: list = None,
    excluded_files_patterns: list = None
):
    """
    Orchestrates the process of updating target paths in YAML frontmatter across the vault.
    """
    print(f"\n===== 启动 YAML 路径更新 =====")
    print(f"- 项目根路径: {project_root_abs}")

    # 1. Build the index of all files and their new relative paths
    file_index = build_file_index(project_root_abs, excluded_folders, excluded_files_patterns)

    # 2. Iterate through all files and update them
    updated_file_count = 0
    unfound_targets = set()
    
    all_md_files_relative = list_markdown_files(project_root_abs, project_root_abs, excluded_folders, excluded_files_patterns)
    total_files = len(all_md_files_relative)
    
    print(f"\n[INFO] Starting to process {total_files} files for path updates...")

    for i, file_rel_path in enumerate(all_md_files_relative):
        file_abs_path = os.path.join(project_root_abs, file_rel_path)
        print(f"  -> Processing ({i+1}/{total_files}): {file_rel_path}", end='\r')
        if update_target_paths_in_frontmatter_for_single_file(file_abs_path, file_index, unfound_targets):
            updated_file_count += 1
    
    print("\n" + "="*50)
    print("        路径更新报告")
    print("="*50)
    print(f"总文件数: {total_files}")
    print(f"YAML 路径已更新的文件数: {updated_file_count}")
    print("-" * 50)
    
    if unfound_targets:
        print(f"在 YAML 中引用但未在仓库中找到的目标文件 ({len(unfound_targets)}):")
        for filename in sorted(list(unfound_targets)):
            print(f"  - {filename}")
    else:
        print("所有引用的目标路径均已成功找到并更新。")

    print("\n[INFO] 路径更新脚本完成。")


# --- Default constants for argparse ---
DEFAULT_EMBEDDINGS_FILE_NAME = "jina_embeddings.json"
DEFAULT_CANDIDATES_FILE_NAME = "jina_candidate_pairs.json"
DEFAULT_SIMILARITY_THRESHOLD = 0.70

def main():
    parser = argparse.ArgumentParser(description="Jina AI 处理工具 - 处理笔记内容并提取嵌入。")
    parser.add_argument('--project_root', type=str, required=True, help='项目根目录的绝对路径')
    parser.add_argument('--output_dir', type=str, default='.Jina-AI-Linker-Output', help='输出文件的目录路径（相对于项目根目录）')
    parser.add_argument('--jina_api_key', type=str, default='', help='Jina API 密钥') # Made optional for path update mode
    # AI 提供商参数
    parser.add_argument('--ai_provider', type=str, default='', help='AI 提供商 (deepseek, openai, claude, gemini, custom)')
    parser.add_argument('--ai_api_url', type=str, default='', help='AI API URL')
    parser.add_argument('--ai_api_key', type=str, default='', help='AI API 密钥（用于 AI 打分，如不提供则跳过 AI 打分）')
    parser.add_argument('--ai_model_name', type=str, default='', help='AI 模型名称')
    
    # 其他参数
    parser.add_argument('--similarity_threshold', type=float, default=0.7, help='相似度阈值（0-1之间）')
    parser.add_argument('--scan_target_folders', nargs='*', default=[], help='要扫描的文件夹（逗号分隔，相对于项目根目录）')
    parser.add_argument('--excluded_folders', nargs='*', default=[], help='要排除的文件夹列表')
    parser.add_argument('--excluded_files_patterns', nargs='*', default=[], help='要排除的文件名模式列表')
    parser.add_argument('--jina_model_name', type=str, default='jina-embeddings-v3', help='Jina 模型名称')
    parser.add_argument('--max_chars_for_jina', type=int, default=8000, help='传递给 Jina 的最大字符数')
    parser.add_argument('--max_content_length_for_ai', type=int, default=5000, help='传递给 AI 评分的每篇笔记的最大内容长度（字符）')
    parser.add_argument('--max_candidates_per_source_for_ai_scoring', type=int, default=20, help='每个源笔记发送给 AI 评分的最大候选链接数')
    parser.add_argument('--ai_scoring_mode', type=str, choices=['force', 'smart', 'skip'], default='smart', help='AI 评分模式：force=强制重新评分所有候选，smart=只评分未评分的，skip=跳过 AI 评分')
    parser.add_argument('--hash_boundary_marker', type=str, default='<!-- HASH_BOUNDARY -->', help='用于标记哈希计算边界的标记')
    parser.add_argument('--update_paths_only', action='store_true', help='只执行 YAML 路径更新功能，不执行其他处理。') # New argument
    
    args = parser.parse_args()
    
    start_time = time.time()

    project_root_abs = os.path.abspath(args.project_root)
    output_dir_in_vault = args.output_dir
    output_dir_abs = os.path.join(project_root_abs, output_dir_in_vault)
    
    # 确保输出目录存在
    os.makedirs(output_dir_abs, exist_ok=True)
    
    # If only updating paths, execute that function and exit
    if args.update_paths_only:
        update_all_target_paths_in_vault(
            project_root_abs,
            excluded_folders=args.excluded_folders,
            excluded_files_patterns=args.excluded_files_patterns
        )
        end_time = time.time()
        print(f"\n总耗时: {end_time - start_time:.2f} 秒")
        return

    # Default processing flow continues below if not update_paths_only
    
    # 默认的嵌入和候选文件路径
    embeddings_file_path = os.path.join(output_dir_abs, "jina_embeddings.json")
    
    # 处理扫描目标文件夹参数
    if not args.scan_target_folders or (len(args.scan_target_folders) == 1 and args.scan_target_folders[0] == '/'):
        scan_target_folder_abs = project_root_abs
        scan_target_folder_rel = "/"
    else:
        scan_targets = args.scan_target_folders
        if len(scan_targets) == 1:
            scan_target_folder_rel = scan_targets[0]
            scan_target_folder_abs = os.path.join(project_root_abs, scan_target_folder_rel)
            scan_target_folder_rel = scan_target_folder_rel.replace(os.sep, '/')
        else:
            # 当存在多个扫描目标时，先扫描整个库，后面会过滤只处理指定文件夹中的文件
            scan_target_folder_abs = project_root_abs
            scan_target_folder_rel = "multiple folders"
    
    print(f"===== Jina处理启动 =====")
    print(f"- 项目根路径: {project_root_abs}")
    print(f"- 扫描目标: {scan_target_folder_rel}")
    print(f"- 输出目录: {output_dir_in_vault}")
    print(f"- Jina模型: {args.jina_model_name}")
    print(f"- 最大Jina字符数: {args.max_chars_for_jina}")
    print(f"- 相似度阈值: {args.similarity_threshold}")
    if args.max_candidates_per_source_for_ai_scoring > 0:
        print(f"- 每源笔记的最大AI评分候选数: {args.max_candidates_per_source_for_ai_scoring}")
    if args.ai_api_key:
        print(f"- AI评分模式: {args.ai_scoring_mode}")
        print(f"- AI提供商: {args.ai_provider}")
        print(f"- AI模型: {args.ai_model_name}")
        print(f"- AI评分内容最大长度: {args.max_content_length_for_ai}")
    else:
        print("- AI评分: 未提供 AI API 密钥，跳过 AI 评分")
    
    # 扫描并列出符合条件的 markdown 文件
    print(f"\n步骤 1：扫描 Markdown 文件...")
    if scan_target_folder_rel == "multiple folders":
        # 如果指定了多个扫描文件夹，先扫描全部
        all_markdown_files = list_markdown_files(
            project_root_abs, 
            project_root_abs,
            excluded_folders=args.excluded_folders,
            excluded_files_patterns=args.excluded_files_patterns
        )
        # 然后只保留指定文件夹下的文件
        target_folders = [folder.replace(os.sep, '/') for folder in args.scan_target_folders]
        filtered_markdown_files = []
        for file_path in all_markdown_files:
            file_path_norm = normalize_path_python(file_path)
            for target_folder in target_folders:
                target_folder_norm = normalize_path_python(target_folder)
                if target_folder_norm == "/":  # 根目录特殊处理
                    if "/" not in file_path_norm:
                        filtered_markdown_files.append(file_path)
                        break
                elif file_path_norm == target_folder_norm or file_path_norm.startswith(target_folder_norm + "/"):
                    filtered_markdown_files.append(file_path)
                    break
        markdown_files_to_process = filtered_markdown_files
    else:
        # 正常处理单个目标文件夹的情况
        markdown_files_to_process = list_markdown_files(
            scan_target_folder_abs, 
            project_root_abs,
            excluded_folders=args.excluded_folders,
            excluded_files_patterns=args.excluded_files_patterns
        )

    if not markdown_files_to_process:
        print("  没有找到符合条件的 Markdown 文件！")
        return
    
    print(f"  找到 {len(markdown_files_to_process)} 个 Markdown 文件。")
    
    # 步骤2：使用 Jina AI 处理笔记并生成嵌入
    print(f"\n步骤 2：处理笔记并生成嵌入...")
    embeddings_data = process_and_embed_notes(
        project_root_abs,
        markdown_files_to_process,
        embeddings_file_path,
        jina_api_key_to_use=args.jina_api_key,
        jina_model_name_to_use=args.jina_model_name,
        max_chars_for_jina_to_use=args.max_chars_for_jina
    )
    
    if not embeddings_data or not embeddings_data.get('files'):
        print("  错误：没有成功处理任何文件或生成嵌入。")
        return
    
    # 步骤3：生成候选链接对
    print(f"\n步骤 3：根据相似度阈值 {args.similarity_threshold} 生成候选链接对...")
    candidate_pairs = generate_candidate_pairs(embeddings_data, args.similarity_threshold)
    
    print(f"  共生成 {len(candidate_pairs)} 个候选链接对。")
    if len(candidate_pairs) == 0:
        print("  没有找到符合相似度阈值的候选链接对。")
    
    # 步骤 4: AI 对候选链接进行智能打分评分
    if (args.ai_api_key and args.ai_scoring_mode != 'skip' and 
        args.max_candidates_per_source_for_ai_scoring > 0 and len(candidate_pairs) > 0):
        
        print(f"\n步骤 4：使用 {args.ai_provider} AI 对候选链接进行智能评分...")
        
        force_rescore = args.ai_scoring_mode == 'force'
        score_candidates_and_update_frontmatter(
            candidate_pairs,
            project_root_abs,
            ai_provider=args.ai_provider,
            ai_api_url=args.ai_api_url,
            ai_api_key=args.ai_api_key,
            ai_model_name=args.ai_model_name,
            max_content_length_for_ai_to_use=args.max_content_length_for_ai,
            max_candidates_per_source_for_ai_scoring_to_use=args.max_candidates_per_source_for_ai_scoring, 
            hash_boundary_marker_to_use=args.hash_boundary_marker,
            force_rescore=force_rescore
        )
    else:
        if args.ai_api_key:
            print(f"\n步骤 4：跳过 AI 评分 (评分模式: {args.ai_scoring_mode})")
        else:
            print(f"\n步骤 4：跳过 AI 评分 (未提供 {args.ai_provider or 'AI'} API 密钥)")
    
    # 打印总结信息
    end_time = time.time()
    total_files_processed = len(embeddings_data.get('files', {}))
    total_time = end_time - start_time
    
    print(f"\n===== 处理完成 =====")
    print(f"- 成功处理文件: {total_files_processed} 个")
    print(f"- 生成候选链接对: {len(candidate_pairs)} 个")
    print(f"- 总耗时: {total_time:.2f} 秒")
    print(f"- 嵌入数据保存至: {embeddings_file_path}")

if __name__ == "__main__":
    main()
