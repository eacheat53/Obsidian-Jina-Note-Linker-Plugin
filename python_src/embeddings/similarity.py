"""Embedding similarity helpers."""
from __future__ import annotations

import math
from typing import Dict, List

from python_src.utils.logger import get_logger

logger = get_logger(__name__)


# --------------------------- 基础相似度计算 ---------------------------

def cosine_similarity(vec1: List[float] | None, vec2: List[float] | None) -> float:
    """计算两个向量的余弦相似度。向量维度不一致或为空时返回 0.0。"""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


# ----------------------- 根据相似度生成候选对 -----------------------

def generate_candidate_pairs(embeddings_data_input: Dict, similarity_threshold: float) -> List[Dict]:
    """基于向量相似度生成候选链接对 (降序)。"""
    logger.info("开始生成候选链接对 …")
    files_data = embeddings_data_input.get("files", {})

    valid_paths = [p for p, info in files_data.items() if info.get("embedding")]
    total = len(valid_paths) * (len(valid_paths) - 1) // 2
    if not total:
        return []

    logger.info("共有 %s 个文件待比较，总计 %s 次比较。", len(valid_paths), total)

    candidates: List[Dict] = []
    completed = 0
    progress_step = max(1, total // 20)
    next_mark = progress_step

    for i, p1 in enumerate(valid_paths):
        emb1 = files_data[p1]["embedding"]
        for j, p2 in enumerate(valid_paths[i + 1 :], start=i + 1):
            emb2 = files_data[p2]["embedding"]
            completed += 1
            if completed >= next_mark:
                logger.info("进度 %.1f%% - 正在比较 %s <-> %s", completed / total * 100, p1, p2)
                next_mark += progress_step

            sim = cosine_similarity(emb1, emb2)
            if sim >= similarity_threshold:
                candidates.append(
                    {
                        "source_path": p1,
                        "target_path": p2,
                        "jina_similarity": sim,
                    }
                )

    candidates.sort(key=lambda x: x["jina_similarity"], reverse=True)
    logger.info("候选链接对生成完成，共 %s 条。", len(candidates))
    return candidates


__all__ = [
    "cosine_similarity",
    "generate_candidate_pairs",
]
