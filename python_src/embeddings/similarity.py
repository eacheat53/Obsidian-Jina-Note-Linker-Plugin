"""Embedding similarity helpers."""
from __future__ import annotations

import math
from typing import Dict, List
import numpy as np

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
    """使用 NumPy 批量计算余弦相似度，生成候选链接对。"""
    logger.info("[相似度] 开始生成候选链接对 …")

    files_data = embeddings_data_input.get("files", {})
    items = [(p, info) for p, info in files_data.items() if info.get("embedding")]
    if len(items) < 2:
        return []

    paths = [p for p, _ in items]
    vectors = np.array([info["embedding"] for _, info in items], dtype=np.float32)

    # 向量归一化
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors /= norms

    sim_matrix = vectors @ vectors.T  # (n, n)
    n = len(paths)
    candidates: List[Dict] = []

    for i in range(n):
        for j in range(i + 1, n):
            sim = float(sim_matrix[i, j])
            if sim >= similarity_threshold:
                candidates.append(
                    {
                        "source_path": paths[i],
                        "target_path": paths[j],
                        "jina_similarity": sim,
                        "source_hash": files_data[paths[i]].get("hash"),
                        "target_hash": files_data[paths[j]].get("hash"),
                    }
                )

    candidates.sort(key=lambda x: x["jina_similarity"], reverse=True)
    logger.info("[相似度] 生成完成，共 %s 条候选对。", len(candidates))
    return candidates


__all__ = [
    "cosine_similarity",
    "generate_candidate_pairs",
]
