import { App, Notice, Plugin, TFile, Menu, normalizePath } from 'obsidian';
import { JinaLinkerSettings, DEFAULT_SETTINGS } from './models/settings';
import { PerformanceMonitor } from './utils/performance-monitor';
import { CacheManager } from './utils/cache-manager';
import { PythonBridge } from './utils/python-bridge';
import { HashManager } from './services/ash-manager';
import { LinkManager } from './services/link-manager';
import { FileProcessor } from './services/file-processor';
import { JinaLinkerSettingTab } from './ui/settings-tab';
import { RunPluginModal } from './ui/modals/run-plugin-modal';
import { ProgressModal } from './ui/modals/progress-modal';
import { CalculateHashModal } from './ui/modals/calculate-hash-modal';
import { UpdateHashesModal } from './ui/modals/update-hashes-modal';
import { AddHashBoundaryModal } from './ui/modals/add-hash-boundary-modal';
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
        this.fileProcessor = new FileProcessor(this.app, this.cacheManager);

        // 初始化通知服务
        this.notificationService = NotificationService.getInstance();

        if (!this.settings.dataMigrationCompleted) {
            await this.runMigration();
        }

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

        this.addCommand({
            id: 'calculate-note-content-hash',
            name: '计算笔记内容哈希值 (诊断用)',
            callback: () => {
                console.log('🔢 用户启动：计算笔记内容哈希值功能');
                new CalculateHashModal(this.app, this, async (filePath) => {
                    this.calculateHashForFile(filePath);
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
                    await this.fileProcessor.updateHashesInEmbeddingsFile(relativePaths);
                }).open();
            }
        });

        this.addCommand({
            id: 'add-hash-boundary-markers',
            name: '批量添加哈希边界标记',
            callback: () => {
                console.log('🏷️ 用户启动：批量添加哈希边界标记功能');
                new AddHashBoundaryModal(this.app, this, async (targetPaths) => {
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
            
            menu.addItem((item: any) => {
                item.setTitle("计算笔记内容哈希值 (诊断用)")
                   .setIcon("hash")
                   .onClick(() => {
                        new CalculateHashModal(this.app, this, async (filePath) => {
                            this.calculateHashForFile(filePath);
                        }).open();
                   });
            });
            
            menu.addItem((item: any) => {
                item.setTitle("更新嵌入数据中的笔记哈希值")
                   .setIcon("refresh-cw")
                   .onClick(() => {
                        new UpdateHashesModal(this.app, this, async (filePathsStr) => {
                            const relativePaths = filePathsStr.split(',').map(p => p.trim()).filter(p => p);
                            if (relativePaths.length === 0) {
                                new Notice('未提供有效的文件路径。');
                                return;
                            }
                            await this.fileProcessor.updateHashesInEmbeddingsFile(relativePaths);
                        }).open();
                   });
            });

            menu.addItem((item: any) => {
                item.setTitle("批量添加哈希边界标记")
                   .setIcon("hash")
                   .onClick(() => {
                        new AddHashBoundaryModal(this.app, this, async (targetPaths) => {
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
                        progressModal.setCompleted(`✅ 处理完成！检查了 ${processedFiles} 个文件，更新了 ${updatedFiles} 个文件`);
                        
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

    async runMigration(): Promise<void> {
        this.notificationService.showNotice('Data migration to SQLite required. Starting process...', 5000);
        log('info', 'Data migration to SQLite required. Starting process...');

        if (!this.manifest.dir) {
            const errorMsg = 'Plugin directory not found. Cannot run migration.';
            log('error', errorMsg);
            this.notificationService.showError(errorMsg);
            return Promise.reject(new Error(errorMsg));
        }

        try {
            await this.pythonBridge.runMigration(
                this.manifest.dir, 
                (this.app.vault.adapter as any).getBasePath()
            );
            
            this.settings.dataMigrationCompleted = true;
            await this.saveSettings();
            
            return Promise.resolve();
        } catch (error) {
            return Promise.reject(error);
        }
    }

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