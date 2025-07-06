// models/constants.ts

import { AIProvider, AIModelConfig } from './interfaces';

// 哈希边界标记
export const HASH_BOUNDARY_MARKER = '<!-- HASH_BOUNDARY -->';

// 用于链接插入部分的常量
export const SUGGESTED_LINKS_TITLE = '## 建议链接';
export const LINKS_START_MARKER = '<!-- LINKS_START -->';
export const LINKS_END_MARKER = '<!-- LINKS_END -->';

// 默认输出目录和嵌入文件名称
export const DEFAULT_OUTPUT_DIR_IN_VAULT = '.jina-linker';
export const EMBEDDINGS_FILE_NAME = 'embeddings.json';

// 默认AI模型配置
export const DEFAULT_AI_MODELS: Record<AIProvider, AIModelConfig> = {
    deepseek: {
        provider: 'deepseek',
        apiUrl: 'https://api.deepseek.com/chat/completions',
        apiKey: '',
        modelName: 'deepseek-chat',
        enabled: true
    },
    openai: {
        provider: 'openai',
        apiUrl: 'https://api.openai.com/v1/chat/completions',
        apiKey: '',
        modelName: 'gpt-4o-mini',
        enabled: false
    },
    claude: {
        provider: 'claude',
        apiUrl: 'https://api.anthropic.com/v1/messages',
        apiKey: '',
        modelName: 'claude-3-haiku-20240307',
        enabled: false
    },
    gemini: {
        provider: 'gemini',
        apiUrl: 'https://generativelanguage.googleapis.com/v1beta/models',
        apiKey: '',
        modelName: 'gemini-1.5-flash',
        enabled: false
    },
    custom: {
        provider: 'custom',
        apiUrl: '',
        apiKey: '',
        modelName: '',
        enabled: false
    }
};