"""SQLite schema definitions for embeddings & ai_scores databases."""

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