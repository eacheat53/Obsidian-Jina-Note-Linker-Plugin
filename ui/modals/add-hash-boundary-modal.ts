import { App, Modal, Notice, TFile, TFolder } from 'obsidian';
import { PathSuggestModal } from './path-suggest-modal';

export class AddHashBoundaryModal extends Modal {
    plugin: any;
    onSubmit: (filePaths: string) => void; 
    filePaths: string = '';
    inputEl: HTMLTextAreaElement;
    
    // 用于存储自动完成的文件和文件夹路径
    allPaths: string[] = [];

    constructor(app: App, plugin: any, onSubmit: (filePaths: string) => void) {
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
        descEl.setText('为指定的笔记文件添加 <!-- HASH_BOUNDARY --> 标记。请输入一个或多个仓库相对路径 (用英文逗号 "," 分隔)。请使用正斜杠 "/" 作为路径分隔符。(例如：文件夹1/笔记.md, 文件夹2/)。');
        
        // 创建路径输入控件容器
        const inputContainer = settingDiv.createDiv();
        inputContainer.addClass('jina-path-input-container');
        
        // 创建输入框
        this.inputEl = document.createElement('textarea');
        this.inputEl.addClass('jina-path-textarea');
        this.inputEl.setAttr('rows', '3');
        this.inputEl.setAttr('placeholder', 'Notes/Note1.md, 留空处理所有文件');
        this.inputEl.value = this.filePaths;
        inputContainer.appendChild(this.inputEl);
        
        // 创建路径选择按钮
        const browseButton = document.createElement('button');
        browseButton.setText('浏览...');
        browseButton.addClass('jina-browse-button');
        inputContainer.appendChild(browseButton);
        
        // 添加输入框变更事件
        this.inputEl.addEventListener('input', () => {
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