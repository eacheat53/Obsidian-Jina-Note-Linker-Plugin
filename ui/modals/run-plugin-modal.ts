import { App, Modal, Setting } from 'obsidian';
import { RunOptions } from '../../models/interfaces';
import { NotificationService } from '../../utils/notification-service';

export class RunPluginModal extends Modal {
    private plugin: any;
    private scanPath: string = '/';
    private scoringMode: "force" | "smart" | "skip" = "smart";
    private callbackFn?: (options: RunOptions) => void;
    private notificationService = NotificationService.getInstance();

    constructor(app: App, plugin: any, callbackFn?: (options: RunOptions) => void) {
        super(app);
        this.plugin = plugin;
        this.callbackFn = callbackFn;
        
        if (plugin?.settings?.defaultScanPath) {
            this.scanPath = plugin.settings.defaultScanPath;
        }
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.createEl('h2', { text: 'Jina AI Linker 运行选项' });

        new Setting(contentEl)
            .setName('扫描目标文件夹')
            .setDesc('输入要处理的文件夹路径，多个文件夹用逗号分隔。使用 "/" 表示整个仓库。')
            .addText(text => text
                .setPlaceholder('例如：/, 文件夹1, 文件夹2/子文件夹')
                .setValue(this.scanPath)
                .onChange(async (value) => {
                    this.scanPath = value.trim();
                })
            );
            
        new Setting(contentEl)
            .setName('AI 评分模式')
            .setDesc('控制如何处理已有评分的文档对。')
            .addDropdown(dropdown => dropdown
                .addOption('smart', '智能模式（仅评分新增和变更）')
                .addOption('force', '强制模式（重新评分所有）')
                .addOption('skip', '跳过模式（不进行评分）')
                .setValue(this.scoringMode)
                .onChange(value => {
                    this.scoringMode = value as "force" | "smart" | "skip";
                })
            );

        new Setting(contentEl)
            .addButton(btn => btn
                .setButtonText('取消')
                .onClick(() => {
                    this.close();
                }))
            .addButton(btn => btn
                .setButtonText('运行')
                .setCta()
                .onClick(() => {
                    if (!this.scanPath) {
                        this.notificationService.showError('请输入有效的扫描路径');
                        return;
                    }
                    
                    if (this.callbackFn) {
                        this.callbackFn({ 
                            scanPath: this.scanPath, 
                            scoringMode: this.scoringMode 
                        });
                    }
                    
                    this.close();
                }));
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}