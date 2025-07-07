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