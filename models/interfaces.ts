// 定义插件中使用的所有接口类型
export interface RunOptions {
    scanPath: string;
    scoringMode: "force" | "smart" | "skip";
}

export interface EmbeddingData {
    files: Record<string, FileEmbedding>;
    metadata?: EmbeddingMetadata;
}

export interface FileEmbedding {
    hash: string;
    embedding?: number[];
    last_updated?: string;
    last_hash_updated_at?: string;
}

export interface EmbeddingMetadata {
    version?: string;
    last_updated?: string;
    total_files?: number;
}

export interface ProcessingError {
    type: 'PYTHON_NOT_FOUND' | 'API_KEY_INVALID' | 'FILE_NOT_FOUND' | 'PERMISSION_DENIED' | 'UNKNOWN';
    message: string;
    details?: string;
    suggestions?: string[];
}

export interface OperationResult<T = any> {
    success: boolean;
    data?: T;
    error?: ProcessingError;
}

export type AIProvider = 'deepseek' | 'openai' | 'claude' | 'gemini' | 'custom';

export interface AIModelConfig {
    provider: AIProvider;
    apiUrl: string;
    apiKey: string;
    modelName: string;
    enabled: boolean;
}