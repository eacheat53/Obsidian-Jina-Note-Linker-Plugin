import { App, Notice, Plugin, PluginSettingTab, Setting, TFolder, Modal, Editor, MarkdownView, TFile, normalizePath, Menu, SuggestModal, FuzzySuggestModal, FuzzyMatch } from 'obsidian';
import { spawn } from 'child_process';
import * as path from 'path'; // Node.js path module
import * as crypto from 'crypto'; // Node.js crypto module for hashing

// --- 内部常量 ---
const AI_JUDGED_CANDIDATES_FM_KEY = "ai_judged_candidates"; // 固定键名
// 新增：这两个常量用于保存原来的设置默认值，但不作为用户可配置项
const DEFAULT_SCRIPT_PATH = '';
const DEFAULT_OUTPUT_DIR_IN_VAULT = '.Jina-AI-Linker-Output';
// 新增：将哈希边界标记设为内置常量
const HASH_BOUNDARY_MARKER = '<!-- HASH_BOUNDARY -->';

// Interface for plugin settings
interface JinaLinkerSettings {
    pythonPath: string;
    // 以下两个字段不再向用户展示，而是使用默认值
    jinaApiKey: string;
    deepseekApiKey: string;
    similarityThreshold: number;
    excludedFolders: string;
    excludedFilesPatterns: string;
    jinaModelName: string;
    maxCharsForJina: number;
    deepseekModelName: string;
    maxContentLengthForAI: number;
    maxCandidatesPerSourceForAIScoring: number;
    minAiScoreForLinkInsertion: number;
    maxLinksToInsertPerNote: number;
}

// Default settings
const DEFAULT_SETTINGS: JinaLinkerSettings = {
    pythonPath: 'python', 
    jinaApiKey: '',
    deepseekApiKey: '',
    similarityThreshold: 0.70,
    excludedFolders: '.obsidian, Scripts, assets, Excalidraw, .trash, Python-Templater-Plugin-Output',
    excludedFilesPatterns: '*excalidraw*, template*.md, *.kanban.md, ^moc$, ^index$',
    jinaModelName: 'jina-embeddings-v3',
    maxCharsForJina: 8000,
    deepseekModelName: 'deepseek-chat',
    maxContentLengthForAI: 5000,
    maxCandidatesPerSourceForAIScoring: 20,
    minAiScoreForLinkInsertion: 6,
    maxLinksToInsertPerNote: 10,
};

// Constants for the link insertion part
const SUGGESTED_LINKS_TITLE = "## 建议链接";
const LINKS_START_MARKER = "<!-- LINKS_START -->";
const LINKS_END_MARKER = "<!-- LINKS_END -->";
const EMBEDDINGS_FILE_NAME = "jina_embeddings.json";

// Interface for dynamic options from Modal
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

    async onload() {
        await this.loadSettings();

        this.addCommand({
            id: 'run-jina-linker-processing-and-insert-links',
            name: '处理笔记并插入建议链接',
            callback: () => {
                new RunPluginModal(this.app, this, async (options) => {
                    const pythonSuccess = await this.runPythonScript(options.scanPath, options.scoringMode);
                    if (pythonSuccess) {
                        new Notice('Python 脚本执行完毕。现在尝试插入建议链接...', 5000);
                        await this.insertAISuggestedLinksIntoNotes(options.scanPath);
                    } else {
                        new Notice('Python 脚本执行失败。链接插入步骤将被跳过。', 0);
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
                            if (pythonSuccess) {
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
                                console.error(`JinaLinker: 文件 "${normalizedFilePath}" 未找到或不是一个有效文件，无法计算哈希。`);
                                return;
                            }
                            
                            const hash = await this.calculateNoteContentHashForFile(tFile);
                            if (hash) {
                                new Notice(`文件 "${filePath}" 的内容哈希值: ${hash}`);
                                console.log(`JinaLinker: 文件 "${filePath}" 的内容哈希值 (SHA256): ${hash}`);
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
            
            menu.showAtMouseEvent(evt);
        });

        this.addCommand({
            id: 'calculate-note-content-hash',
            name: '计算笔记内容哈希值 (诊断用)',
            callback: () => {
                new CalculateHashModal(this.app, this, async (filePath) => {
                    const normalizedFilePath = normalizePath(filePath);
                    const tFile = this.app.vault.getAbstractFileByPath(normalizedFilePath);

                    if (!(tFile instanceof TFile)) {
                        new Notice(`错误：文件 "${normalizedFilePath}" 未找到或不是一个有效文件。`);
                        console.error(`JinaLinker: 文件 "${normalizedFilePath}" 未找到或不是一个有效文件，无法计算哈希。`);
                        return;
                    }
                    
                    const hash = await this.calculateNoteContentHashForFile(tFile);
                    if (hash) {
                        new Notice(`文件 "${filePath}" 的内容哈希值: ${hash}`);
                        console.log(`JinaLinker: 文件 "${filePath}" 的内容哈希值 (SHA256): ${hash}`);
                    }
                }).open();
            }
        });

        this.addCommand({
            id: 'update-hashes-in-embeddings-file',
            name: '更新嵌入数据中的笔记哈希值',
            callback: () => {
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


        this.addSettingTab(new JinaLinkerSettingTab(this.app, this));
        new Notice('Jina AI Linker 插件已加载。');
    }

    onunload() {
        new Notice('Jina AI Linker 插件已卸载。');
    }

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings() {
        await this.saveData(this.settings);
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
                console.warn(`JinaLinker: 文件 "${file.path}" 中未找到哈希边界标记 (在 frontmatter 之后)。`);
                return null;
            }
            
            const hasher = crypto.createHash('sha256');
            hasher.update(contentForHashing, 'utf-8');
            return hasher.digest('hex');

        } catch (error) {
            new Notice(`计算文件 "${file.path}" 哈希时发生错误: ${error.message}`);
            console.error(`JinaLinker: 计算文件 "${file.path}" 哈希时发生错误:`, error);
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
                console.error(`JinaLinker: 嵌入文件 "${embeddingsFilePath}" 未找到。`);
                return;
            }
            const rawData = await this.app.vault.adapter.read(embeddingsFilePath);
            embeddingsData = JSON.parse(rawData);
            if (!embeddingsData.files || typeof embeddingsData.files !== 'object') {
                throw new Error("嵌入文件结构不正确，缺少 'files' 对象。");
            }
        } catch (error) {
            new Notice(`读取或解析嵌入文件 "${embeddingsFilePath}" 失败: ${error.message}`);
            console.error(`JinaLinker: 读取或解析嵌入文件 "${embeddingsFilePath}" 失败:`, error);
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
                console.warn(`JinaLinker: 路径 "${normalizedRelPathKey}" 不存在，跳过。`);
                continue;
            }
            
            // 如果是文件夹，递归获取所有Markdown文件
            if (abstractFile instanceof TFolder) {
                console.log(`JinaLinker: 处理文件夹 "${normalizedRelPathKey}"...`);
                
                // 递归获取该文件夹下的所有Markdown文件
                const folderFiles = this.getMarkdownFilesInFolder(abstractFile);
                console.log(`JinaLinker: 在文件夹 "${normalizedRelPathKey}" 中找到 ${folderFiles.length} 个Markdown文件。`);
                
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
                console.warn(`JinaLinker: 路径 "${normalizedRelPathKey}" 不是Markdown文件或文件夹，跳过。`);
            }
        }
        
        // 去重，避免重复处理同一文件
        filesToProcess = Array.from(new Set(filesToProcess));
        
        new Notice(`共找到 ${filesToProcess.length} 个Markdown文件需要处理...`);
        console.log(`JinaLinker: 共找到 ${filesToProcess.length} 个Markdown文件需要处理。`);
        
        let updatedJsonCount = 0;
        let notFoundInJsonCount = 0;
        let hashCalculationFailedCount = 0;
        let noChangeCount = 0;
        let updatedFrontmatterCount = 0;
        let processedCount = 0;

        // 处理每个文件
        for (const tFile of filesToProcess) {
            processedCount++;
            const normalizedFilePath = tFile.path;
            console.log(`JinaLinker: 处理文件 (${processedCount}/${filesToProcess.length}): ${normalizedFilePath}`);

            const newHash = await this.calculateNoteContentHashForFile(tFile);
            if (!newHash) {
                console.warn(`JinaLinker: 未能为文件 "${normalizedFilePath}" 计算新哈希，跳过。`);
                hashCalculationFailedCount++;
                continue;
            }
            
            // 更新嵌入JSON中的哈希值
            let jsonUpdated = false;
            if (embeddingsData.files.hasOwnProperty(normalizedFilePath)) {
                const entry = embeddingsData.files[normalizedFilePath];
                const oldHash = entry.hash;
                if (oldHash === newHash) {
                    console.log(`JinaLinker: 文件 "${normalizedFilePath}" 在JSON中的哈希值 (${newHash ? newHash.substring(0,8) : 'N/A'}...) 已是最新。`);
                } else {
                    console.log(`JinaLinker: 更新JSON中文件 "${normalizedFilePath}" 的哈希: ${oldHash ? oldHash.substring(0,8) : 'N/A'}... -> ${newHash ? newHash.substring(0,8) : 'N/A'}...`);
                    entry.hash = newHash;
                    entry.last_hash_updated_at = new Date().toISOString();
                    updatedJsonCount++;
                    jsonUpdated = true;
                }
            } else {
                console.warn(`JinaLinker: 在嵌入JSON中未找到文件 "${normalizedFilePath}" 的条目。`);
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
                            const oldHashDisplay = oldHash ? oldHash.substring(0,8) : 'N/A';
                            const newHashDisplay = newHash ? newHash.substring(0,8) : 'N/A';
                            console.log(`JinaLinker: 更新文件 "${normalizedFilePath}" frontmatter中的哈希: ${oldHashDisplay}... -> ${newHashDisplay}...`);
                        } else {
                            console.log(`JinaLinker: 文件 "${normalizedFilePath}" frontmatter中的哈希值已是最新。`);
                        }
                    } else {
                        // 无jina_hash，添加到frontmatter末尾
                        const newFrontmatter = frontmatterContent + `\njina_hash: ${newHash}`;
                        newContent = fileContent.replace(
                            fmMatch[0], 
                            `---\n${newFrontmatter}\n---\n`
                        );
                        frontmatterUpdated = true;
                        console.log(`JinaLinker: 在文件 "${normalizedFilePath}" frontmatter中添加哈希值。`);
                    }
                } else {
                    // 无frontmatter，创建包含jina_hash的frontmatter
                    newContent = `---\njina_hash: ${newHash}\n---\n\n${fileContent}`;
                    frontmatterUpdated = true;
                    console.log(`JinaLinker: 为文件 "${normalizedFilePath}" 创建包含哈希值的frontmatter。`);
                }
                
                // 如果需要更新，保存文件
                if (frontmatterUpdated && newContent) {
                    await this.app.vault.modify(tFile, newContent);
                    updatedFrontmatterCount++;
                } else {
                    noChangeCount++;
                }
                
            } catch (error) {
                console.error(`JinaLinker: 更新文件 "${normalizedFilePath}" frontmatter时出错:`, error);
                new Notice(`更新文件 "${normalizedFilePath}" frontmatter时出错: ${error instanceof Error ? error.message : String(error)}`);
            }
        }

        // 保存更新后的嵌入文件
        if (updatedJsonCount > 0) {
            try {
                await this.app.vault.adapter.write(embeddingsFilePath, JSON.stringify(embeddingsData, null, 4));
                console.log(`JinaLinker: 嵌入文件 "${embeddingsFilePath}" 已更新。`);
            } catch (error) {
                new Notice(`写入更新后的嵌入文件 "${embeddingsFilePath}" 时发生错误: ${error instanceof Error ? error.message : String(error)}`);
                console.error(`JinaLinker: 写入更新后的嵌入文件 "${embeddingsFilePath}" 时发生错误:`, error);
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
        console.log(`JinaLinker: ${summaryMsg}`);
        
        let detailedSummary = `哈希更新摘要: ${updatedJsonCount} 个JSON已更新, ${updatedFrontmatterCount} 个frontmatter已更新, ${noChangeCount} 个无需更改, ${notFoundInJsonCount} 个在JSON中未找到, ${hashCalculationFailedCount} 个哈希计算失败。`;
        console.log(`JinaLinker: ${detailedSummary}`);
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

    async runPythonScript(scanPathFromModal: string, scoringModeFromModal: "force" | "smart" | "skip"): Promise<boolean> {
        return new Promise(async (resolve) => {
            let scriptToExecutePath = '';
            const vaultBasePath = (this.app.vault.adapter as any).getBasePath();
            const bundledScriptName = 'jina_obsidian_processor.py';
    
            // 默认使用插件自带脚本，不再考虑用户设置的scriptPath
            if (this.manifest.dir) {
                scriptToExecutePath = path.join(vaultBasePath, this.manifest.dir, bundledScriptName);
            } else {
                new Notice('JinaLinker 错误: Python 脚本路径无法确定。', 0);
                console.error('JinaLinker: Python 脚本路径设置错误。');
                resolve(false);
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
                    console.log(`JinaLinker: 已创建JSON输出目录: ${outputDirInVault}`);
                }
            } catch (error) {
                console.error('JinaLinker: 创建输出目录时发生错误:', error);
                new Notice(`JinaLinker: 创建输出目录 "${outputDirInVault}" 失败。请检查权限。`, 0);
                resolve(false);
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
            
            if (this.settings.deepseekApiKey) {
                args.push('--deepseek_api_key', this.settings.deepseekApiKey);
                args.push('--deepseek_model_name', this.settings.deepseekModelName);
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
            
            new Notice('JinaLinker: 开始执行 Python 脚本...', 5000);
            console.log('JinaLinker: 正在启动 Python 脚本。\n命令:', this.settings.pythonPath, '\n参数:', JSON.stringify(args, null, 2));
        
            const pythonProcess = spawn(this.settings.pythonPath, args, { stdio: ['pipe', 'pipe', 'pipe'] });
        
        let scriptOutput = '';
        let scriptError = '';

        pythonProcess.stdout.on('data', (data) => {
            const outputChunk = data.toString();
            scriptOutput += outputChunk;
            console.log(`JinaLinker Python (stdout): ${outputChunk.trim()}`);
        });

        pythonProcess.stderr.on('data', (data) => {
            const errorChunk = data.toString();
            scriptError += errorChunk;
            console.error(`JinaLinker Python (stderr): ${errorChunk.trim()}`);
        });

        pythonProcess.on('close', (code) => {
                console.log(`JinaLinker: Python 脚本执行完毕，退出码 ${code}.`);
            if (code === 0) {
                    resolve(true);
                } else {
                    new Notice('JinaLinker: Python 脚本执行失败。详情请查看开发者控制台。', 0);
                    resolve(false);
                }
            });

            pythonProcess.on('error', (err) => {
                console.error('JinaLinker: 启动 Python 脚本失败:', err);
                new Notice(`JinaLinker: 启动 Python 脚本失败: ${err.message}。请检查 Python 路径是否正确。`, 0);
                resolve(false);
            });
        });
    }

    async insertAISuggestedLinksIntoNotes(targetFoldersOption: string) {
        try {
            // 使用默认输出目录，而不是用户设置的outputDirInVault
            const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
            const embeddingsFilePath = normalizePath(path.join(outputDirInVault, EMBEDDINGS_FILE_NAME));

            const fileExists = await this.app.vault.adapter.exists(embeddingsFilePath);
            if (!fileExists) {
                new Notice(`错误: 嵌入文件 "${embeddingsFilePath}" 未找到。无法插入链接。`, 0);
                console.error(`JinaLinker: 嵌入文件 "${embeddingsFilePath}" 未找到。无法插入链接。`);
                return;
            }
            
            const rawEmbeddingsData = await this.app.vault.adapter.read(embeddingsFilePath);
            const embeddingsData = JSON.parse(rawEmbeddingsData);

            console.log("JinaLinker: 开始 'insertAISuggestedLinksIntoNotes' 流程。");
            new Notice('正在处理笔记以插入/更新建议链接 (在 HASH_BOUNDARY 之后)...', 3000);
            const allMarkdownFiles = this.app.vault.getMarkdownFiles();
            let processedFileCount = 0;
            let updatedFileCount = 0;

            const targetFolderPaths = targetFoldersOption.split(',').map(p => p.trim()).filter(p => p);
            const shouldProcessAll = targetFolderPaths.length === 0 || (targetFolderPaths.length === 1 && targetFolderPaths[0] === '/');
            console.log(`JinaLinker: 将为 ${allMarkdownFiles.length} 个 Markdown 文件执行链接插入 (遵循目标文件夹选项: '${targetFoldersOption || '仓库根目录'}').`);

            for (const file of allMarkdownFiles) {
                let inTargetFolder = shouldProcessAll;
                if (!shouldProcessAll) {
                    for (const targetFolder of targetFolderPaths) {
                        const normalizedTarget = targetFolder.endsWith('/') ? targetFolder.slice(0, -1) : targetFolder;
                        const filePathNormalized = file.path;
                        if (filePathNormalized.startsWith(normalizedTarget + '/') || filePathNormalized === normalizedTarget) {
                            inTargetFolder = true; break;
                        }
                    }
                }
                if (!inTargetFolder) {
                    continue;
                }
                processedFileCount++;
                
                try {
                    // 读取文件内容
                    let fileContent = await this.app.vault.read(file);
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
                            console.log(`JinaLinker: 在 ${file.path} 添加了哈希边界标记。`);
                        } else {
                            console.warn(`JinaLinker: ${file.path} 没有任何非空行，跳过。`);
                            continue;
                        }
                    }
                    
                    // 分离哈希边界标记前后的内容
                    const contentBeforeBoundary = bodyContent.substring(0, boundaryIndexInBody);
                    let contentAfterBoundary = bodyContent.substring(boundaryIndexInBody + boundaryMarker.length);
                    
                    // 删除现有的所有建议链接部分（可能有多个）
                    const sectionTitle = SUGGESTED_LINKS_TITLE;
                    const startMarker = LINKS_START_MARKER;
                    const endMarker = LINKS_END_MARKER;
                    
                    // 正则表达式匹配整个建议链接部分，包括可能包含的div标签
                    const linkSectionRegexWithDiv = new RegExp(`<div[^>]*>\\s*${escapeRegExp(sectionTitle)}\\s*${escapeRegExp(startMarker)}[\\s\\S]*?${escapeRegExp(endMarker)}\\s*<\\/div>`, "g");
                    const linkSectionRegexSimple = new RegExp(`${escapeRegExp(sectionTitle)}\\s*${escapeRegExp(startMarker)}[\\s\\S]*?${escapeRegExp(endMarker)}`, "g");
                    
                    // 清除所有匹配的链接部分
                    contentAfterBoundary = contentAfterBoundary
                        .replace(linkSectionRegexWithDiv, '')
                        .replace(linkSectionRegexSimple, '');
                    
                    // 获取候选链接
                    const fileCache = this.app.metadataCache.getFileCache(file);
                    const frontmatter = fileCache?.frontmatter;
                    const candidates: any[] = (frontmatter && frontmatter[AI_JUDGED_CANDIDATES_FM_KEY] && Array.isArray(frontmatter[AI_JUDGED_CANDIDATES_FM_KEY])) ? frontmatter[AI_JUDGED_CANDIDATES_FM_KEY] : [];
                    const linksToInsert: string[] = [];

                    // 按分数排序
                    candidates.sort((a, b) => {
                        const scoreA = a.aiScore !== undefined ? a.aiScore : -Infinity;
                        const scoreB = b.aiScore !== undefined ? b.aiScore : -Infinity;
                        if (scoreB !== scoreA) return scoreB - scoreA;
                        return (b.jinaScore || 0) - (a.jinaScore || 0);
                    });

                    // 筛选要插入的链接
                    for (const cand of candidates) {
                        if (linksToInsert.length >= this.settings.maxLinksToInsertPerNote) break;
                        
                        if (cand && typeof cand === 'object' && cand.targetPath) {
                            if (cand.aiScore === undefined || cand.aiScore < this.settings.minAiScoreForLinkInsertion) {
                                continue; 
                            }
                            
                            const targetTFile = this.app.vault.getAbstractFileByPath(cand.targetPath);
                            if (targetTFile instanceof TFile) {
                                const linkText = this.app.metadataCache.fileToLinktext(targetTFile, file.path, true);
                                linksToInsert.push(`- [[${linkText}]]`);
                            } else {
                                console.warn(`JinaLinker: 目标文件 ${cand.targetPath} 在为 ${file.path} 生成链接时未找到。跳过此链接。`);
                            }
                        }
                    }

                    // 清理可能存在的多余空行
                    contentAfterBoundary = contentAfterBoundary.trim();
                    
                    // 构建最终内容
                    let finalContent = '';
                    
                    // 添加frontmatter
                    if (frontmatterPart) {
                        finalContent += frontmatterPart;
                    }
                    
                    // 添加正文和哈希边界标记
                    finalContent += contentBeforeBoundary + boundaryMarker;
                    
                    // 添加换行和建议链接部分（如果有链接）
                    if (linksToInsert.length > 0) {
                        const linksMarkdown = linksToInsert.join('\n');
                        finalContent += `\n${sectionTitle}\n${startMarker}\n${linksMarkdown}\n${endMarker}`;
                        
                        // 如果有剩余内容，添加到最后
                        if (contentAfterBoundary.length > 0) {
                            finalContent += `\n\n${contentAfterBoundary}`;
                        }
                    } else if (contentAfterBoundary.length > 0) {
                        // 如果没有链接但有其他内容，保留其他内容
                        finalContent += `\n\n${contentAfterBoundary}`;
                    }

                    // 检查内容是否有变化，有则更新文件
                    if (finalContent !== originalFileContentForComparison) {
                        await this.app.vault.modify(file, finalContent);
                        updatedFileCount++;
                        console.log(`JinaLinker: 已更新 ${file.path} 中的链接。`);
                    }

                } catch (error: any) {
                    console.error(`JinaLinker: 处理文件 ${file.path} 的链接插入时发生错误:`, error);
                    new Notice(`更新 ${file.path} 中的链接时出错: ${error.message}`);
                }
            }
            
            const summaryMessage = `链接插入处理完毕。共检查 ${processedFileCount} 个文件，更新了 ${updatedFileCount} 个文件。`;
            console.log(`JinaLinker: ${summaryMessage}`);
            new Notice(summaryMessage);
        } catch (error) {
            console.error(`JinaLinker: 处理笔记插入链接时发生错误:`, error);
            new Notice(`处理笔记插入链接时出错: ${error.message}`);
        }
    }
}

function escapeRegExp(string: string): string {
    return string.replace(/[.*+\-?^{}()|[\\]\\]/g, '\\$&'); 
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
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('DeepSeek API 密钥')
            .setDesc('您的 DeepSeek API 密钥，用于 AI 对候选链接进行智能评分 (可选)。')
            .addText(text => {
                text.inputEl.type = 'password';
                text.setPlaceholder('输入 DeepSeek API 密钥 (可选)')
                    .setValue(this.plugin.settings.deepseekApiKey)
                    .onChange(async (value) => {
                        this.plugin.settings.deepseekApiKey = value;
                        await this.plugin.saveSettings();
                    });
            });
        
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
                    if (!isNaN(num) && num >= 0 && num <= 1) {
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
            .setName('DeepSeek 模型名称')
            .setDesc('用于 AI 评分的 DeepSeek 模型名称。')
            .addText(text => text
                .setPlaceholder(DEFAULT_SETTINGS.deepseekModelName)
                .setValue(this.plugin.settings.deepseekModelName)
                .onChange(async (value) => {
                    this.plugin.settings.deepseekModelName = value.trim() || DEFAULT_SETTINGS.deepseekModelName; 
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
            
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div style="margin-top: 2em; color: var(--text-muted); font-size: 0.9em;">Jina AI Linker v' + this.plugin.manifest.version + '</div>';
    }
}
