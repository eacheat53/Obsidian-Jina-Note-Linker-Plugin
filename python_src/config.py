"""Centralised configuration constants for the Jina-Linker Python toolkit.

这些常量此前散落在 monolith `main.py` 中，现统一搬迁至此文件，供各模块引用。"""
from __future__ import annotations

# ---------------------------- Embedding (Jina) -----------------------------
JINA_API_URL: str = "https://api.jina.ai/v1/embeddings"
# Delay (seconds) between successive Jina API requests to respect rate-limit
JINA_API_REQUEST_DELAY: float = 0.1

# --------------------------- AI provider generic ---------------------------
# Delay inserted between individual AI provider requests (seconds)
AI_API_REQUEST_DELAY_SECONDS: float = 1.0

# ------------------------------- Batch sizes -------------------------------
EMBEDDING_BATCH_SIZE: int = 10  # number of notes per embedding batch
AI_SCORING_BATCH_SIZE: int = 5  # number of pairs per scoring batch

# --------------------------- Default file names ---------------------------
DEFAULT_EMBEDDINGS_FILE_NAME: str = "jina_embeddings.db"
DEFAULT_AI_SCORES_FILE_NAME: str = "ai_scores.db"
DEFAULT_SIMILARITY_THRESHOLD: float = 0.70

# ------------------------- Provider endpoint map --------------------------
DEFAULT_AI_CONFIGS: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_url": "https://api.deepseek.com/chat/completions",
        "model_name": "deepseek-chat",
    },
    "openai": {
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model_name": "gpt-4o-mini",
    },
    "claude": {
        "api_url": "https://api.anthropic.com/v1/messages",
        "model_name": "claude-3-haiku-20240307",
    },
    "gemini": {
        "api_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "model_name": "gemini-1.5-flash",
    },
    # Placeholder for user-supplied custom endpoint
    "custom": {
        "api_url": "",
        "model_name": "",
    },
}
