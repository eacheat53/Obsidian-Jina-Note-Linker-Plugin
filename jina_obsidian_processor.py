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

# Ensure stdout and stderr use UTF-8 encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# --- 嵌入处理配置常量 (只保留脚本内部固定或真正意义上的常量) ---
JINA_API_URL = "https://api.jina.ai/v1/embeddings" 
JINA_API_REQUEST_DELAY = 0.1 # Jina API 请求之间的延迟时间（秒）
# DEFAULT_EMBEDDINGS_FILE_NAME, DEFAULT_CANDIDATES_FILE_NAME etc. are used as argparse defaults below

# --- DeepSeek AI 打分相关配置 (只保留脚本内部固定或真正意义上的常量) ---
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_REQUEST_DELAY_SECONDS = 1.0 # DeepSeek API 调用之间的默认延迟时间（秒）
# Other DeepSeek related defaults are in argparse

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
                candidate_pairs.append({"source_path": path1, "target_path": path2, "jina_similarity": similarity})
                candidate_pairs.append({"source_path": path2, "target_path": path1, "jina_similarity": similarity})
    
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

def call_deepseek_api_for_pair_relevance(
    source_body_content: str, 
    target_body_content: str, 
    source_file_path: str,
    target_file_path: str, 
    api_key: str, # DeepSeek API Key directly
    # --- Added parameters ---
    deepseek_model_name_to_use: str,
    max_content_length_for_ai_to_use: int,
    hash_boundary_marker_to_use: str
) -> dict:
    if not api_key:
        print(f"错误：DeepSeek API Key 未配置。无法为 {source_file_path} -> {target_file_path} 打分。")
        return {"ai_score": -1, "error": "API Key not configured"}

    source_file_name = os.path.basename(source_file_path)
    target_file_name = os.path.basename(target_file_path)

    processed_source_body = extract_content_for_hashing(source_body_content)
    processed_target_body = extract_content_for_hashing(target_body_content)

    if processed_source_body is None or processed_target_body is None:
        missing_marker_info = []
        if processed_source_body is None: missing_marker_info.append(f"源笔记({source_file_path})")
        if processed_target_body is None: missing_marker_info.append(f"目标笔记({target_file_path})")
        error_msg = f"Missing HASH_BOUNDARY_MARKER ('{HASH_BOUNDARY_MARKER}') in {', '.join(missing_marker_info)}"
        print(f"DeepSeek API 跳过: {error_msg}")
        return {"ai_score": -1, "error": error_msg}

    source_excerpt = processed_source_body[:max_content_length_for_ai_to_use]
    target_excerpt = processed_target_body[:max_content_length_for_ai_to_use]

    prompt = f"""
你是一个 Obsidian 笔记链接评估助手。请直接比较以下【源笔记内容】和【目标笔记内容】，判断它们之间的相关性。
你的任务是评估从源笔记指向目标笔记建立一个链接是否合适。
请给出 0-10 之间的整数评分，其中 10 表示极其相关，7-9 表示比较相关，6 表示你认为合格的相关性，1-5 表示弱相关，0 表示不相关或无法判断。

源笔记文件名: {source_file_name}
目标笔记文件名: {target_file_name}

【源笔记内容】(最多 {max_content_length_for_ai_to_use} 字符):
---
{source_excerpt}
---

【目标笔记内容】(最多 {max_content_length_for_ai_to_use} 字符):
---
{target_excerpt}
---

请严格按照以下 JSON 格式返回你的评分: {{"relevance_score": <你的评分>}}
例如: {{"relevance_score": 8}}
返回纯粹的JSON，不包含任何Markdown标记。
"""
    request_body = {
        "model": deepseek_model_name_to_use, # Use passed model name
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "stream": False
    }
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

    print(f"  AI打分 (调用API): {source_file_path} -> {target_file_path}")
    try:
        # Delay is handled by the caller (score_candidates_and_update_frontmatter)
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=request_body, timeout=45)
        
        if not response.ok:
            error_message = f"DeepSeek API 失败 {source_file_path}->{target_file_path}: HTTP {response.status_code}"
            try: error_message += f" - {response.json()}"
            except json.JSONDecodeError: error_message += f" - {response.text[:200]}"
            print(error_message)
            return {"ai_score": -1, "error": f"API Error: HTTP {response.status_code}"}

        data = response.json()
        if data and data.get("choices") and data["choices"][0].get("message", {}).get("content"):
            message_content_str = data["choices"][0]["message"]["content"]
            try:
                cleaned_json_str = re.sub(r'^```json\s*|\s*```$', '', message_content_str.strip(), flags=re.DOTALL)
                parsed_json = json.loads(cleaned_json_str)
                if isinstance(parsed_json.get("relevance_score"), (int, float)):
                    score = max(0, min(10, round(float(parsed_json["relevance_score"]))))
                    return {"ai_score": score}
                else:
                    print(f"DeepSeek API JSON 结构不完整 {source_file_path}->{target_file_path}: {parsed_json}")
                    return {"ai_score": -1, "error": "AI incomplete JSON score"}
            except json.JSONDecodeError as e_json:
                print(f"DeepSeek API 响应非JSON {source_file_path}->{target_file_path}: '{message_content_str}', Error: {e_json}")
                return {"ai_score": -1, "error": f"AI response not valid JSON: {e_json}"}
        else:
             print(f"DeepSeek API 响应格式不符 {source_file_path}->{target_file_path}: {data}")
             return {"ai_score": -1, "error": "AI response format unexpected"}
    except requests.exceptions.Timeout:
        print(f"DeepSeek API 超时 {source_file_path}->{target_file_path}")
        return {"ai_score": -1, "error": "API call timed out"}
    except Exception as e_unknown: # Catch broader exceptions
        print(f"DeepSeek API 未知错误 {source_file_path}->{target_file_path}: {e_unknown}")
        return {"ai_score": -1, "error": f"Unknown API call error: {e_unknown}"}


def normalize_path_python(path_str: str) -> str:
    if not path_str: return ""
    return path_str.replace(os.sep, '/')

def score_candidates_and_update_frontmatter(
    candidate_pairs_list: list,
    project_root_abs: str,
    deepseek_api_key_to_use: str, # Passed from main
    # --- Added parameters from args ---
    deepseek_model_name_to_use: str,
    max_content_length_for_ai_to_use: int,
    max_candidates_per_source_for_ai_scoring_to_use: int,
    hash_boundary_marker_to_use: str,
    # --- Modified parameter ---
    force_rescore: bool # This is now directly controlled by ai_scoring_mode logic in main
):
    if not deepseek_api_key_to_use: # This check is now primary
        print("错误：DeepSeek API Key 未提供，跳过 AI 打分流程。")
        return

    updated_files_count = 0
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

                print(f"  AI打分 ({processed_ai_pairs_this_run}/{total_pairs_for_ai_consideration} - 源内 {pairs_processed_for_current_source}/{current_source_pairs_to_process}): {source_rel_path} -> {target_rel_path}")

                if not force_rescore and target_rel_path in existing_judged_targets_info:
                    print(f"    AI打分已存在且未强制刷新，跳过。")
                    continue

                if not os.path.exists(target_abs_path):
                    print(f"    警告：目标文件 {target_rel_path} 不存在，跳过。")
                    continue

                tgt_content_body, _, _ = read_markdown_with_frontmatter(target_abs_path)
                clean_tgt_body = extract_content_for_hashing(tgt_content_body)

                if clean_tgt_body is None:
                    print(f"    警告：目标文件 {target_rel_path} 缺少哈希边界 \'{HASH_BOUNDARY_MARKER}\'，跳过。")
                    continue
                if not clean_tgt_body.strip():
                    print(f"    警告：目标文件 {target_rel_path} 哈希边界前内容为空，跳过。")
                    continue
                
                # API Call Delay before each call
                time.sleep(DEEPSEEK_API_REQUEST_DELAY_SECONDS) # Use internal constant
                
                ai_result = call_deepseek_api_for_pair_relevance(
                    clean_src_body_for_ai, 
                    clean_tgt_body,
                    source_rel_path, 
                    target_rel_path,
                    deepseek_api_key_to_use, # Pass API key
                    deepseek_model_name_to_use,
                    max_content_length_for_ai_to_use,
                    hash_boundary_marker_to_use
                )

                if "ai_score" in ai_result and ai_result["ai_score"] != -1:
                    ai_score_value = ai_result["ai_score"]
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
                    print(f"    AI评分 ({ai_score_value}/10) 已记录到 {source_rel_path} (目标: {target_rel_path})")
                else:
                    print(f"    AI打分失败或无效 (源: {source_rel_path}, 目标: {target_rel_path})。错误: {ai_result.get('error', '未知')}")

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

    print(f"\nAI 打分及 Frontmatter 更新完成。更新了 {updated_files_count} 个源文件。处理了 {processed_ai_pairs_this_run}/{total_pairs_for_ai_consideration} 对候选。")


# --- Default constants for argparse ---
DEFAULT_EMBEDDINGS_FILE_NAME = "jina_embeddings.json"
DEFAULT_CANDIDATES_FILE_NAME = "jina_candidate_pairs.json"
DEFAULT_SIMILARITY_THRESHOLD = 0.70

def main():
    parser = argparse.ArgumentParser(description="Jina AI 处理工具 - 处理笔记内容并提取嵌入。")
    parser.add_argument('--project_root', type=str, required=True, help='项目根目录的绝对路径')
    parser.add_argument('--output_dir', type=str, default='.Jina-AI-Linker-Output', help='输出文件的目录路径（相对于项目根目录）')
    parser.add_argument('--jina_api_key', type=str, required=True, help='Jina API 密钥')
    parser.add_argument('--deepseek_api_key', type=str, default='', help='DeepSeek API 密钥（用于 AI 打分，如不提供则跳过 AI 打分）')
    parser.add_argument('--similarity_threshold', type=float, default=0.7, help='相似度阈值（0-1之间）')
    parser.add_argument('--scan_target_folders', nargs='*', default=[], help='要扫描的文件夹（逗号分隔，相对于项目根目录）')
    parser.add_argument('--excluded_folders', nargs='*', default=[], help='要排除的文件夹列表')
    parser.add_argument('--excluded_files_patterns', nargs='*', default=[], help='要排除的文件名模式列表')
    parser.add_argument('--jina_model_name', type=str, default='jina-embeddings-v3', help='Jina 模型名称')
    parser.add_argument('--max_chars_for_jina', type=int, default=8000, help='传递给 Jina 的最大字符数')
    parser.add_argument('--deepseek_model_name', type=str, default='deepseek-chat', help='DeepSeek 模型名称')
    parser.add_argument('--max_content_length_for_ai', type=int, default=5000, help='传递给 AI 评分的每篇笔记的最大内容长度（字符）')
    parser.add_argument('--max_candidates_per_source_for_ai_scoring', type=int, default=20, help='每个源笔记发送给 AI 评分的最大候选链接数')
    parser.add_argument('--ai_scoring_mode', type=str, choices=['force', 'smart', 'skip'], default='smart', help='AI 评分模式：force=强制重新评分所有候选，smart=只评分未评分的，skip=跳过 AI 评分')
    parser.add_argument('--hash_boundary_marker', type=str, default='<!-- HASH_BOUNDARY -->', help='用于标记哈希计算边界的标记')
    
    args = parser.parse_args()
    
    start_time = time.time()

    project_root_abs = os.path.abspath(args.project_root)
    output_dir_in_vault = args.output_dir
    output_dir_abs = os.path.join(project_root_abs, output_dir_in_vault)
    
    # 确保输出目录存在
    os.makedirs(output_dir_abs, exist_ok=True)
    
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
    if args.deepseek_api_key:
        print(f"- AI评分模式: {args.ai_scoring_mode}")
        print(f"- DeepSeek模型: {args.deepseek_model_name}")
        print(f"- AI评分内容最大长度: {args.max_content_length_for_ai}")
    else:
        print("- AI评分: 未提供 DeepSeek API 密钥，跳过 AI 评分")
    
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
    if (args.deepseek_api_key and args.ai_scoring_mode != 'skip' and 
        args.max_candidates_per_source_for_ai_scoring > 0 and len(candidate_pairs) > 0):
        
        print(f"\n步骤 4：使用 DeepSeek AI 对候选链接进行智能评分...")
        
        force_rescore = args.ai_scoring_mode == 'force'
        score_candidates_and_update_frontmatter(
            candidate_pairs,
            project_root_abs,
            deepseek_api_key_to_use=args.deepseek_api_key, 
            deepseek_model_name_to_use=args.deepseek_model_name,
            max_content_length_for_ai_to_use=args.max_content_length_for_ai,
            max_candidates_per_source_for_ai_scoring_to_use=args.max_candidates_per_source_for_ai_scoring, 
            hash_boundary_marker_to_use=args.hash_boundary_marker,
            force_rescore=force_rescore
        )
    else:
        if args.deepseek_api_key:
            print(f"\n步骤 4：跳过 AI 评分 (评分模式: {args.ai_scoring_mode})")
        else:
            print(f"\n步骤 4：跳过 AI 评分 (未提供 DeepSeek API 密钥)")
    
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
