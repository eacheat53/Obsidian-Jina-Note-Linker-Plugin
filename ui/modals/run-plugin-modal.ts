import { App, Modal, Setting } from 'obsidian';
// 使用 any 以避免默认导入限制

import { RunOptions } from '../../models/interfaces';

export class RunPluginModal extends Modal {
    plugin: any;
    onSubmit: (options: RunOptions) => void;
    options: RunOptions;

    constructor(app: App, plugin: any, onSubmit: (options: RunOptions) => void) {
        super(app);
        this.plugin = plugin;
        this.onSubmit = onSubmit;
        // 初始化时使用设置中的默认扫描路径
        this.options = {
            scanPath: this.plugin.settings.defaultScanPath,
            scoringMode: 'smart',
        };
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();

        contentEl.createEl('h2', { text: '配置 Jina Linker 运行参数' });

        new Setting(contentEl)
            .setName('扫描目标文件夹 (可选)')
            .setDesc('逗号分隔的仓库相对文件夹路径。使用 "/" 扫描整个仓库。会遵循全局排除设置。')
            .addText(text => text
                .setPlaceholder('例如：/, 文件夹1/子文件夹, 文件夹2')
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