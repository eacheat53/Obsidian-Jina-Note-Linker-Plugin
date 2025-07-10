import { App, Modal, Setting, TFile, TFolder } from 'obsidian';
import { PathSuggestModal } from './path-suggest-modal';

export class AddAiTagsModal extends Modal {
    plugin: any;
    onSubmit: (filePaths: string, mode: 'smart' | 'force') => void; 
    filePaths: string = '';
    selectedMode: 'smart' | 'force' = 'smart';
    inputEl: HTMLTextAreaElement;
    
    // 用于存储自动完成的文件和文件夹路径
    allPaths: string[] = [];

    constructor(app: App, plugin: any, onSubmit: (filePaths: string, mode: 'smart' | 'force') => void) {
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
        contentEl.createEl('h2', { text: '批量插入 AI 标签' });

        // 生成模式
        new Setting(contentEl)
            .setName('生成模式')
            .setDesc('智能 = 仅为无标签新笔记生成；强制 = 总是重新生成')
            .addDropdown(dd => {
                dd.addOption('smart', '智能 (仅新笔记)');
                dd.addOption('force', '强制 (全部重生成)');
                dd.setValue(this.selectedMode);
                dd.onChange(v => (this.selectedMode = v as any));
            });

        // 目标文件/文件夹
        const pathSetting = new Setting(contentEl)
            .setName('目标文件/文件夹')
            .setDesc('多个路径用逗号分隔，"/" 表示整个仓库');

        pathSetting.addTextArea(ta => {
            ta.inputEl.rows = 3;
            ta.setPlaceholder('Notes/Note1.md, 留空处理所有文件');
            ta.setValue(this.filePaths);
            ta.onChange(v => {
                this.filePaths = v;
            });
            this.inputEl = ta.inputEl;
        });

        pathSetting.addButton(btn => {
            btn.setButtonText('浏览...');
            btn.onClick(() => {
                this.openPathSuggestModal('', selectedPath => {
                    if (selectedPath) {
                        if (this.filePaths && this.filePaths.trim() !== '' && !this.filePaths.trim().endsWith(',')) {
                            this.filePaths += ', ';
                        }
                        this.filePaths += selectedPath;
                        this.inputEl.value = this.filePaths;
                    }
                });
            });
        });

        // 底部按钮
        new Setting(contentEl)
            .addButton(btn => btn.setButtonText('取消').onClick(() => this.close()))
            .addButton(btn => btn
                .setButtonText('插入标签')
                .setCta()
                .onClick(() => {
                    this.close();
                    this.onSubmit(this.filePaths, this.selectedMode);
                }));
    }
    
    // 打开路径建议弹窗
    openPathSuggestModal(currentPath: string, callback: (selectedPath: string) => void) {
        const modal = new PathSuggestModal(this.app, this.allPaths, currentPath, callback);
        modal.open();
    }
    
    // 旧版 addStyles 样式已移除，改用 Setting 默认样式

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}