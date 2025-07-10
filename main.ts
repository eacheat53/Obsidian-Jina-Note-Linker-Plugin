import { App, Notice, Plugin, TFile, Menu, normalizePath } from 'obsidian';
import { JinaLinkerSettings, DEFAULT_SETTINGS } from './models/settings';
import { PerformanceMonitor } from './utils/performance-monitor';
import { CacheManager } from './utils/cache-manager';
import { PythonBridge } from './utils/python-bridge';
import { HashManager } from './services/hash-manager';
import { LinkManager } from './services/link-manager';
import { FileProcessor } from './services/file-processor';
import { TagManager } from './services/tag-manager';
import { JinaLinkerSettingTab } from './ui/settings-tab';
import { RunPluginModal } from './ui/modals/run-plugin-modal';
import { ProgressModal } from './ui/modals/progress-modal';
import { AddHashBoundaryModal } from './ui/modals/add-hash-boundary-modal';
import { AddAiTagsModal } from './ui/modals/add-ai-tags-modal';
import { log } from './utils/error-handler';
import { DEFAULT_AI_MODELS } from './models/constants';
import { AIProvider, RunOptions } from './models/interfaces';
import { NotificationService } from './utils/notification-service';

export default class JinaLinkerPlugin extends Plugin {
    settings: JinaLinkerSettings;
    performanceMonitor: PerformanceMonitor;
    private cacheManager: CacheManager;
    private pythonBridge: PythonBridge;
    private hashManager: HashManager;
    private linkManager: LinkManager;
    private tagManager: TagManager;
    private fileProcessor: FileProcessor;
    private notificationService: NotificationService;

    async onload() {
        console.log('🚀 Jina AI Linker 插件开始加载...');
        await this.loadSettings();
        console.log('✅ 插件设置加载完成');

        // 初始化各个管理器
        this.performanceMonitor = new PerformanceMonitor();
        this.cacheManager = new CacheManager();
        this.pythonBridge = new PythonBridge(this.settings);
        this.hashManager = new HashManager(this.app, this.cacheManager);
        this.linkManager = new LinkManager(this.app, this.settings, this.cacheManager);
        this.tagManager = new TagManager(this.app, this.settings, this.cacheManager);
        this.fileProcessor = new FileProcessor(this.app, this.cacheManager);

        // 初始化通知服务
        this.notificationService = NotificationService.getInstance();

        // 首次使用不再执行旧 JSON→SQLite 迁移逻辑

        console.log('✅ 性能监控器和服务初始化完成');
        console.log('🎉 Jina AI Linker 插件加载完成！');

        // 添加命令和功能
        this.addCommands();
        this.addRibbonMenu();
        this.addSettingTab(new JinaLinkerSettingTab(this.app, this));
        
        this.notificationService.showNotice('Jina AI Linker 插件已加载');
    }

    onunload() {
        this.pythonBridge.cancelOperation();
        this.cacheManager.clearCache();
        this.notificationService.showNotice('Jina AI Linker 插件已卸载', 2000);
    }

    // 添加各种命令
    private addCommands() {
        this.addCommand({
            id: 'run-jina-linker-processing-and-insert-links',
            name: '处理笔记并插入建议链接',
            callback: () => {
                console.log('📝 用户启动：处理笔记并插入建议链接功能');
                this.runPluginWithUI();
            }
        });

        // 已移除“更新嵌入数据中的笔记哈希值”命令（数据库架构自动处理哈希同步）

        this.addCommand({
            id: 'add-hash-boundary-markers',
            name: '批量添加哈希边界标记',
            callback: () => {
                console.log('🏷️ 用户启动：批量添加哈希边界标记功能');
                new AddHashBoundaryModal(this.app, this, async (targetPaths: string) => {
                    const result = await this.fileProcessor.addHashBoundaryMarkers(targetPaths);
                        if (result.success) {
                        const { processedFiles, updatedFiles } = result.data!;
                        new Notice(`✅ 处理完成！检查了 ${processedFiles} 个文件，添加标记到 ${updatedFiles} 个文件`);
                            } else {
                        new Notice('❌ 批量添加哈希边界标记失败');
                    }
                }).open();
            }
        });

        // ---- 新增：仅插入 AI 标签 ----
        this.addCommand({
            id: 'insert-ai-tags-into-notes',
            name: '批量插入 AI 标签到笔记',
            callback: () => {
                console.log('🏷️ 用户启动：批量插入 AI 标签功能');
                new AddAiTagsModal(this.app, this, (paths: string, mode: 'smart'|'force') => {
                    this.runTagOnlyFlow(paths, mode);
                }).open();
            }
        });

        // 添加测试命令（仅在开发模式下使用）
        this.addCommand({
            id: 'test-insert-links-into-body',
            name: '测试：处理重复链接部分',
            callback: () => {
                console.log('🧪 用户启动：测试处理重复链接部分');
                this.linkManager.testInsertLinksIntoBody('梦中画境.md');
            }
        });
    }

    // 添加功能菜单到工具栏
    private addRibbonMenu() {
        this.addRibbonIcon('link', 'Jina Linker 工具', (evt: MouseEvent) => {
            // 创建菜单
            const menu = new Menu();
            
            menu.addItem((item: any) => {
                item.setTitle("处理笔记并插入建议链接")
                   .setIcon("link")
                   .onClick(() => {
                        this.runPluginWithUI();
                   });
            });
            
            // 移除更新哈希菜单项

            menu.addItem((item: any) => {
                item.setTitle("批量添加哈希边界标记")
                   .setIcon("hash")
                   .onClick(() => {
                        new AddHashBoundaryModal(this.app, this, async (targetPaths: string) => {
                            const result = await this.fileProcessor.addHashBoundaryMarkers(targetPaths);
                            if (result.success) {
                                const { processedFiles, updatedFiles } = result.data!;
                                new Notice(`✅ 处理完成！检查了 ${processedFiles} 个文件，添加标记到 ${updatedFiles} 个文件`);
                            } else {
                                new Notice('❌ 批量添加哈希边界标记失败');
                            }
                        }).open();
                   });
            });

            menu.addItem((item: any) => {
                item.setTitle("批量插入 AI 标签")
                   .setIcon("tag")
                   .onClick(() => {
                        new AddAiTagsModal(this.app, this, (paths: string, mode: 'smart'|'force') => {
                            this.runTagOnlyFlow(paths, mode);
                        }).open();
                   });
            });
            
            menu.showAtMouseEvent(evt);
        });
    }

    // 主要的插件功能执行流程
    private async runPluginWithUI() {
        new RunPluginModal(this.app, this, async (options: RunOptions) => {
            const progressModal = new ProgressModal(this.app, 'Jina AI Linker 处理进度', () => {
                this.pythonBridge.cancelOperation();
            });
            progressModal.open();
            
            try {
                // 第一阶段：运行Python脚本
                progressModal.updateProgress(0, 2, '正在运行Python脚本', '生成嵌入数据和AI评分...');
                const result = await this.pythonBridge.runPythonScript(
                    options.scanPath, 
                    options.scoringMode,
                    this.manifest.dir || '',
                    (this.app.vault.adapter as any).getBasePath()
                );
                
                if (result.success) {
                    // 第二阶段：插入链接
                    progressModal.updateProgress(1, 2, '正在插入建议链接', '处理笔记文件...');
                    const insertResult = await this.linkManager.insertAISuggestedLinksIntoNotes(options.scanPath);
                    
                    if (insertResult.success) {
                        const { processedFiles, updatedFiles } = insertResult.data!;
                        // 删除标签插入代码，使功能独立
                        // await this.tagManager.insertAIGeneratedTagsIntoNotes(options.scanPath);

                        progressModal.setCompleted(`✅ 链接插入完成！检查了 ${processedFiles} 个文件，插入链接到 ${updatedFiles} 个文件`);
                        
                        // 显示性能统计
                        const metrics = this.performanceMonitor.getMetricsSummary();
                        log('info', '性能统计', metrics);
                        
                        setTimeout(() => progressModal.close(), 3000);
                    } else {
                        progressModal.setError('链接插入失败');
                    }
                } else {
                    progressModal.setError('Python脚本执行失败');
                }
            } catch (error: any) {
                progressModal.setError('处理过程中发生错误');
                log('error', '处理过程中发生错误', error);
            }
        }).open();
    }

    // 仅生成并插入 AI 标签的快捷流程
    private async runTagOnlyFlow(targetPaths: string, mode: 'smart' | 'force') {
        // 临时覆盖 tagsMode 以便传递给 Python
        const originalMode = this.settings.tagsMode;
        this.settings.tagsMode = mode;

        const progress = new ProgressModal(this.app, '生成并插入 AI 标签', () => this.pythonBridge.cancelOperation());
        progress.open();

        try {
            // 1. 后端：只生成标签
            progress.updateProgress(0, 2, '运行后端', '生成 AI 标签…');
            const pyRes = await this.pythonBridge.runPythonScript(
                targetPaths || '/',
                'skip', // 评分跳过
                this.manifest.dir || '',
                (this.app.vault.adapter as any).getBasePath()
            );

            if (!pyRes.success) throw new Error('Python 执行失败');

            // 2. 前端：写入 front-matter
            progress.updateProgress(1, 2, '写入标签', '插入 front-matter…');
            const { processed, updated } = await this.tagManager.insertAIGeneratedTagsIntoNotes(targetPaths);

            progress.setCompleted(`✅ 处理 ${processed} 文件，更新 ${updated}`);
            setTimeout(() => progress.close(), 2500);
        } catch (err) {
            progress.setError('生成/插入标签失败');
            log('error', 'runTagOnlyFlow error', err);
        } finally {
            // 恢复原始模式，避免影响其他功能
            this.settings.tagsMode = originalMode;
        }
    }

    // 计算单个文件的哈希值
    private async calculateHashForFile(filePath: string) {
                    const normalizedFilePath = normalizePath(filePath);
                    const tFile = this.app.vault.getAbstractFileByPath(normalizedFilePath);

                    if (!(tFile instanceof TFile)) {
                        new Notice(`错误：文件 "${normalizedFilePath}" 未找到或不是一个有效文件。`);
                        return;
                    }
                    
        const hash = await this.hashManager.calculateNoteContentHashForFile(tFile);
                    if (hash) {
                        new Notice(`文件 "${filePath}" 的内容哈希值: ${hash}`);
                    }
    }

    // 迁移逻辑已废弃，保留空实现避免旧代码引用
    async runMigration(): Promise<void> { return Promise.resolve(); }

    async loadSettings() {
        const loadedData = await this.loadData();
        
        // 清理旧的、无用的设置
        if (loadedData) {
            delete loadedData.outputDirInVault;
            delete loadedData.aiJudgedCandidatesFmKey;
        }

        this.settings = Object.assign({}, DEFAULT_SETTINGS, loadedData);
        
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

    cancelCurrentOperation(): void {
        this.pythonBridge.cancelOperation();
    }

    clearCache(): void {
        this.cacheManager.clearCache();
        this.notificationService.showNotice('🧹 缓存已清理', 2000);
    }
}