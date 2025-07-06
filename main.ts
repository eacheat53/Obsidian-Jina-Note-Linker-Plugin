import { App, Notice, Plugin, PluginSettingTab, Setting, TFolder, Modal, Editor, MarkdownView, TFile, normalizePath, Menu, SuggestModal, FuzzySuggestModal, FuzzyMatch } from 'obsidian';
import { spawn, ChildProcess } from 'child_process';
import * as path from 'path'; // 导入 Node.js path 模块
import * as crypto from 'crypto'; // 导入 Node.js crypto 模块用于哈希计算

// --- 内部常量 ---
// 已删除：AI_JUDGED_CANDIDATES_FM_KEY 常量，因为现在完全使用JSON文件存储AI评分数据
// 新增：这两个常量用于保存原来的设置默认值，但不作为用户可配置项
const DEFAULT_SCRIPT_PATH = '';
const DEFAULT_OUTPUT_DIR_IN_VAULT = '.Jina-AI-Linker-Output';
// 新增：将哈希边界标记设为内置常量
const HASH_BOUNDARY_MARKER = '<!-- HASH_BOUNDARY -->';

// 用于链接插入部分的常量
const SUGGESTED_LINKS_TITLE = '## 建议链接';
const LINKS_START_MARKER = '<!-- LINKS_START -->';
const LINKS_END_MARKER = '<!-- LINKS_END -->';
const UPDATE_PATHS_ONLY_ARG = '--update_paths_only';


// AI 提供商类型
type AIProvider = 'deepseek' | 'openai' | 'claude' | 'gemini' | 'custom';

// AI 模型配置接口
interface AIModelConfig {
    provider: AIProvider;
    apiUrl: string;
    apiKey: string;
    modelName: string;
    enabled: boolean;
}

// 插件设置接口
interface JinaLinkerSettings {
    pythonPath: string;
    jinaApiKey: string;
    // AI模型配置 - 支持多个AI提供商
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
    jinaModelName: string;
    maxCharsForJina: number;
    maxContentLengthForAI: number;
    maxCandidatesPerSourceForAIScoring: number;
    minAiScoreForLinkInsertion: number;
    maxLinksToInsertPerNote: number;
}

// 类型定义优化
interface EmbeddingData {
    files: Record<string, FileEmbedding>;
    metadata?: EmbeddingMetadata;
}

interface FileEmbedding {
    hash: string;
    embedding?: number[];
    last_updated?: string;
    last_hash_updated_at?: string;
}

interface EmbeddingMetadata {
    version?: string;
    last_updated?: string;
    total_files?: number;
}

interface ProcessingError {
    type: 'PYTHON_NOT_FOUND' | 'API_KEY_INVALID' | 'FILE_NOT_FOUND' | 'PERMISSION_DENIED' | 'UNKNOWN';
    message: string;
    details?: string;
    suggestions?: string[];
}

interface OperationResult<T = any> {
    success: boolean;
    data?: T;
    error?: ProcessingError;
}

// 性能监控类
class PerformanceMonitor {
    private metrics = new Map<string, number[]>();
    
    startTimer(operation: string): () => void {
        const start = performance.now();
        return () => {
            const duration = performance.now() - start;
            this.recordMetric(operation, duration);
        };
    }
    
    private recordMetric(operation: string, duration: number): void {
        if (!this.metrics.has(operation)) {
            this.metrics.set(operation, []);
        }
        const times = this.metrics.get(operation)!;
        times.push(duration);
        
        // 保持最近100次记录
        if (times.length > 100) {
            times.shift();
        }
    }
    
    getAverageTime(operation: string): number {
        const times = this.metrics.get(operation) || [];
        if (times.length === 0) return 0;
        return times.reduce((a, b) => a + b, 0) / times.length;
    }
    
    getMetricsSummary(): Record<string, {avg: number, count: number}> {
        const summary: Record<string, {avg: number, count: number}> = {};
        for (const [operation, times] of this.metrics.entries()) {
            summary[operation] = {
                avg: this.getAverageTime(operation),
                count: times.length
            };
        }
        return summary;
    }
}

// 文件路径工具类
class FilePathUtils {
    static normalizePath(filePath: string): string {
        return normalizePath(filePath);
    }
    
    static isMarkdownFile(file: TFile): boolean {
        return file.extension === 'md';
    }
    
    static getRelativePath(file: TFile, basePath: string): string {
        return path.relative(basePath, file.path);
    }
    
    static validatePath(inputPath: string): boolean {
        // 防止路径遍历攻击
        if (inputPath.includes('..') || inputPath.includes('~')) {
            return false;
        }
        return true;
    }
    
    static sanitizePathForLog(inputPath: string): string {
        // 隐藏敏感路径信息
        return inputPath.replace(/\/Users\/[^\/]+/, '/Users/***');
    }
}

// 默认AI模型配置
const DEFAULT_AI_MODELS: Record<AIProvider, AIModelConfig> = {
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

// 默认设置
const DEFAULT_SETTINGS: JinaLinkerSettings = {
    pythonPath: 'python', 
    jinaApiKey: '',
    aiModels: { ...DEFAULT_AI_MODELS },
    selectedAIProvider: 'deepseek',
    similarityThreshold: 0.70,
    excludedFolders: '.obsidian, Scripts, assets, Excalidraw, .trash, Python-Templater-Plugin-Output',
    excludedFilesPatterns: '*excalidraw*, template*.md, *.kanban.md, ^moc$, ^index$',
    jinaModelName: 'jina-embeddings-v3',
    maxCharsForJina: 8000,
    maxContentLengthForAI: 5000,
    maxCandidatesPerSourceForAIScoring: 20,
    minAiScoreForLinkInsertion: 6,
    maxLinksToInsertPerNote: 10
};

const EMBEDDINGS_FILE_NAME = "jina_embeddings.json";

// Modal动态选项接口
interface RunOptions {
    scanPath: string;
    scoringMode: "force" | "smart" | "skip";
}

class RunPluginModal extends Modal {
    plugin: JinaLinkerPlugin;
    onSubmit: (options: RunOptions) => void;
    options: RunOptions = {
        scanPath: '',
        scoringMode: 'smart',
    };

    constructor(app: App, plugin: JinaLinkerPlugin, onSubmit: (options: RunOptions) => void) {
        super(app);
        this.plugin = plugin;
        this.onSubmit = onSubmit;
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();

        contentEl.createEl('h2', { text: '配置 Jina Linker 运行参数' });

        new Setting(contentEl)
            .setName('扫描目标文件夹 (可选)')
            .setDesc('逗号分隔的仓库相对文件夹路径。请使用正斜杠 "/" 作为路径分隔符。输入“/”则扫描整个仓库 (会遵循全局排除设置)。例如：笔记/文件夹, 知识库/文章')
            .addText(text => text
                .setPlaceholder('输入“/”扫描整个仓库，或例如：文件夹1/子文件夹, 文件夹2')
                .setValue(this.options.scanPath)
                .onChange(value => {
                    this.options.scanPath = value.trim();
                }));

        new Setting(contentEl)
            .setName('AI 智能评分模式')
            .setDesc('决定如何处理候选链接对的 AI 评分。')
            .addDropdown(dropdown => dropdown
                .addOption('smart', '智能 (仅对未评分的进行评分)')
                .addOption('force', '强制重新评分 (对所有进行评分)')
                .addOption('skip', '跳过 AI 评分')
                .setValue(this.options.scoringMode)
                .onChange(value => {
                    this.options.scoringMode = value as "force" | "smart" | "skip";
                }));

        new Setting(contentEl)
            .addButton(button => button
                .setButtonText('开始处理')
                .setCta()
                .onClick(() => {
                    this.close();
                    this.onSubmit(this.options);
                }));
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

class CalculateHashModal extends Modal {
    plugin: JinaLinkerPlugin;
    onSubmit: (filePath: string) => void;
    filePath: string = '';
    inputEl: HTMLInputElement;
    
    // 用于存储自动完成的文件和文件夹路径
    allPaths: string[] = [];

    constructor(app: App, plugin: JinaLinkerPlugin, onSubmit: (filePath: string) => void) {
        super(app);
        this.plugin = plugin;
        this.onSubmit = onSubmit;
        
        // 加载所有文件路径
        this.loadAllPaths();
    }
    
    // 加载所有Markdown文件路径
    loadAllPaths() {
        this.allPaths = [];
        
        // 获取所有加载的文件
        const allFiles = this.app.vault.getAllLoadedFiles();
        
        // 只添加Markdown文件路径
        for (const file of allFiles) {
            if (file instanceof TFile && file.extension === 'md') {
                this.allPaths.push(file.path);
            }
        }
        
        // 排序路径，按字母顺序
        this.allPaths.sort();
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl('h2', { text: '计算笔记内容哈希值' });

        const settingDiv = contentEl.createDiv();
        settingDiv.addClass('jina-setting');
        
        const descEl = settingDiv.createDiv();
        descEl.addClass('setting-item-description');
        descEl.setText('请输入要计算哈希值的笔记的仓库相对路径。请使用正斜杠 "/" 作为路径分隔符 (例如：文件夹/笔记.md)。');
        
        // 创建路径输入控件容器
        const inputContainer = settingDiv.createDiv();
        inputContainer.addClass('jina-path-input-container');
        
        // 创建输入框
        this.inputEl = document.createElement('input');
        this.inputEl.addClass('jina-path-input');
        this.inputEl.setAttr('placeholder', '例如：Notes/MyNote.md');
        this.inputEl.value = this.filePath;
        inputContainer.appendChild(this.inputEl);
        
        // 创建路径选择按钮
        const browseButton = document.createElement('button');
        browseButton.setText('浏览...');
        browseButton.addClass('jina-browse-button');
        inputContainer.appendChild(browseButton);
        
        // 添加输入框变更事件
        this.inputEl.addEventListener('input', (e) => {
            this.filePath = this.inputEl.value;
        });
        
        // 添加路径选择按钮点击事件
        browseButton.addEventListener('click', () => {
            // 获取当前输入的部分路径
            const currentPath = this.inputEl.value.trim();
            
            // 打开文件选择对话框
            this.openPathSuggestModal(currentPath, (selectedPath) => {
                if (selectedPath) {
                    // 更新输入框值
                    this.inputEl.value = selectedPath;
                    this.filePath = selectedPath;
                    this.inputEl.focus();
                }
            });
        });
        
        // 按钮区域
        const buttonContainer = contentEl.createDiv();
        buttonContainer.addClass('jina-button-container');
        
        const submitButton = buttonContainer.createEl('button');
        submitButton.setText('计算哈希');
        submitButton.addClass('mod-cta');
        submitButton.addEventListener('click', () => {
            if (!this.filePath) {
                new Notice('请输入文件路径。');
                return;
            }
            this.close();
            this.onSubmit(this.filePath);
        });
        
        // 添加样式
        this.addStyles(contentEl);
    }
    
    // 打开路径建议弹窗
    openPathSuggestModal(currentPath: string, callback: (selectedPath: string) => void) {
        const modal = new PathSuggestModal(this.app, this.allPaths, currentPath, callback);
        modal.open();
    }
    
    // 添加样式
    addStyles(contentEl: HTMLElement) {
        const styleEl = contentEl.createEl('style');
        styleEl.textContent = `
            .jina-setting {
                padding: 12px 0;
            }
            .jina-path-input-container {
                display: flex;
                margin-top: 8px;
                gap: 8px;
                align-items: center;
            }
            .jina-path-input {
                flex-grow: 1;
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
                background-color: var(--background-modifier-form-field);
                border: 1px solid var(--background-modifier-border);
            }
            .jina-browse-button {
                padding: 6px 12px;
                background-color: var(--interactive-accent);
                color: var(--text-on-accent);
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            .jina-button-container {
                display: flex;
                justify-content: flex-end;
                margin-top: 12px;
            }
        `;
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

class AddHashBoundaryModal extends Modal {
    plugin: JinaLinkerPlugin;
    onSubmit: (filePaths: string) => void; 
    filePaths: string = '';
    inputEl: HTMLTextAreaElement;
    
    // 用于存储自动完成的文件和文件夹路径
    allPaths: string[] = [];

    constructor(app: App, plugin: JinaLinkerPlugin, onSubmit: (filePaths: string) => void) {
        super(app);
        this.plugin = plugin;
        this.onSubmit = onSubmit;
        
        // 加载所有文件和文件夹路径
        this.loadAllPaths();
    }
    
    // 加载所有文件和文件夹路径
    loadAllPaths() {
        this.allPaths = [];
        
        // 获取所有文件
        const allFiles = this.app.vault.getAllLoadedFiles();
        
        // 添加文件路径
        for (const file of allFiles) {
            if (file instanceof TFile && file.extension === 'md') {
                this.allPaths.push(file.path);
            } else if (file instanceof TFolder) {
                this.allPaths.push(file.path + "/");
            }
        }
        
        // 排序路径，按字母顺序
        this.allPaths.sort();
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl('h2', { text: '批量添加哈希边界标记' });

        const settingDiv = contentEl.createDiv();
        settingDiv.addClass('jina-setting');
        
        const descEl = settingDiv.createDiv();
        descEl.addClass('setting-item-description');
        descEl.setText('为指定的笔记文件添加 <!-- HASH_BOUNDARY --> 标记。请输入一个或多个仓库相对路径 (用英文逗号 "," 分隔)。请使用正斜杠 "/" 作为路径分隔符。可以是具体文件或文件夹 (例如：文件夹1/笔记.md, 文件夹2/)。');
        
        // 创建路径输入控件容器
        const inputContainer = settingDiv.createDiv();
        inputContainer.addClass('jina-path-input-container');
        
        // 创建输入框
        this.inputEl = document.createElement('textarea');
        this.inputEl.addClass('jina-path-textarea');
        this.inputEl.setAttr('rows', '3');
        this.inputEl.setAttr('placeholder', '例如：Notes/Note1.md, 文件夹/ 或留空处理所有文件');
        this.inputEl.value = this.filePaths;
        inputContainer.appendChild(this.inputEl);
        
        // 创建路径选择按钮
        const browseButton = document.createElement('button');
        browseButton.setText('浏览...');
        browseButton.addClass('jina-browse-button');
        inputContainer.appendChild(browseButton);
        
        // 添加输入框变更事件
        this.inputEl.addEventListener('input', (e) => {
            this.filePaths = this.inputEl.value;
        });
        
        // 添加路径选择按钮点击事件
        browseButton.addEventListener('click', () => {
            // 获取当前光标位置的路径上下文
            const cursorPos = this.inputEl.selectionStart;
            const text = this.inputEl.value;
            
            // 查找光标前的最后一个逗号位置
            let startPos = text.lastIndexOf(',', cursorPos - 1);
            if (startPos === -1) startPos = 0;
            else startPos += 1; // 跳过逗号
            
            // 提取当前输入的部分路径
            const currentPath = text.substring(startPos, cursorPos).trim();
            
            // 打开文件选择对话框
            this.openPathSuggestModal(currentPath, (selectedPath) => {
                if (selectedPath) {
                    // 构建新的输入值，替换当前路径部分
                    const newValue = text.substring(0, startPos) + 
                                   (startPos > 0 ? ' ' : '') + 
                                   selectedPath + 
                                   text.substring(cursorPos);
                    
                    // 更新输入框值
                    this.inputEl.value = newValue;
                    this.filePaths = newValue;
                    
                    // 设置光标位置到路径后面
                    const newCursorPos = startPos + selectedPath.length + (startPos > 0 ? 1 : 0);
                    this.inputEl.setSelectionRange(newCursorPos, newCursorPos);
                    this.inputEl.focus();
                }
            });
        });
        
        // 按钮区域
        const buttonContainer = contentEl.createDiv();
        buttonContainer.addClass('jina-button-container');
        
        const submitButton = buttonContainer.createEl('button');
        submitButton.setText('添加标记');
        submitButton.addClass('mod-cta');
        submitButton.addEventListener('click', () => {
            this.close();
            this.onSubmit(this.filePaths);
        });
        
        // 添加样式
        this.addStyles(contentEl);
    }
    
    // 打开路径建议弹窗
    openPathSuggestModal(currentPath: string, callback: (selectedPath: string) => void) {
        const modal = new PathSuggestModal(this.app, this.allPaths, currentPath, callback);
        modal.open();
    }
    
    // 添加样式
    addStyles(contentEl: HTMLElement) {
        const styleEl = contentEl.createEl('style');
        styleEl.textContent = `
            .jina-setting {
                padding: 12px 0;
            }
            .jina-path-input-container {
                display: flex;
                margin-top: 8px;
                gap: 8px;
                align-items: flex-start;
            }
            .jina-path-textarea {
                flex-grow: 1;
                min-height: 60px;
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
                background-color: var(--background-modifier-form-field);
                border: 1px solid var(--background-modifier-border);
            }
            .jina-browse-button {
                padding: 6px 12px;
                background-color: var(--interactive-accent);
                color: var(--text-on-accent);
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            .jina-button-container {
                display: flex;
                justify-content: flex-end;
                margin-top: 12px;
            }
        `;
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

class UpdateHashesModal extends Modal {
    plugin: JinaLinkerPlugin;
    onSubmit: (filePaths: string) => void; 
    filePaths: string = '';
    inputEl: HTMLTextAreaElement;
    
    // 用于存储自动完成的文件和文件夹路径
    allPaths: string[] = [];

    constructor(app: App, plugin: JinaLinkerPlugin, onSubmit: (filePaths: string) => void) {
        super(app);
        this.plugin = plugin;
        this.onSubmit = onSubmit;
        
        // 加载所有文件和文件夹路径
        this.loadAllPaths();
    }
    
    // 加载所有文件和文件夹路径
    loadAllPaths() {
        this.allPaths = [];
        
        // 获取所有文件
        const allFiles = this.app.vault.getAllLoadedFiles();
        
        // 添加文件路径
        for (const file of allFiles) {
            if (file instanceof TFile && file.extension === 'md') {
                this.allPaths.push(file.path);
            } else if (file instanceof TFolder) {
                this.allPaths.push(file.path + "/");
            }
        }
        
        // 排序路径，按字母顺序
        this.allPaths.sort();
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl('h2', { text: '更新嵌入数据中的笔记哈希值' });

        const settingDiv = contentEl.createDiv();
        settingDiv.addClass('jina-setting');
        
        const descEl = settingDiv.createDiv();
        descEl.addClass('setting-item-description');
        descEl.setText('请输入一个或多个仓库相对路径 (用英文逗号 "," 分隔)。请使用正斜杠 "/" 作为路径分隔符。可以是具体文件或文件夹 (例如：文件夹1/笔记.md, 文件夹2/)。');
        
        // 创建路径输入控件容器
        const inputContainer = settingDiv.createDiv();
        inputContainer.addClass('jina-path-input-container');
        
        // 创建输入框
        this.inputEl = document.createElement('textarea');
        this.inputEl.addClass('jina-path-textarea');
        this.inputEl.setAttr('rows', '3');
        this.inputEl.setAttr('placeholder', '例如：Notes/Note1.md, 文件夹/');
        this.inputEl.value = this.filePaths;
        inputContainer.appendChild(this.inputEl);
        
        // 创建路径选择按钮
        const browseButton = document.createElement('button');
        browseButton.setText('浏览...');
        browseButton.addClass('jina-browse-button');
        inputContainer.appendChild(browseButton);
        
        // 添加输入框变更事件
        this.inputEl.addEventListener('input', (e) => {
            this.filePaths = this.inputEl.value;
        });
        
        // 添加路径选择按钮点击事件
        browseButton.addEventListener('click', () => {
            // 获取当前光标位置的路径上下文
            const cursorPos = this.inputEl.selectionStart;
            const text = this.inputEl.value;
            
            // 查找光标前的最后一个逗号位置
            let startPos = text.lastIndexOf(',', cursorPos - 1);
            if (startPos === -1) startPos = 0;
            else startPos += 1; // 跳过逗号
            
            // 提取当前输入的部分路径
            const currentPath = text.substring(startPos, cursorPos).trim();
            
            // 打开文件选择对话框
            this.openPathSuggestModal(currentPath, (selectedPath) => {
                if (selectedPath) {
                    // 构建新的输入值，替换当前路径部分
                    const newValue = text.substring(0, startPos) + 
                                   (startPos > 0 ? ' ' : '') + 
                                   selectedPath + 
                                   text.substring(cursorPos);
                    
                    // 更新输入框值
                    this.inputEl.value = newValue;
                    this.filePaths = newValue;
                    
                    // 设置光标位置到路径后面
                    const newCursorPos = startPos + selectedPath.length + (startPos > 0 ? 1 : 0);
                    this.inputEl.setSelectionRange(newCursorPos, newCursorPos);
                    this.inputEl.focus();
                }
            });
        });
        
        // 按钮区域
        const buttonContainer = contentEl.createDiv();
        buttonContainer.addClass('jina-button-container');
        
        const submitButton = buttonContainer.createEl('button');
        submitButton.setText('更新哈希值');
        submitButton.addClass('mod-cta');
        submitButton.addEventListener('click', () => {
            if (!this.filePaths.trim()) {
                new Notice('请输入至少一个文件路径。');
                return;
            }
            this.close();
            this.onSubmit(this.filePaths);
        });
        
        // 添加样式
        this.addStyles(contentEl);
    }
    
    // 打开路径建议弹窗
    openPathSuggestModal(currentPath: string, callback: (selectedPath: string) => void) {
        const modal = new PathSuggestModal(this.app, this.allPaths, currentPath, callback);
        modal.open();
    }
    
    // 添加样式
    addStyles(contentEl: HTMLElement) {
        const styleEl = contentEl.createEl('style');
        styleEl.textContent = `
            .jina-setting {
                padding: 12px 0;
            }
            .jina-path-input-container {
                display: flex;
                margin-top: 8px;
                gap: 8px;
                align-items: flex-start;
            }
            .jina-path-textarea {
                flex-grow: 1;
                min-height: 60px;
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
                background-color: var(--background-modifier-form-field);
                border: 1px solid var(--background-modifier-border);
            }
            .jina-browse-button {
                padding: 6px 12px;
                background-color: var(--interactive-accent);
                color: var(--text-on-accent);
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            .jina-button-container {
                display: flex;
                justify-content: flex-end;
                margin-top: 12px;
            }
        `;
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

// 进度显示模态框
class ProgressModal extends Modal {
    private progressBar: HTMLElement;
    private statusText: HTMLElement;
    private detailsText: HTMLElement;
    private cancelButton: HTMLElement;
    private onCancel?: () => void;
    
    constructor(app: App, title: string, onCancel?: () => void) {
        super(app);
        this.onCancel = onCancel;
        this.modalEl.addClass('jina-progress-modal');
        this.titleEl.setText(title);
    }
    
    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        
        // 状态文本
        this.statusText = contentEl.createEl('div', { 
            cls: 'jina-progress-status',
            text: '准备中...' 
        });
        
        // 进度条容器
        const progressContainer = contentEl.createDiv('jina-progress-container');
        const progressTrack = progressContainer.createDiv('jina-progress-track');
        this.progressBar = progressTrack.createDiv('jina-progress-bar');
        
        // 详细信息
        this.detailsText = contentEl.createEl('div', { 
            cls: 'jina-progress-details',
            text: '' 
        });
        
        // 取消按钮
        if (this.onCancel) {
            const buttonContainer = contentEl.createDiv('jina-progress-buttons');
            this.cancelButton = buttonContainer.createEl('button', {
                text: '取消操作',
                cls: 'mod-warning'
            });
            this.cancelButton.addEventListener('click', () => {
                this.onCancel?.();
                this.close();
            });
        }
        
        this.addStyles();
    }
    
    updateProgress(current: number, total: number, status: string, details?: string) {
        const percentage = total > 0 ? (current / total) * 100 : 0;
        this.progressBar.style.width = `${percentage}%`;
        this.statusText.textContent = `${status} (${current}/${total})`;
        
        if (details) {
            this.detailsText.textContent = details;
        }
    }
    
    setCompleted(message: string) {
        this.progressBar.style.width = '100%';
        this.statusText.textContent = message;
        this.detailsText.textContent = '';
        
        if (this.cancelButton) {
            this.cancelButton.textContent = '关闭';
            this.cancelButton.removeClass('mod-warning');
            this.cancelButton.addClass('mod-cta');
        }
    }
    
    setError(message: string) {
        this.statusText.textContent = `❌ ${message}`;
        this.progressBar.style.backgroundColor = 'var(--color-red)';
        
        if (this.cancelButton) {
            this.cancelButton.textContent = '关闭';
            this.cancelButton.removeClass('mod-warning');
        }
    }
    
    private addStyles() {
        const styleEl = this.contentEl.createEl('style');
        styleEl.textContent = `
            .jina-progress-modal .modal-content {
                padding: 20px;
                min-width: 400px;
            }
            .jina-progress-status {
                font-size: 16px;
                font-weight: 500;
                margin-bottom: 15px;
                color: var(--text-normal);
            }
            .jina-progress-container {
                margin-bottom: 15px;
            }
            .jina-progress-track {
                width: 100%;
                height: 8px;
                background-color: var(--background-secondary);
                border-radius: 4px;
                overflow: hidden;
            }
            .jina-progress-bar {
                height: 100%;
                background-color: var(--interactive-accent);
                transition: width 0.3s ease;
                width: 0%;
            }
            .jina-progress-details {
                font-size: 14px;
                color: var(--text-muted);
                margin-bottom: 15px;
                min-height: 20px;
            }
            .jina-progress-buttons {
                display: flex;
                justify-content: flex-end;
            }
        `;
    }
    
    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

// 用于路径自动完成的modal
class PathSuggestModal extends FuzzySuggestModal<string> {
    paths: string[];
    inputText: string;
    callback: (selectedPath: string) => void;
    
    constructor(app: App, paths: string[], inputText: string, callback: (selectedPath: string) => void) {
        super(app);
        this.paths = paths;
        this.inputText = inputText || '';
        this.callback = callback;
        this.setPlaceholder('选择文件或文件夹路径');
        
        // 设置初始查询文本
        if (this.inputText) {
            this.inputEl.value = this.inputText;
            // 触发输入事件以显示初始结果
            this.inputEl.dispatchEvent(new Event('input'));
        }
    }
    
    getItems(): string[] {
        return this.paths;
    }
    
    getItemText(path: string): string {
        return path;
    }
    
    onChooseItem(path: string, evt: MouseEvent | KeyboardEvent): void {
        this.callback(path);
    }
    
    renderSuggestion(item: FuzzyMatch<string>, el: HTMLElement): void {
        const match = item.item;
        el.setText(match);
        
        // 如果路径以/结尾，表示是文件夹，添加特殊样式
        if (match.endsWith('/')) {
            el.addClass('jina-folder-path');
            const iconEl = el.createSpan({cls: 'jina-folder-icon'});
            iconEl.setText('📁 ');
            el.prepend(iconEl);
        } else {
            el.addClass('jina-file-path');
            const iconEl = el.createSpan({cls: 'jina-file-icon'});
            iconEl.setText('📄 ');
            el.prepend(iconEl);
        }
    }
}

export default class JinaLinkerPlugin extends Plugin {
    settings: JinaLinkerSettings;
    performanceMonitor: PerformanceMonitor; // 改为public以便在设置页面访问
    private fileContentCache = new Map<string, {content: string, mtime: number}>();
    private currentOperation: AbortController | null = null;

    async onload() {
        console.log('🚀 Jina AI Linker 插件开始加载...');
        await this.loadSettings();
        console.log('✅ 插件设置加载完成');
        this.performanceMonitor = new PerformanceMonitor();
        console.log('✅ 性能监控器初始化完成');
        console.log('🎉 Jina AI Linker 插件加载完成！');

        this.addCommand({
            id: 'run-jina-linker-processing-and-insert-links',
            name: '处理笔记并插入建议链接',
            callback: () => {
                console.log('📝 用户启动：处理笔记并插入建议链接功能');
                new RunPluginModal(this.app, this, async (options) => {
                    const progressModal = new ProgressModal(this.app, 'Jina AI Linker 处理进度', () => {
                        this.currentOperation?.abort();
                    });
                    progressModal.open();
                    
                    try {
                        // 第一阶段：运行Python脚本
                        progressModal.updateProgress(0, 2, '正在运行Python脚本', '生成嵌入数据和AI评分...');
                        const result = await this.runPythonScript(options.scanPath, options.scoringMode);
                        
                        if (result.success) {
                            // 第二阶段：插入链接
                            progressModal.updateProgress(1, 2, '正在插入建议链接', '处理笔记文件...');
                            const insertResult = await this.insertAISuggestedLinksIntoNotes(options.scanPath);
                            
                            if (insertResult.success) {
                                const { processedFiles, updatedFiles } = insertResult.data!;
                                progressModal.setCompleted(`✅ 处理完成！检查了 ${processedFiles} 个文件，更新了 ${updatedFiles} 个文件`);
                                
                                // 显示性能统计
                                const metrics = this.performanceMonitor.getMetricsSummary();
                                this.log('info', '性能统计', metrics);
                                
                                setTimeout(() => progressModal.close(), 3000);
                            } else {
                                progressModal.setError('链接插入失败');
                            }
                        } else {
                            progressModal.setError('Python脚本执行失败');
                        }
                    } catch (error: any) {
                        progressModal.setError('处理过程中发生错误');
                        this.log('error', '处理过程中发生错误', error);
                    }
                }).open();
            }
        });

        this.addRibbonIcon('link', 'Jina Linker 工具', (evt: MouseEvent) => {
            // 创建菜单
            const menu = new Menu();
            
            menu.addItem((item) => {
                item.setTitle("处理笔记并插入建议链接")
                   .setIcon("link")
                   .onClick(() => {
                        new RunPluginModal(this.app, this, async (options) => {
                            const pythonSuccess = await this.runPythonScript(options.scanPath, options.scoringMode);
                            if (pythonSuccess.success) { // Check success property
                                new Notice('Python 脚本执行完毕。现在尝试插入建议链接...', 5000);
                                await this.insertAISuggestedLinksIntoNotes(options.scanPath);
                            } else {
                                new Notice('Python 脚本执行失败。链接插入步骤将被跳过。', 0);
                            }
                        }).open();
                   });
            });
            
            menu.addItem((item) => {
                item.setTitle("计算笔记内容哈希值 (诊断用)")
                   .setIcon("hash")
                   .onClick(() => {
                        new CalculateHashModal(this.app, this, async (filePath) => {
                            const normalizedFilePath = normalizePath(filePath);
                            const tFile = this.app.vault.getAbstractFileByPath(normalizedFilePath);

                            if (!(tFile instanceof TFile)) {
                                new Notice(`错误：文件 "${normalizedFilePath}" 未找到或不是一个有效文件。`);
                                return;
                            }
                            
                            const hash = await this.calculateNoteContentHashForFile(tFile);
                            if (hash) {
                                new Notice(`文件 "${filePath}" 的内容哈希值: ${hash}`);
                            }
                        }).open();
                   });
            });
            
            menu.addItem((item) => {
                item.setTitle("更新嵌入数据中的笔记哈希值")
                   .setIcon("refresh-cw")
                   .onClick(() => {
                        new UpdateHashesModal(this.app, this, async (filePathsStr) => {
                            const relativePaths = filePathsStr.split(',').map(p => p.trim()).filter(p => p);
                            if (relativePaths.length === 0) {
                                new Notice('未提供有效的文件路径。');
                                return;
                            }
                            await this.updateHashesInEmbeddingsFile(relativePaths);
                        }).open();
                   });
            });

            menu.addItem((item) => {
                item.setTitle("更新 YAML 笔记路径")
                   .setIcon("folder-symlink")
                   .onClick(async () => {
                        new Notice('JinaLinker: 开始执行 Python 脚本更新 YAML 路径...', 5000);
                        const pythonSuccess = await this.runPythonScriptForPathUpdate();
                        if (pythonSuccess.success) { // Check success property
                            new Notice('JinaLinker: YAML 路径更新脚本执行完毕。', 5000);
                        } else {
                            new Notice('JinaLinker: YAML 路径更新脚本执行失败。', 0);
                        }
                   });
            });

            menu.addItem((item) => {
                item.setTitle("批量添加哈希边界标记")
                   .setIcon("hash")
                   .onClick(() => {
                        new AddHashBoundaryModal(this.app, this, async (targetPaths) => {
                            const result = await this.addHashBoundaryMarkers(targetPaths);
                            if (result.success) {
                                const { processedFiles, updatedFiles } = result.data!;
                                new Notice(`✅ 处理完成！检查了 ${processedFiles} 个文件，添加标记到 ${updatedFiles} 个文件`);
                            } else {
                                new Notice('❌ 批量添加哈希边界标记失败');
                            }
                        }).open();
                   });
            });
            
            menu.showAtMouseEvent(evt);
        });

        this.addCommand({
            id: 'calculate-note-content-hash',
            name: '计算笔记内容哈希值 (诊断用)',
            callback: () => {
                console.log('🔢 用户启动：计算笔记内容哈希值功能');
                new CalculateHashModal(this.app, this, async (filePath) => {
                    const normalizedFilePath = normalizePath(filePath);
                    const tFile = this.app.vault.getAbstractFileByPath(normalizedFilePath);

                    if (!(tFile instanceof TFile)) {
                        new Notice(`错误：文件 "${normalizedFilePath}" 未找到或不是一个有效文件。`);
                        return;
                    }
                    
                    const hash = await this.calculateNoteContentHashForFile(tFile);
                    if (hash) {
                        new Notice(`文件 "${filePath}" 的内容哈希值: ${hash}`);
                    }
                }).open();
            }
        });

        this.addCommand({
            id: 'update-hashes-in-embeddings-file',
            name: '更新嵌入数据中的笔记哈希值',
            callback: () => {
                console.log('🔄 用户启动：更新嵌入数据中的笔记哈希值功能');
                new UpdateHashesModal(this.app, this, async (filePathsStr) => {
                    const relativePaths = filePathsStr.split(',').map(p => p.trim()).filter(p => p);
                    if (relativePaths.length === 0) {
                        new Notice('未提供有效的文件路径。');
                        return;
                    }
                    await this.updateHashesInEmbeddingsFile(relativePaths);
                }).open();
            }
        });

        this.addCommand({
            id: 'update-yaml-note-paths',
            name: '更新 YAML 笔记路径',
            callback: async () => {
                new Notice('JinaLinker: 开始执行 Python 脚本更新 YAML 路径...', 5000);
                const result = await this.runPythonScriptForPathUpdate();
                if (result.success) {
                    new Notice('JinaLinker: YAML 路径更新脚本执行完毕。', 5000);
                } else {
                    new Notice('JinaLinker: YAML 路径更新脚本执行失败。', 0);
                }
            }
        });

        this.addCommand({
            id: 'add-hash-boundary-markers',
            name: '批量添加哈希边界标记',
            callback: () => {
                console.log('🏷️ 用户启动：批量添加哈希边界标记功能');
                new AddHashBoundaryModal(this.app, this, async (targetPaths) => {
                    const result = await this.addHashBoundaryMarkers(targetPaths);
                    if (result.success) {
                        const { processedFiles, updatedFiles } = result.data!;
                        new Notice(`✅ 处理完成！检查了 ${processedFiles} 个文件，添加标记到 ${updatedFiles} 个文件`);
                    } else {
                        new Notice('❌ 批量添加哈希边界标记失败');
                    }
                }).open();
            }
        });


        this.addSettingTab(new JinaLinkerSettingTab(this.app, this));
        new Notice('Jina AI Linker 插件已加载。');
    }

    onunload() {
        // 清理资源
        this.cancelCurrentOperation();
        this.fileContentCache.clear();
        new Notice('Jina AI Linker 插件已卸载。');
    }

    // 取消当前操作
    cancelCurrentOperation(): void {
        if (this.currentOperation) {
            this.currentOperation.abort();
            this.currentOperation = null;
            new Notice('⚠️ 操作已取消', 3000);
        }
    }

    // 清理缓存
    clearCache(): void {
        this.fileContentCache.clear();
        new Notice('🧹 缓存已清理', 2000);
    }

    async loadSettings() {
        const loadedData = await this.loadData();
        
        // 合并默认设置
        this.settings = Object.assign({}, DEFAULT_SETTINGS, loadedData);
        
        // 确保AI模型配置完整性
        if (!this.settings.aiModels) {
            this.settings.aiModels = { ...DEFAULT_AI_MODELS };
        } else {
            // 合并缺失的AI模型配置
            for (const provider of Object.keys(DEFAULT_AI_MODELS) as AIProvider[]) {
                if (!this.settings.aiModels[provider]) {
                    this.settings.aiModels[provider] = { ...DEFAULT_AI_MODELS[provider] };
                } else {
                    // 确保每个AI模型配置都有完整的字段
                    this.settings.aiModels[provider] = Object.assign(
                        {}, 
                        DEFAULT_AI_MODELS[provider], 
                        this.settings.aiModels[provider]
                    );
                }
            }
        }
        
        // 兼容旧版本设置
        if (loadedData && loadedData.deepseekApiKey && !this.settings.aiModels.deepseek.apiKey) {
            this.settings.aiModels.deepseek.apiKey = loadedData.deepseekApiKey;
            this.settings.aiModels.deepseek.enabled = true;
        }
        
        // 确保选中的AI提供商有效
        if (!this.settings.selectedAIProvider || !this.settings.aiModels[this.settings.selectedAIProvider]) {
            this.settings.selectedAIProvider = 'deepseek';
        }
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    // 性能优化：缓存文件内容
    async getCachedFileContent(file: TFile): Promise<string> {
        const mtime = file.stat.mtime;
        const cached = this.fileContentCache.get(file.path);
        if (cached && cached.mtime === mtime) {
            return cached.content;
        }
        const content = await this.app.vault.read(file);
        this.fileContentCache.set(file.path, {content, mtime});
        
        // 限制缓存大小
        if (this.fileContentCache.size > 100) {
            const firstKey = this.fileContentCache.keys().next().value;
            this.fileContentCache.delete(firstKey);
        }
        
        return content;
    }

    // 错误处理优化
    private createProcessingError(type: ProcessingError['type'], message: string, details?: string): ProcessingError {
        const suggestions: string[] = [];
        
        switch (type) {
            case 'PYTHON_NOT_FOUND':
                suggestions.push('请检查Python路径设置是否正确');
                suggestions.push('确保Python已正确安装并在PATH中');
                break;
            case 'API_KEY_INVALID':
                suggestions.push('请检查API密钥是否正确配置');
                suggestions.push('确认API密钥有效且未过期');
                break;
            case 'FILE_NOT_FOUND':
                suggestions.push('请检查文件路径是否存在');
                suggestions.push('确认文件未被移动或删除');
                break;
            case 'PERMISSION_DENIED':
                suggestions.push('请检查文件/目录权限');
                suggestions.push('尝试以管理员权限运行');
                break;
        }
        
        return { type, message, details, suggestions };
    }

    private handleError(error: ProcessingError): void {
        new Notice(`❌ ${error.message}`, 0);
        
        if (error.suggestions && error.suggestions.length > 0) {
            setTimeout(() => {
                error.suggestions!.forEach((suggestion, index) => {
                    new Notice(`💡 建议${index + 1}: ${suggestion}`, 8000);
                });
            }, 1000);
        }
        
        this.log('error', error.message, error);
    }

    // 日志优化
    private log(level: 'info' | 'warn' | 'error', message: string, data?: any): void {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] [${level.toUpperCase()}] JinaLinker: ${message}`;
        
        switch (level) {
            case 'error':
                console.error(logEntry, data);
                break;
            case 'warn':
                console.warn(logEntry, data);
                break;
            default:
                console.log(logEntry, data);
        }
    }

    // 设置验证
    validateSettings(): ProcessingError[] {
        const errors: ProcessingError[] = [];
        
        if (!this.settings.jinaApiKey?.trim()) {
            errors.push(this.createProcessingError('API_KEY_INVALID', 'Jina API密钥未配置'));
        }
        
        if (this.settings.similarityThreshold < 0 || this.settings.similarityThreshold > 1) {
            errors.push(this.createProcessingError('UNKNOWN', '相似度阈值必须在0-1之间'));
        }
        
        if (!this.settings.pythonPath?.trim()) {
            errors.push(this.createProcessingError('PYTHON_NOT_FOUND', 'Python路径未配置'));
        }
        
        return errors;
    }

    // API密钥安全处理
    private sanitizeArgsForLog(args: string[]): string[] {
        return args.map(arg => {
            if (arg.includes('api_key') || arg.startsWith('sk-') || arg.startsWith('Bearer ')) {
                return arg.replace(/sk-[a-zA-Z0-9]+/g, 'sk-***').replace(/Bearer [a-zA-Z0-9]+/g, 'Bearer ***');
            }
            return FilePathUtils.sanitizePathForLog(arg);
        });
    }

    // 类型守卫
    private isValidEmbeddingData(data: any): data is EmbeddingData {
        return data && 
               typeof data === 'object' && 
               typeof data.files === 'object' && 
               data.files !== null;
    }

    private extractContentForHashingFromText(fullContent: string): string | null {
        let bodyContentAfterFM = fullContent;
        const fmRegex = /^---\s*$\n([\s\S]*?)\n^---\s*$\n?/m;
        const fmMatch = fullContent.match(fmRegex);
        if (fmMatch) {
            bodyContentAfterFM = fullContent.substring(fmMatch[0].length);
        }

        const marker = HASH_BOUNDARY_MARKER; // Use settings for boundary marker
        const markerIndex = bodyContentAfterFM.indexOf(marker);

        if (markerIndex !== -1) {
            let contentToHash = bodyContentAfterFM.substring(0, markerIndex);
            if (!contentToHash.trim()) {
                return "\n"; 
            }
            contentToHash = contentToHash.replace(/\r\n/g, "\n").replace(/\s+$/, "");
            return contentToHash + "\n";
        }
        return null;
    }
    
    async calculateNoteContentHashForFile(file: TFile): Promise<string | null> {
        try {
            const fileContent = await this.app.vault.read(file);
            const contentForHashing = this.extractContentForHashingFromText(fileContent);

            if (contentForHashing === null) {
                new Notice(`错误: 文件 "${file.path}" 中未找到哈希边界标记 "${HASH_BOUNDARY_MARKER}" (在 frontmatter 之后)。无法计算哈希。`);
                return null;
            }
            
            const hasher = crypto.createHash('sha256');
            hasher.update(contentForHashing, 'utf-8');
            return hasher.digest('hex');

        } catch (error: any) {
            new Notice(`计算文件 "${file.path}" 哈希时发生错误: ${error.message}`);
            return null;
        }
    }

    async updateHashesInEmbeddingsFile(targetRelativePaths: string[]): Promise<void> {
        new Notice(`开始处理 ${targetRelativePaths.length} 个路径，更新哈希值...`);
        
        // 使用默认输出目录，而不是用户设置的outputDirInVault
        const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
        const embeddingsFilePath = normalizePath(path.join(outputDirInVault, EMBEDDINGS_FILE_NAME));
        let embeddingsData: any;

        try {
            const fileExists = await this.app.vault.adapter.exists(embeddingsFilePath);
            if (!fileExists) {
                new Notice(`错误: 嵌入文件 "${embeddingsFilePath}" 未找到。`);
                return;
            }
            const rawData = await this.app.vault.adapter.read(embeddingsFilePath);
            embeddingsData = JSON.parse(rawData);
            if (!embeddingsData.files || typeof embeddingsData.files !== 'object') {
                throw new Error("嵌入文件结构不正确，缺少 'files' 对象。");
            }
        } catch (error: any) {
            new Notice(`读取或解析嵌入文件 "${embeddingsFilePath}" 失败: ${error.message}`);
            return;
        }
        
        // 用于存储要处理的所有Markdown文件
        let filesToProcess: TFile[] = [];
        
        // 处理每个输入路径，可能是文件或文件夹
        for (const relPath of targetRelativePaths) {
            const normalizedRelPathKey = normalizePath(relPath);
            const abstractFile = this.app.vault.getAbstractFileByPath(normalizedRelPathKey);
            
            if (!abstractFile) {
                new Notice(`警告: 路径 "${normalizedRelPathKey}" 不存在，跳过。`);
                continue;
            }
            
            // 如果是文件夹，递归获取所有Markdown文件
            if (abstractFile instanceof TFolder) {
                
                // 递归获取该文件夹下的所有Markdown文件
                const folderFiles = this.getMarkdownFilesInFolder(abstractFile);
                
                // 添加到处理列表
                filesToProcess = [...filesToProcess, ...folderFiles];
            } 
            // 如果是文件且是Markdown文件，直接添加到处理列表
            else if (abstractFile instanceof TFile && abstractFile.extension === 'md') {
                filesToProcess.push(abstractFile);
            }
            // 如果是其他类型的文件，跳过
            else {
                new Notice(`警告: 路径 "${normalizedRelPathKey}" 不是Markdown文件或文件夹，跳过。`);
            }
        }
        
        // 去重，避免重复处理同一文件
        filesToProcess = Array.from(new Set(filesToProcess));
        
        new Notice(`共找到 ${filesToProcess.length} 个Markdown文件需要处理...`);
        
        let updatedJsonCount = 0;
        let notFoundInJsonCount = 0;
        let hashCalculationFailedCount = 0;
        let noChangeCount = 0;
        let updatedFrontmatterCount = 0;
        // let processedCount = 0; // Removed unused variable

        // 处理每个文件
        for (const tFile of filesToProcess) {
            // processedCount++; // Removed unused variable
            const normalizedFilePath = tFile.path;

            const newHash = await this.calculateNoteContentHashForFile(tFile);
            if (!newHash) {
                hashCalculationFailedCount++;
                continue;
            }
            
            // 更新嵌入JSON中的哈希值
            // let jsonUpdated = false; // Removed unused variable
            if (embeddingsData.files.hasOwnProperty(normalizedFilePath)) {
                const entry = embeddingsData.files[normalizedFilePath];
                const oldHash = entry.hash;
                if (oldHash !== newHash) {
                    entry.hash = newHash;
                    entry.last_hash_updated_at = new Date().toISOString();
                    updatedJsonCount++;
                    // jsonUpdated = true; // Removed unused variable
                }
            } else {
                notFoundInJsonCount++;
            }
            
            // 更新文件frontmatter中的jina_hash
            try {
                // 读取文件内容
                const fileContent = await this.app.vault.read(tFile);
                
                // 检查是否存在frontmatter
                const fmRegex = /^---\s*\n([\s\S]*?)\n---\s*\n/;
                const fmMatch = fileContent.match(fmRegex);
                
                let newContent;
                let frontmatterUpdated = false;
                
                if (fmMatch) {
                    // 有frontmatter，检查是否需要更新jina_hash
                    const frontmatterContent = fmMatch[1];
                    const jinaHashRegex = /^jina_hash:\s*(.*)\s*$/m;
                    const jinaHashMatch = frontmatterContent.match(jinaHashRegex);
                    
                    if (jinaHashMatch) {
                        // 已有jina_hash，检查值是否需要更新
                        const oldHash = jinaHashMatch[1].trim();
                        if (oldHash !== newHash) {
                            // 需要更新jina_hash
                            const newFrontmatter = frontmatterContent.replace(
                                jinaHashRegex, 
                                `jina_hash: ${newHash}`
                            );
                            newContent = fileContent.replace(
                                fmMatch[0], 
                                `---\n${newFrontmatter}\n---\n`
                            );
                            frontmatterUpdated = true;
                        } else {
                            // No change in hash, do nothing
                        }
                    } else {
                        // 无jina_hash，添加到frontmatter末尾
                        const newFrontmatter = frontmatterContent + `\njina_hash: ${newHash}`;
                        newContent = fileContent.replace(
                            fmMatch[0], 
                            `---\n${newFrontmatter}\n---\n`
                        );
                        frontmatterUpdated = true;
                    }
                } else {
                    // 无frontmatter，创建包含jina_hash的frontmatter
                    newContent = `---\njina_hash: ${newHash}\n---\n\n${fileContent}`;
                    frontmatterUpdated = true;
                }
                
                // 如果需要更新，保存文件
                if (frontmatterUpdated && newContent) {
                    await this.app.vault.modify(tFile, newContent);
                    updatedFrontmatterCount++;
                } else {
                    noChangeCount++;
                }
                
            } catch (error: any) {
                new Notice(`更新文件 "${normalizedFilePath}" frontmatter时出错: ${error.message}`);
            }
        }

        // 保存更新后的嵌入文件
        if (updatedJsonCount > 0) {
            try {
                await this.app.vault.adapter.write(embeddingsFilePath, JSON.stringify(embeddingsData, null, 4));
            } catch (error: any) {
                new Notice(`写入更新后的嵌入文件 "${embeddingsFilePath}" 时发生错误: ${error.message}`);
                return;
            }
        }
        
        // 显示结果通知
        let summaryMsg;
        if (updatedJsonCount > 0 && updatedFrontmatterCount > 0) {
            summaryMsg = `成功更新了 ${updatedJsonCount} 个文件在嵌入JSON中的哈希值和 ${updatedFrontmatterCount} 个文件的frontmatter。`;
        } else if (updatedJsonCount > 0) {
            summaryMsg = `成功更新了 ${updatedJsonCount} 个文件在嵌入JSON中的哈希值。`;
        } else if (updatedFrontmatterCount > 0) {
            summaryMsg = `成功更新了 ${updatedFrontmatterCount} 个文件的frontmatter。`;
        } else {
            summaryMsg = "所有哈希值均已是最新，无需更新。";
        }
        
        new Notice(summaryMsg);
        
        let detailedSummary = `哈希更新摘要: ${updatedJsonCount} 个JSON已更新, ${updatedFrontmatterCount} 个frontmatter已更新, ${noChangeCount} 个无需更改, ${notFoundInJsonCount} 个在JSON中未找到, ${hashCalculationFailedCount} 个哈希计算失败。`;
        if (notFoundInJsonCount > 0 || hashCalculationFailedCount > 0) {
            new Notice(detailedSummary, 7000); 
        }
    }
    
    // 递归获取文件夹中的所有Markdown文件
    private getMarkdownFilesInFolder(folder: TFolder): TFile[] {
        let markdownFiles: TFile[] = [];
        
        // 获取所有加载的文件
        const allFiles = this.app.vault.getAllLoadedFiles();
        
        // 过滤出文件夹下的Markdown文件
        for (const file of allFiles) {
            if (file instanceof TFile && 
                file.extension === 'md' && 
                file.path.startsWith(folder.path)) {
                markdownFiles.push(file);
            }
        }
        
        return markdownFiles;
    }

    // 批量添加哈希边界标记
    async addHashBoundaryMarkers(targetRelativePaths: string): Promise<OperationResult<{processedFiles: number, updatedFiles: number}>> {
        console.log('🏷️ 开始执行：批量添加哈希边界标记');
        console.log(`📂 目标路径: ${targetRelativePaths}`);
        const endTimer = this.performanceMonitor.startTimer('addHashBoundaryMarkers');
        
        try {
            new Notice(`🔄 开始批量添加哈希边界标记...`);
            
            // 解析目标路径
            let filesToProcess: TFile[] = [];
            
            if (!targetRelativePaths.trim()) {
                // 如果没有指定路径，处理所有Markdown文件
                filesToProcess = this.app.vault.getMarkdownFiles();
                new Notice(`📁 将处理所有 ${filesToProcess.length} 个Markdown文件`);
            } else {
                // 处理指定的路径
                const pathList = targetRelativePaths.split(',').map(p => p.trim()).filter(p => p);
                
                for (const relPath of pathList) {
                    const normalizedRelPathKey = normalizePath(relPath);
                    const abstractFile = this.app.vault.getAbstractFileByPath(normalizedRelPathKey);
                    
                    if (!abstractFile) {
                        new Notice(`⚠️ 路径 "${normalizedRelPathKey}" 不存在，跳过`);
                        continue;
                    }
                    
                    if (abstractFile instanceof TFolder) {
                        // 如果是文件夹，递归获取所有Markdown文件
                        const folderFiles = this.getMarkdownFilesInFolder(abstractFile);
                        filesToProcess = [...filesToProcess, ...folderFiles];
                    } else if (abstractFile instanceof TFile && abstractFile.extension === 'md') {
                        // 如果是Markdown文件，直接添加
                        filesToProcess.push(abstractFile);
                    } else {
                        new Notice(`⚠️ "${normalizedRelPathKey}" 不是Markdown文件或文件夹，跳过`);
                    }
                }
                
                // 去重
                filesToProcess = Array.from(new Set(filesToProcess));
                new Notice(`📁 将处理 ${filesToProcess.length} 个Markdown文件`);
            }
            
            let processedCount = 0;
            let updatedCount = 0;
            
            for (const file of filesToProcess) {
                processedCount++;
                
                try {
                    const fileContent = await this.getCachedFileContent(file);
                    const hasMarker = fileContent.includes(HASH_BOUNDARY_MARKER);
                    
                    if (hasMarker) {
                        continue;
                    }
                    
                    // 分离frontmatter和正文
                    const fmRegex = /^---\s*$\n([\s\S]*?)\n^---\s*$\n?/m;
                    const fmMatch = fileContent.match(fmRegex);
                    let bodyContent = fileContent;
                    let frontmatterPart = '';
                    
                    if (fmMatch) {
                        frontmatterPart = fmMatch[0];
                        bodyContent = fileContent.substring(frontmatterPart.length);
                    }
                    
                    // 找到正文的最后一个非空行
                    const lines = bodyContent.split(/\r?\n/);
                    let lastNonEmptyLineIndex = -1;
                    
                    for (let i = lines.length - 1; i >= 0; i--) {
                        if (lines[i].trim().length > 0) {
                            lastNonEmptyLineIndex = i;
                            break;
                        }
                    }
                    
                    if (lastNonEmptyLineIndex === -1) {
                        // 如果正文完全为空，在开头添加标记
                        lines.splice(0, 0, '', HASH_BOUNDARY_MARKER);
                    } else {
                        // 在最后一个非空行后添加标记
                        lines.splice(lastNonEmptyLineIndex + 1, 0, '', HASH_BOUNDARY_MARKER);
                    }
                    
                    // 重新组合内容
                    const newBodyContent = lines.join('\n');
                    const finalContent = frontmatterPart + newBodyContent;
                    
                    // 写入文件
                    await this.app.vault.modify(file, finalContent);
                    updatedCount++;
                    
                    // 每处理10个文件显示一次进度
                    if (processedCount % 10 === 0) {
                        new Notice(`📊 已处理 ${processedCount}/${filesToProcess.length} 个文件，更新了 ${updatedCount} 个`, 2000);
                    }
                    
                } catch (error: any) {
                    this.log('error', `处理文件 ${file.path} 时发生错误`, error);
                }
            }
            
            endTimer();
            
            const summaryMessage = `哈希边界标记添加完成。检查了 ${processedCount} 个文件，更新了 ${updatedCount} 个文件。`;
            
            return {
                success: true,
                data: { processedFiles: processedCount, updatedFiles: updatedCount }
            };
            
        } catch (error: any) {
            endTimer();
            const processingError = this.createProcessingError('UNKNOWN',
                '批量添加哈希边界标记时发生错误',
                error instanceof Error ? error.message : String(error));
            this.handleError(processingError);
            return { success: false, error: processingError };
        }
    }

    async runPythonScript(scanPathFromModal: string, scoringModeFromModal: "force" | "smart" | "skip"): Promise<OperationResult<boolean>> {
        console.log('🐍 开始执行：Python脚本处理');
        console.log(`📂 扫描路径: ${scanPathFromModal}`);
        console.log(`🤖 AI评分模式: ${scoringModeFromModal}`);
        const endTimer = this.performanceMonitor.startTimer('runPythonScript');
        
        try {
            // 验证设置
            const validationErrors = this.validateSettings();
            if (validationErrors.length > 0) {
                validationErrors.forEach(error => this.handleError(error));
                return { success: false, error: validationErrors[0] };
            }

            // 创建可取消的操作
            this.currentOperation = new AbortController();
            
            return new Promise(async (resolve) => {
                let scriptToExecutePath = '';
                const vaultBasePath = (this.app.vault.adapter as any).getBasePath();
                const bundledScriptName = 'jina_obsidian_processor.py';
        
                // 默认使用插件自带脚本，不再考虑用户设置的scriptPath
                if (this.manifest.dir) {
                    scriptToExecutePath = path.join(vaultBasePath, this.manifest.dir, bundledScriptName);
                } else {
                    const error = this.createProcessingError('FILE_NOT_FOUND', 'Python 脚本路径无法确定');
                    this.handleError(error);
                    resolve({ success: false, error });
                    return;
                }
            
            // 使用默认输出目录，忽略用户设置
            const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
            const fullOutputDirPath = path.join(vaultBasePath, outputDirInVault);
            
                try {
                    // 改用 fs 模块直接创建目录
                    const fs = require('fs');
                    if (!fs.existsSync(fullOutputDirPath)) {
                        fs.mkdirSync(fullOutputDirPath, { recursive: true });
                    }
                } catch (error: any) {
                    const processingError = this.createProcessingError('PERMISSION_DENIED', 
                        `创建输出目录 "${outputDirInVault}" 失败`, 
                        error instanceof Error ? error.message : String(error));
                    this.handleError(processingError);
                    resolve({ success: false, error: processingError });
                    return;
                }

            let args = [
                scriptToExecutePath, 
                '--project_root', vaultBasePath,
                '--output_dir', outputDirInVault,
                '--jina_api_key', this.settings.jinaApiKey,
                '--ai_scoring_mode', scoringModeFromModal,
                '--similarity_threshold', this.settings.similarityThreshold.toString(),
                '--jina_model_name', this.settings.jinaModelName,
                '--max_chars_for_jina', this.settings.maxCharsForJina.toString(),
                '--max_candidates_per_source_for_ai_scoring', this.settings.maxCandidatesPerSourceForAIScoring.toString(),
                '--hash_boundary_marker', HASH_BOUNDARY_MARKER.replace(/"/g, '\\"'),
                '--max_content_length_for_ai', this.settings.maxContentLengthForAI.toString(),
            ];
            
            // 传递选中的AI模型配置
            const selectedAIModel = this.settings.aiModels[this.settings.selectedAIProvider];
            if (selectedAIModel && selectedAIModel.enabled && selectedAIModel.apiKey) {
                args.push('--ai_provider', this.settings.selectedAIProvider);
                args.push('--ai_api_url', selectedAIModel.apiUrl);
                args.push('--ai_api_key', selectedAIModel.apiKey);
                args.push('--ai_model_name', selectedAIModel.modelName);
            }
            
            if (scanPathFromModal && scanPathFromModal.trim() !== '/') {
                args.push('--scan_target_folders');
                const folders = scanPathFromModal.split(',').map(f => f.trim()).filter(f => f);
                args = args.concat(folders);
            }
            
            if (this.settings.excludedFolders) {
                args.push('--excluded_folders');
                const excludedFolders = this.settings.excludedFolders.split(',').map(f => f.trim()).filter(f => f);
                args = args.concat(excludedFolders);
            }
            
            if (this.settings.excludedFilesPatterns) {
                args.push('--excluded_files_patterns');
                const patterns = this.settings.excludedFilesPatterns.split(',').map(p => p.trim()).filter(p => p);
                args = args.concat(patterns);
            }
            
                new Notice('🚀 JinaLinker: 开始执行 Python 脚本...', 5000);
                // const sanitizedArgs = this.sanitizeArgsForLog(args); // Removed unused variable
            
                this.log('info', `执行 Python 命令: ${this.settings.pythonPath} ${this.sanitizeArgsForLog(args).join(' ')}`);
                const pythonProcess = spawn(this.settings.pythonPath, args, { 
                    stdio: ['pipe', 'pipe', 'pipe'],
                    signal: this.currentOperation?.signal
                });
            
                let scriptOutput = '';
                let scriptError = '';

                pythonProcess.stdout.on('data', (data) => {
                    if (this.currentOperation?.signal.aborted) return;
                    const outputChunk = data.toString();
                    scriptOutput += outputChunk;
                    this.log('info', `Python stdout: ${outputChunk.trim()}`); // Log stdout
                });

                pythonProcess.stderr.on('data', (data) => {
                    if (this.currentOperation?.signal.aborted) return;
                    const errorChunk = data.toString();
                    scriptError += errorChunk;
                    this.log('error', `Python stderr: ${errorChunk.trim()}`); // Log stderr
                });

                pythonProcess.on('close', (code) => {
                    endTimer();
                    this.currentOperation = null;
                    
                    if (code === 0) {
                        new Notice('✅ Python 脚本执行成功', 3000);
                        this.log('info', 'Python 脚本执行成功', scriptOutput);
                        resolve({ success: true, data: true });
                    } else {
                        const error = this.createProcessingError('UNKNOWN', 
                            'Python 脚本执行失败', 
                            `退出码: ${code}, 错误输出: ${scriptError}`);
                        this.handleError(error);
                        resolve({ success: false, error });
                    }
                });

                pythonProcess.on('error', (err: any) => {
                    endTimer();
                    this.currentOperation = null;
                    
                    let error: ProcessingError;
                    if (err.message.includes('ENOENT')) {
                        error = this.createProcessingError('PYTHON_NOT_FOUND', 
                            '找不到Python解释器', 
                            err.message);
                    } else {
                        error = this.createProcessingError('UNKNOWN', 
                            '启动 Python 脚本失败', 
                            err.message);
                    }
                    
                    this.handleError(error);
                    resolve({ success: false, error });
                });

                // 处理操作取消
                this.currentOperation?.signal.addEventListener('abort', () => {
                    pythonProcess.kill();
                    const error = this.createProcessingError('UNKNOWN', '操作已被用户取消');
                    resolve({ success: false, error });
                });
            });
        } catch (error: any) {
            endTimer();
            const processingError = this.createProcessingError('UNKNOWN', 
                '执行Python脚本时发生未知错误', 
                error instanceof Error ? error.message : String(error));
            return { success: false, error: processingError };
        }
    }

    async runPythonScriptForPathUpdate(): Promise<OperationResult<boolean>> {
        return new Promise(async (resolve) => {
            let scriptToExecutePath = '';
            const vaultBasePath = (this.app.vault.adapter as any).getBasePath();
            const bundledScriptName = 'jina_obsidian_processor.py';
    
            if (this.manifest.dir) {
                scriptToExecutePath = path.join(vaultBasePath, this.manifest.dir, bundledScriptName);
            } else {
                const error = this.createProcessingError('FILE_NOT_FOUND', 'Python 脚本路径无法确定');
                this.handleError(error);
                resolve({ success: false, error });
                return;
            }
            
            const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
            const fullOutputDirPath = path.join(vaultBasePath, outputDirInVault);
            
            try {
                const fs = require('fs');
                if (!fs.existsSync(fullOutputDirPath)) {
                    fs.mkdirSync(fullOutputDirPath, { recursive: true });
                }
            } catch (error: any) {
                const processingError = this.createProcessingError('PERMISSION_DENIED', 
                    `创建输出目录 "${outputDirInVault}" 失败`, 
                    error instanceof Error ? error.message : String(error));
                this.handleError(processingError);
                resolve({ success: false, error: processingError });
                return;
            }

            let args = [
                scriptToExecutePath, 
                '--project_root', vaultBasePath,
                '--output_dir', outputDirInVault,
                UPDATE_PATHS_ONLY_ARG, // New argument to trigger path update mode
            ];

            if (this.settings.excludedFolders) {
                args.push('--excluded_folders');
                const excludedFolders = this.settings.excludedFolders.split(',').map(f => f.trim()).filter(f => f);
                args = args.concat(excludedFolders);
            }
            
            if (this.settings.excludedFilesPatterns) {
                args.push('--excluded_files_patterns');
                const patterns = this.settings.excludedFilesPatterns.split(',').map(p => p.trim()).filter(p => p);
                args = args.concat(patterns);
            }
            
            const pythonProcess = spawn(this.settings.pythonPath, args, { stdio: ['pipe', 'pipe', 'pipe'] });
        
            // let scriptOutput = ''; // Removed unused variable
            // let scriptError = ''; // Removed unused variable

            pythonProcess.on('close', (code) => {
                if (code === 0) {
                    resolve({ success: true, data: true });
                } else {
                    const error = this.createProcessingError('UNKNOWN', 
                        'Python 脚本执行失败', 
                        `退出码: ${code}, 错误输出: (output not captured)`); // Modified error message
                    this.handleError(error);
                    resolve({ success: false, error });
                }
            });

            pythonProcess.on('error', (err: any) => { // Added type annotation for err
                let error: ProcessingError;
                if (err.message.includes('ENOENT')) {
                    error = this.createProcessingError('PYTHON_NOT_FOUND', 
                        '找不到Python解释器', 
                        err.message);
                } else {
                    error = this.createProcessingError('UNKNOWN', 
                        '启动 Python 脚本失败', 
                        err.message);
                }
                this.handleError(error);
                resolve({ success: false, error });
            });
        });
    }

    async insertAISuggestedLinksIntoNotes(targetFoldersOption: string): Promise<OperationResult<{processedFiles: number, updatedFiles: number}>> {
        console.log('🔗 开始执行：插入AI建议链接');
        console.log(`📂 目标文件夹: ${targetFoldersOption}`);
        const endTimer = this.performanceMonitor.startTimer('insertAISuggestedLinksIntoNotes');
        
        try {
            // 使用默认输出目录
            const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
            const aiScoresFilePath = FilePathUtils.normalizePath(path.join(outputDirInVault, 'ai_scores.json'));

            // 检查AI评分文件是否存在
            const aiScoresFileExists = await this.app.vault.adapter.exists(aiScoresFilePath);
            if (!aiScoresFileExists) {
                const error = this.createProcessingError('FILE_NOT_FOUND', 
                    `AI评分文件 "${aiScoresFilePath}" 未找到`, 
                    '请先运行Python脚本生成AI评分数据');
                this.handleError(error);
                return { success: false, error };
            }

            // 读取AI评分数据
            const rawAiScoresData = await this.app.vault.adapter.read(aiScoresFilePath);
            let aiScoresData: any;
            
            try {
                aiScoresData = JSON.parse(rawAiScoresData);
            } catch (parseError: any) { // Added type annotation for parseError
                const error = this.createProcessingError('UNKNOWN', 
                    '解析AI评分数据文件失败', 
                    parseError instanceof Error ? parseError.message : String(parseError));
                this.handleError(error);
                return { success: false, error };
            }

            this.log('info', "开始从JSON文件读取AI评分数据并插入建议链接");
            new Notice('🔄 正在从AI评分数据插入建议链接...', 3000);
            
            const allMarkdownFiles = this.app.vault.getMarkdownFiles().filter(FilePathUtils.isMarkdownFile);
            let processedFileCount = 0;
            let updatedFileCount = 0;

            const targetFolderPaths = targetFoldersOption.split(',').map(p => p.trim()).filter(p => p);
            const shouldProcessAll = targetFolderPaths.length === 0 || (targetFolderPaths.length === 1 && targetFolderPaths[0] === '/');
            this.log('info', `将为 ${allMarkdownFiles.length} 个 Markdown 文件执行链接插入`, {
                targetFolders: targetFolderPaths.length > 0 ? targetFoldersOption : '仓库根目录'
            });

            // 性能优化：批量处理文件
            const batchSize = 5;
            for (let i = 0; i < allMarkdownFiles.length; i += batchSize) {
                const batch = allMarkdownFiles.slice(i, i + batchSize);
                const batchResults = await Promise.allSettled(
                    batch.map(file => this.processFileForLinkInsertionFromJSON(file, targetFolderPaths, shouldProcessAll, aiScoresData))
                );
                
                for (const result of batchResults) {
                    if (result.status === 'fulfilled' && result.value) {
                        processedFileCount++;
                        if (result.value.updated) {
                            updatedFileCount++;
                        }
                    }
                }
                
                // 显示进度
                if (i % 20 === 0) {
                    new Notice(`📊 已处理 ${Math.min(i + batchSize, allMarkdownFiles.length)}/${allMarkdownFiles.length} 个文件`, 2000);
                }
            }
            
            endTimer();
            const summaryMessage = `链接插入处理完毕。共检查 ${processedFileCount} 个文件，更新了 ${updatedFileCount} 个文件。`;
            this.log('info', summaryMessage);
            new Notice(`✅ ${summaryMessage}`, 5000);
            
            return {
                success: true,
                data: { processedFiles: processedFileCount, updatedFiles: updatedFileCount }
            };
            
        } catch (error: any) {
            endTimer();
            const processingError = this.createProcessingError('UNKNOWN',
                '插入建议链接时发生错误',
                error instanceof Error ? error.message : String(error));
            this.handleError(processingError);
            return { success: false, error: processingError };
        }
    }

    // 新增：从JSON文件读取AI评分数据的文件处理逻辑
    private async processFileForLinkInsertionFromJSON(
        file: TFile, 
        targetFolderPaths: string[], 
        shouldProcessAll: boolean,
        aiScoresData: any
    ): Promise<{processed: boolean, updated: boolean} | null> {
        try {
            // 检查文件是否在目标文件夹中
            let inTargetFolder = shouldProcessAll;
            if (!shouldProcessAll) {
                for (const targetFolder of targetFolderPaths) {
                    const normalizedTarget = targetFolder.endsWith('/') ? targetFolder.slice(0, -1) : targetFolder;
                    const filePathNormalized = file.path;
                    if (filePathNormalized.startsWith(normalizedTarget + '/') || filePathNormalized === normalizedTarget) {
                        inTargetFolder = true; 
                        break;
                    }
                }
            }
            
            if (!inTargetFolder) {
                return null;
            }

            // 从JSON数据中获取该文件的AI评分候选
            const candidates = this.getAICandidatesFromJSON(file.path, aiScoresData);
            if (!candidates || candidates.length === 0) {
                return { processed: true, updated: false };
            }

            // 使用缓存读取文件内容
            let fileContent = await this.getCachedFileContent(file);
            const originalFileContentForComparison = fileContent; 

            // 分离frontmatter和正文
            const fmRegex = /^---\s*$\n([\s\S]*?)\n^---\s*$\n?/m;
            const fmMatch = fileContent.match(fmRegex);
            let bodyContent = fileContent;
            let frontmatterPart = '';

            if (fmMatch) {
                frontmatterPart = fmMatch[0];
                bodyContent = fileContent.substring(frontmatterPart.length);
            }
            
            // 检查哈希边界标记，若没有则添加
            const boundaryMarker = HASH_BOUNDARY_MARKER;
            let boundaryIndexInBody = bodyContent.indexOf(boundaryMarker);
            
            // 如果没有哈希边界标记，则在正文末尾添加
            if (boundaryIndexInBody === -1) {
                // 找到最后一个非空行
                const lines = bodyContent.split(/\r?\n/);
                let lastNonEmptyLineIndex = -1;
                
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (lines[i].trim().length > 0) {
                        lastNonEmptyLineIndex = i;
                        break;
                    }
                }
                
                if (lastNonEmptyLineIndex !== -1) {
                    // 在最后一个非空行后插入哈希边界标记
                    lines.splice(lastNonEmptyLineIndex + 1, 0, boundaryMarker);
                    bodyContent = lines.join('\n');
                    boundaryIndexInBody = bodyContent.indexOf(boundaryMarker);
                    this.log('info', `在 ${file.path} 添加了哈希边界标记`);
                } else {
                    this.log('warn', `${file.path} 没有任何非空行，跳过`);
                    return { processed: false, updated: false };
                }
            }

            // 处理链接插入
            const linksSection = this.generateLinksSection(candidates);
            const updatedBodyContent = this.insertLinksIntoBody(bodyContent, linksSection, boundaryMarker);
            
            const finalContent = frontmatterPart + updatedBodyContent;
            
            // 检查内容是否有变化
            if (finalContent !== originalFileContentForComparison) {
                await this.app.vault.modify(file, finalContent);
                this.log('info', `更新了 ${file.path} 的建议链接`);
                return { processed: true, updated: true };
            } else {
                return { processed: true, updated: false };
            }
            
        } catch (error: any) {
            this.log('error', `处理文件 ${file.path} 时发生错误`, error);
            return null;
        }
    }

    // 从JSON数据中获取AI评分候选
    private getAICandidatesFromJSON(filePath: string, aiScoresData: any): any[] {
        try {
            const aiScores = aiScoresData?.ai_scores || {};
            const candidates: any[] = [];
            
            // 遍历AI评分数据，找到以当前文件为源的评分
            for (const [key, scoreEntry] of Object.entries(aiScores)) {
                if (typeof scoreEntry === 'object' && scoreEntry !== null) {
                    const entry = scoreEntry as any;
                    if (entry.source_path === filePath && entry.ai_score >= this.settings.minAiScoreForLinkInsertion) {
                        candidates.push({
                            targetPath: entry.target_path,
                            aiScore: entry.ai_score,
                            jinaScore: entry.jina_similarity
                        });
                    }
                }
            }
            
            // 按AI评分排序，取前N个
            candidates.sort((a: any, b: any) => (b.aiScore || 0) - (a.aiScore || 0));
            return candidates.slice(0, this.settings.maxLinksToInsertPerNote);
            
        } catch (error: any) {
            this.log('error', `从JSON获取AI候选时发生错误`, error);
            return [];
        }
    }

    // 生成链接部分的内容
    private generateLinksSection(candidates: any[]): string {
        if (!candidates || candidates.length === 0) {
            return '';
        }

        const linksToInsert: string[] = [];
        
        for (const cand of candidates) {
            if (cand && typeof cand === 'object' && cand.targetPath) {
                const targetTFile = this.app.vault.getAbstractFileByPath(cand.targetPath);
                if (targetTFile instanceof TFile) {
                    const linkText = this.app.metadataCache.fileToLinktext(targetTFile, '', true);
                    linksToInsert.push(`- [[${linkText}]]`);
                } else {
                    console.warn(`JinaLinker: 目标文件 ${cand.targetPath} 未找到。跳过此链接。`);
                }
            }
        }

        if (linksToInsert.length === 0) {
            return '';
        }

        const linksMarkdown = linksToInsert.join('\n');
        return `\n${SUGGESTED_LINKS_TITLE}\n${LINKS_START_MARKER}\n${linksMarkdown}\n${LINKS_END_MARKER}`;
    }

    // 将链接部分插入到正文中
    private insertLinksIntoBody(bodyContent: string, linksSection: string, boundaryMarker: string): string {
        // 找到哈希边界标记的位置
        const boundaryIndex = bodyContent.indexOf(boundaryMarker);
        if (boundaryIndex === -1) {
            return bodyContent;
        }

        // 分离哈希边界标记前后的内容
        const contentBeforeBoundary = bodyContent.substring(0, boundaryIndex);
        let contentAfterBoundary = bodyContent.substring(boundaryIndex + boundaryMarker.length);

        // 删除现有的建议链接部分

        // 正则表达式匹配整个建议链接部分
        const linkSectionRegex = new RegExp(`${escapeRegExp(SUGGESTED_LINKS_TITLE)}\\s*${escapeRegExp(LINKS_START_MARKER)}[\\s\\S]*?${escapeRegExp(LINKS_END_MARKER)}`, "g");
        
        // 清除现有的链接部分
        contentAfterBoundary = contentAfterBoundary.replace(linkSectionRegex, '').trim();

        // 构建最终内容
        let finalContent = contentBeforeBoundary + boundaryMarker;

        // 添加新的链接部分（如果有）
        if (linksSection) {
            finalContent += linksSection;
        }

        // 添加剩余内容
        if (contentAfterBoundary.length > 0) {
            finalContent += `\n\n${contentAfterBoundary}`;
        }

        return finalContent;
    }

    // 已删除：processFileForLinkInsertion() 函数，因为现在完全使用JSON文件存储AI评分数据
}

// Helper function for regex escaping
function escapeRegExp(string: string): string {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

class JinaLinkerSettingTab extends PluginSettingTab {
    plugin: JinaLinkerPlugin;

    constructor(app: App, plugin: JinaLinkerPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();
        containerEl.createEl('h2', { text: 'Jina AI Linker 插件设置', cls: 'jina-settings-header' });

        // API 密钥设置部分
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">基本设置</div>';

        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('Python 解释器路径')
            .setDesc('Python 可执行文件的命令或完整路径 (例如：python, python3, /usr/bin/python, C:\\Python39\\python.exe)')
            .addText(text => text
                .setPlaceholder(DEFAULT_SETTINGS.pythonPath)
                .setValue(this.plugin.settings.pythonPath)
                .onChange(async (value) => {
                    this.plugin.settings.pythonPath = value.trim() || DEFAULT_SETTINGS.pythonPath;
                    await this.plugin.saveSettings();
                }));

        // API 密钥设置部分
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">API 密钥</div>';

        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('Jina API 密钥')
            .setDesc('您的 Jina AI API 密钥，用于生成文本嵌入向量。')
            .addText(text => {
                text.inputEl.type = 'password';
                text.setPlaceholder('输入 Jina API 密钥')
                    .setValue(this.plugin.settings.jinaApiKey)
                    .onChange(async (value) => {
                        this.plugin.settings.jinaApiKey = value;
                        await this.plugin.saveSettings();
                    });
            });

        // AI 模型配置部分
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">AI 智能评分配置</div>';

        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('AI 提供商')
            .setDesc('选择用于智能评分的 AI 提供商。')
            .addDropdown(dropdown => {
                dropdown.addOption('deepseek', 'DeepSeek');
                dropdown.addOption('openai', 'OpenAI');
                dropdown.addOption('claude', 'Claude (Anthropic)');
                dropdown.addOption('gemini', 'Gemini (Google)');
                dropdown.addOption('custom', '自定义');
                dropdown.setValue(this.plugin.settings.selectedAIProvider);
                dropdown.onChange(async (value: AIProvider) => {
                    this.plugin.settings.selectedAIProvider = value;
                    await this.plugin.saveSettings();
                    this.display(); // 重新渲染设置页面
                });
            });

        // 显示选中AI提供商的配置
        this.displayAIProviderSettings(containerEl);
        
        // Python 脚本处理参数
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">Python 脚本处理参数</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('排除的文件夹')
            .setDesc('Python 脚本处理时要排除的文件夹名称 (逗号分隔，不区分大小写)。')
            .addText(text => text
                .setPlaceholder('例如：.archive, Temp, 附件')
                .setValue(this.plugin.settings.excludedFolders)
                .onChange(async (value) => {
                    this.plugin.settings.excludedFolders = value; 
                    await this.plugin.saveSettings();
                })
            );
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('排除的文件模式')
            .setDesc('Python 脚本处理时要排除的文件名 Glob 模式 (逗号分隔)。')
            .addText(text => text
                .setPlaceholder('例如：*.excalidraw, draft-*.md, ZK_*')
                .setValue(this.plugin.settings.excludedFilesPatterns)
                .onChange(async (value) => {
                    this.plugin.settings.excludedFilesPatterns = value; 
                    await this.plugin.saveSettings();
                })
            );
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('Jina 相似度阈值')
            .setDesc('Jina 嵌入向量之间计算余弦相似度的最小阈值 (0.0 到 1.0)，低于此阈值的笔记对将不被视为候选链接。')
            .addText(text => text
                .setValue(this.plugin.settings.similarityThreshold.toString())
                .onChange(async (value) => { 
                    const num = parseFloat(value); 
                    if (!isNaN(num) && num >= 0 && num >= 0 && num <= 1) { // Fixed: Changed second num >= 0 to num <= 1
                        this.plugin.settings.similarityThreshold = num; 
                    } else {
                        new Notice("相似度阈值必须是 0.0 到 1.0 之间的数字。"); 
                    }
                    await this.plugin.saveSettings(); 
                })
            );
        
        // 高级模型与内容参数
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">高级模型与内容参数</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('Jina 模型名称')
            .setDesc('用于生成嵌入的 Jina 模型名称。')
            .addText(text => text
                .setPlaceholder(DEFAULT_SETTINGS.jinaModelName)
                .setValue(this.plugin.settings.jinaModelName)
                .onChange(async (value) => {
                    this.plugin.settings.jinaModelName = value.trim() || DEFAULT_SETTINGS.jinaModelName; 
                    await this.plugin.saveSettings();
                })
            );
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('Jina 嵌入最大字符数')
            .setDesc('传递给 Jina API 进行嵌入的文本内容的最大字符数。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxCharsForJina))
                .setValue(this.plugin.settings.maxCharsForJina.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxCharsForJina = parseInt(value) || DEFAULT_SETTINGS.maxCharsForJina; 
                    await this.plugin.saveSettings();
                })
            );
        
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('AI 评分内容最大长度')
            .setDesc('传递给 DeepSeek API 进行评分的每条笔记内容的最大字符数。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxContentLengthForAI))
                .setValue(this.plugin.settings.maxContentLengthForAI.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxContentLengthForAI = parseInt(value) || DEFAULT_SETTINGS.maxContentLengthForAI; 
                    await this.plugin.saveSettings();
                })
            );
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('每源笔记送交 AI 评分的最大候选链接数')
            .setDesc('对于每个源笔记，按 Jina 相似度从高到低排序后，最多选择多少个候选链接发送给 AI进行评分。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxCandidatesPerSourceForAIScoring))
                .setValue(this.plugin.settings.maxCandidatesPerSourceForAIScoring.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxCandidatesPerSourceForAIScoring = parseInt(value) || DEFAULT_SETTINGS.maxCandidatesPerSourceForAIScoring; 
                    await this.plugin.saveSettings();
                })
            );
        
        // 链接插入与哈希设置
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">链接插入设置</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('链接插入的最小 AI 分数')
            .setDesc('只有 AI 评分大于或等于此值的候选链接才会被插入到笔记中。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.minAiScoreForLinkInsertion))
                .setValue(this.plugin.settings.minAiScoreForLinkInsertion.toString())
                .onChange(async (value) => {
                    this.plugin.settings.minAiScoreForLinkInsertion = parseInt(value) || DEFAULT_SETTINGS.minAiScoreForLinkInsertion; 
                    await this.plugin.saveSettings();
                })
            );
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('每个笔记最多插入的链接数')
            .setDesc('对于每个笔记，最多插入多少条符合条件的建议链接。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxLinksToInsertPerNote))
                .setValue(this.plugin.settings.maxLinksToInsertPerNote.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxLinksToInsertPerNote = parseInt(value) || DEFAULT_SETTINGS.maxLinksToInsertPerNote; 
                    await this.plugin.saveSettings();
                })
            );
            
        // 性能和调试设置
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">性能和调试</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('清理文件缓存')
            .setDesc('清理插件的文件内容缓存以释放内存。')
            .addButton(button => button
                .setButtonText('清理缓存')
                .onClick(() => {
                    this.plugin.clearCache();
                }));
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('显示性能统计')
            .setDesc('在控制台显示插件的性能统计信息。')
            .addButton(button => button
                .setButtonText('显示统计')
                .onClick(() => {
                    const metrics = this.plugin.performanceMonitor.getMetricsSummary();
                    console.log('Jina AI Linker 性能统计:', metrics);
                    new Notice('性能统计已输出到控制台', 3000);
                }));
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('取消当前操作')
            .setDesc('取消正在进行的Python脚本或链接插入操作。')
            .addButton(button => button
                .setButtonText('取消操作')
                .setClass('mod-warning')
                .onClick(() => {
                    this.plugin.cancelCurrentOperation();
                }));
        
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div style="margin-top: 2em; color: var(--text-muted); font-size: 0.9em;">Jina AI Linker v' + this.plugin.manifest.version + '</div>';
    }

    displayAIProviderSettings(containerEl: HTMLElement): void {
        const selectedProvider = this.plugin.settings.selectedAIProvider;
        const aiConfig = this.plugin.settings.aiModels[selectedProvider];

        // AI 提供商启用状态
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName(`启用 ${this.getProviderDisplayName(selectedProvider)}`)
            .setDesc(`是否启用 ${this.getProviderDisplayName(selectedProvider)} 进行智能评分。`)
            .addToggle(toggle => toggle
                .setValue(aiConfig.enabled)
                .onChange(async (value) => {
                    this.plugin.settings.aiModels[selectedProvider].enabled = value;
                    await this.plugin.saveSettings();
                    this.display(); // 重新渲染
                }));

        if (aiConfig.enabled) {
            // API URL 设置
            new Setting(containerEl)
                .setClass('jina-settings-block')
                .setName('API URL')
                .setDesc(`${this.getProviderDisplayName(selectedProvider)} 的 API 端点地址。`)
                .addText(text => text
                    .setPlaceholder(this.getDefaultApiUrl(selectedProvider))
                    .setValue(aiConfig.apiUrl)
                    .onChange(async (value) => {
                        this.plugin.settings.aiModels[selectedProvider].apiUrl = value.trim() || this.getDefaultApiUrl(selectedProvider);
                        await this.plugin.saveSettings();
                    }));

            // API Key 设置
            new Setting(containerEl)
                .setClass('jina-settings-block')
                .setName('API 密钥')
                .setDesc(`您的 ${this.getProviderDisplayName(selectedProvider)} API 密钥。`)
                .addText(text => {
                    text.inputEl.type = 'password';
                    text.setPlaceholder(`输入 ${this.getProviderDisplayName(selectedProvider)} API 密钥`)
                        .setValue(aiConfig.apiKey)
                        .onChange(async (value) => {
                            this.plugin.settings.aiModels[selectedProvider].apiKey = value;
                            await this.plugin.saveSettings();
                        });
                });

            // 模型名称设置
            new Setting(containerEl)
                .setClass('jina-settings-block')
                .setName('模型名称')
                .setDesc(`${this.getProviderDisplayName(selectedProvider)} 的模型名称。`)
                .addText(text => text
                    .setPlaceholder(this.getDefaultModelName(selectedProvider))
                    .setValue(aiConfig.modelName)
                    .onChange(async (value) => {
                        this.plugin.settings.aiModels[selectedProvider].modelName = value.trim() || this.getDefaultModelName(selectedProvider);
                        await this.plugin.saveSettings();
                    }));

            // 显示常用模型建议
            this.displayModelSuggestions(containerEl, selectedProvider);
        }
    }

    getProviderDisplayName(provider: AIProvider): string {
        const names = {
            'deepseek': 'DeepSeek',
            'openai': 'OpenAI',
            'claude': 'Claude',
            'gemini': 'Gemini',
            'custom': '自定义'
        };
        return names[provider] || provider;
    }

    getDefaultApiUrl(provider: AIProvider): string {
        return DEFAULT_AI_MODELS[provider].apiUrl;
    }

    getDefaultModelName(provider: AIProvider): string {
        return DEFAULT_AI_MODELS[provider].modelName;
    }

    displayModelSuggestions(containerEl: HTMLElement, provider: AIProvider): void {
        const suggestions = this.getModelSuggestions(provider);
        if (suggestions.length === 0) return;

        const suggestionEl = containerEl.createEl('div', { cls: 'jina-model-suggestions' });
        suggestionEl.createEl('div', { 
            text: '常用模型：', 
            cls: 'jina-suggestion-title' 
        });
        
        const buttonContainer = suggestionEl.createEl('div', { cls: 'jina-suggestion-buttons' });
        
        suggestions.forEach(model => {
            const button = buttonContainer.createEl('button', {
                text: model,
                cls: 'jina-suggestion-button'
            });
            button.addEventListener('click', async () => {
                this.plugin.settings.aiModels[provider].modelName = model;
                await this.plugin.saveSettings();
                this.display();
            });
        });

        // 添加样式
        const styleEl = containerEl.createEl('style');
        styleEl.textContent = `
            .jina-model-suggestions {
                margin-top: 8px;
                padding: 12px;
                background-color: var(--background-secondary);
                border-radius: 6px;
            }
            .jina-suggestion-title {
                font-size: 12px;
                color: var(--text-muted);
                margin-bottom: 8px;
            }
            .jina-suggestion-buttons {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
            }
            .jina-suggestion-button {
                padding: 4px 8px;
                font-size: 11px;
                background-color: var(--interactive-normal);
                border: 1px solid var(--background-modifier-border);
                border-radius: 4px;
                cursor: pointer;
                color: var(--text-normal);
            }
            .jina-suggestion-button:hover {
                background-color: var(--interactive-hover);
            }
        `;
    }

    getModelSuggestions(provider: AIProvider): string[] {
        const suggestions = {
            'deepseek': ['deepseek-chat', 'deepseek-coder'],
            'openai': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
            'claude': ['claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307', 'claude-3-sonnet-20240229'],
            'gemini': ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.0-pro'],
            'custom': []
        };
        return suggestions[provider] || [];
    }
}
