EMBEDDINGS_DB_SCHEMA = """
CREATE TABLE metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE file_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT UNIQUE NOT NULL,   -- 相对路径 (含 .md)
    content_hash TEXT NOT NULL,          -- 正文 SHA
    embedding    BLOB                    -- JSON 数组或向量字节
);
CREATE INDEX idx_file_path ON file_embeddings(file_path);
CREATE INDEX idx_content_hash ON file_embeddings(content_hash);
INSERT INTO metadata (key, value) VALUES 
    ('schema_version', '2.0'),
    ('database_type', 'embeddings');
"""

AI_SCORES_DB_SCHEMA = """
CREATE TABLE metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE ai_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    source_hash TEXT,
    target_hash TEXT,
    ai_score    INTEGER,
    UNIQUE(source_path, target_path, source_hash, target_hash)
);
INSERT INTO metadata (key, value) VALUES 
    ('schema_version', '2.0'),
    ('database_type', 'ai_scores');
"""

MAIN_DB_SCHEMA = """
-- 元数据表
CREATE TABLE IF NOT EXISTS metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
);

-- Notes 表: 用于保存笔记元数据与向量
CREATE TABLE IF NOT EXISTS notes (
    note_id      TEXT PRIMARY KEY,
    file_name    TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding    BLOB -- JSON 数组
);
CREATE INDEX IF NOT EXISTS idx_notes_file_name ON notes(file_name);
CREATE INDEX IF NOT EXISTS idx_notes_content_hash ON notes(content_hash);

-- Scores 表: 保存笔记对的 AI 相关度分数
CREATE TABLE IF NOT EXISTS scores (
    pair_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id_a      TEXT NOT NULL,
    file_name_a    TEXT NOT NULL,
    note_id_b      TEXT NOT NULL,
    file_name_b    TEXT NOT NULL,
    ai_score       REAL,
    UNIQUE(note_id_a, note_id_b)
);
CREATE INDEX IF NOT EXISTS idx_scores_note_pair ON scores(note_id_a, note_id_b);

-- 可选: 保存批量 AI 请求 / 响应，便于调试
CREATE TABLE IF NOT EXISTS ai_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT NOT NULL,
    ai_provider   TEXT NOT NULL,
    model_name    TEXT NOT NULL,
    request_content  TEXT,
    response_content TEXT,
    prompt_type      TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_responses_batch ON ai_responses(batch_id);

-- Note Tags 表: 用于保存笔记的标签和置信度
CREATE TABLE IF NOT EXISTS note_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id   TEXT NOT NULL,
    tag       TEXT NOT NULL,
    confidence REAL,
    UNIQUE(note_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_note_tags_note ON note_tags(note_id);

INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '3.0');
"""