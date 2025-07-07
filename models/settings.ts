import { AIModelConfig, AIProvider } from './interfaces';
import { DEFAULT_AI_MODELS } from './constants';

export interface JinaLinkerSettings {
    pythonPath: string;
    jinaApiKey: string;
    aiModels: {
        deepseek: AIModelConfig;
        openai: AIModelConfig;
        claude: AIModelConfig;
        gemini: AIModelConfig;
        custom: AIModelConfig;
    };
    selectedAIProvider: AIProvider;
    similarityThreshold: number;
    excludedFolders: string;
    excludedFilesPatterns: string;
    defaultScanPath: string;
    jinaModelName: string;
    maxCharsForJina: number;
    maxContentLengthForAI: number;
    maxCandidatesPerSourceForAIScoring: number;
    minAiScoreForLinkInsertion: number;
    maxLinksToInsertPerNote: number;
    dataMigrationCompleted: boolean;
}

export const DEFAULT_SETTINGS: JinaLinkerSettings = {
    pythonPath: 'bin/jina-linker.exe',
    jinaApiKey: '',
    aiModels: { ...DEFAULT_AI_MODELS },
    selectedAIProvider: 'deepseek',
    similarityThreshold: 0.70,
    excludedFolders: '.obsidian, Scripts, assets, Excalidraw, .trash, Python-Templater-Plugin-Output',
    excludedFilesPatterns: '*excalidraw*, template*.md, *.kanban.md, ^moc$, ^index$',
    defaultScanPath: '/',
    jinaModelName: 'jina-embeddings-v3',
    maxCharsForJina: 8000,
    maxContentLengthForAI: 5000,
    maxCandidatesPerSourceForAIScoring: 20,
    minAiScoreForLinkInsertion: 6,
    maxLinksToInsertPerNote: 10,
    dataMigrationCompleted: false
};