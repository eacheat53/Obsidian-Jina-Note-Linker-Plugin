import { App, Notice, PluginSettingTab, Setting } from 'obsidian';
import { AIProvider } from '../models/interfaces';
import { DEFAULT_AI_MODELS } from '../models/constants';
import { DEFAULT_SETTINGS } from '../models/settings';

export class JinaLinkerSettingTab extends PluginSettingTab {
    plugin: any;

    constructor(app: App, plugin: any) {
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
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">处理参数</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('默认扫描路径')
            .setDesc('运行插件时默认扫描的文件夹路径 (逗号分隔)。使用 "/" 表示整个仓库。')
            .addText(text => text
                .setPlaceholder('例如：/, 文件夹1, 文件夹2/子文件夹')
                .setValue(this.plugin.settings.defaultScanPath)
                .onChange(async (value) => {
                    this.plugin.settings.defaultScanPath = value.trim() || DEFAULT_SETTINGS.defaultScanPath;
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
                .setPlaceholder(String(DEFAULT_SETTINGS.jinaModelName))
                .setValue(this.plugin.settings.jinaModelName)
                .onChange(async (value) => {
                    this.plugin.settings.jinaModelName = value.trim() || DEFAULT_SETTINGS.jinaModelName;
                    await this.plugin.saveSettings();
                })
            );
        
    // 显示选中AI提供商的配置
        this.displayAIProviderSettings(containerEl);

        // Python 脚本处理参数
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">处理参数</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('默认扫描路径')
            .setDesc('运行插件时默认扫描的文件夹路径 (逗号分隔)。使用 "/" 表示整个仓库。')
            .addText(text => text
                .setPlaceholder('例如：/, 文件夹1, 文件夹2/子文件夹')
                .setValue(this.plugin.settings.defaultScanPath)
                .onChange(async (value) => {
                    this.plugin.settings.defaultScanPath = value.trim() || DEFAULT_SETTINGS.defaultScanPath;
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
                .setPlaceholder(String(DEFAULT_SETTINGS.jinaModelName))
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
         // 显示选中AI提供商的配置
         this.displayAIProviderSettings(containerEl);

         // Python 脚本处理参数
         containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">处理参数</div>';
         
         new Setting(containerEl)
             .setClass('jina-settings-block')
             .setName('默认扫描路径')
             .setDesc('运行插件时默认扫描的文件夹路径 (逗号分隔)。使用 "/" 表示整个仓库。')
             .addText(text => text
                 .setPlaceholder('例如：/, 文件夹1, 文件夹2/子文件夹')
                 .setValue(this.plugin.settings.defaultScanPath)
                 .onChange(async (value) => {
                     this.plugin.settings.defaultScanPath = value.trim() || DEFAULT_SETTINGS.defaultScanPath;
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
                 .setPlaceholder(String(DEFAULT_SETTINGS.jinaModelName))
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
            'claude': ['claude-3-5-sonnet-20240620', 'claude-3-haiku-20240307', 'claude-3-sonnet-20240229'],
            'gemini': ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.0-pro'],
            'custom': []
        };
        return suggestions[provider] || [];
    }
}