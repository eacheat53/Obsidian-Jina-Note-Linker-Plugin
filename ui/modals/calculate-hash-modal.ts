import { App, Modal, Notice, Setting, TFile } from 'obsidian';
import { PathSuggestModal } from './path-suggest-modal';
// 使用 any 避免默认导入问题

export class CalculateHashModal extends Modal {
    plugin: any;
    onSubmit: (filePath: string) => void;
    filePath: string = '';
    inputEl: HTMLInputElement;
    
    // 用于存储自动完成的文件和文件夹路径
    allPaths: string[] = [];

    constructor(app: App, plugin: any, onSubmit: (filePath: string) => void) {
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
        this.inputEl.addEventListener('input', () => {
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