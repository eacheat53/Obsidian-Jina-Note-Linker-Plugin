import { App, Notice, PluginSettingTab, Setting } from 'obsidian';
import { AIProvider } from '../models/interfaces';
import { DEFAULT_AI_MODELS } from '../models/constants';
import { DEFAULT_SETTINGS, DEFAULT_SCORING_PROMPT, DEFAULT_TAG_PROMPT } from '../models/settings';

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

        // Jina 嵌入配置部分
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">Jina 嵌入配置</div>';

        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('Jina API 密钥')
            .setDesc('您的 Jina API 密钥，用于生成文本嵌入向量。')
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
            .setName('Python 可执行路径')
            .setDesc('如留空则使用系统 PATH 中的 python。可以填写虚拟环境下的完整 python.exe 路径。')
            .addText(text => {
                text.setPlaceholder('例如 C:/Python311/python.exe')
                    .setValue(this.plugin.settings.pythonPath || '')
                    .onChange(async (value) => {
                        this.plugin.settings.pythonPath = value.trim();
                        await this.plugin.saveSettings();
                    });
            });

        // Jina 模型名称
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

        // Jina 嵌入最大字符数
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

        // AI 智能评分配置部分
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
            .setDesc('运行插件时默认扫描的文件夹路径 (半角逗号分隔)。使用 "/" 表示整个仓库。')
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
            .setDesc('Python 脚本处理时要排除的文件名 Glob 模式 (半角逗号分隔)。')
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
            .setName('AI 评分内容最大长度')
            .setDesc('传递给 AI API 进行评分的每条笔记内容的最大字符数。')
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

        // 批量处理参数设置
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">AI 批量处理参数</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('每次 API 请求的最大笔记对数')
            .setDesc('每次向 AI 服务发送请求时，最多包含的笔记对数量。增加可减少 API 调用次数，但可能增加处理时间。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxPairsPerRequest))
                .setValue(this.plugin.settings.maxPairsPerRequest.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxPairsPerRequest = parseInt(value) || DEFAULT_SETTINGS.maxPairsPerRequest;
                    await this.plugin.saveSettings();
                })
            );
            
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('每个笔记在 AI 评分时的最大字符数')
            .setDesc('限制发送给 AI 进行评分的每个笔记的最大字符数，以避免超出 API 限制。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxCharsPerNote))
                .setValue(this.plugin.settings.maxCharsPerNote.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxCharsPerNote = parseInt(value) || DEFAULT_SETTINGS.maxCharsPerNote;
                    await this.plugin.saveSettings();
                })
            );
            
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('每次 API 请求的最大总字符数')
            .setDesc('每次 API 批量请求的最大总字符数限制，以避免超出 API 的请求大小限制。')
            .addText(text => text
                .setPlaceholder(String(DEFAULT_SETTINGS.maxTotalCharsPerRequest))
                .setValue(this.plugin.settings.maxTotalCharsPerRequest.toString())
                .onChange(async (value) => {
                    this.plugin.settings.maxTotalCharsPerRequest = parseInt(value) || DEFAULT_SETTINGS.maxTotalCharsPerRequest;
                    await this.plugin.saveSettings();
                })
            );

        // AI 评分提示词设置
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">AI 评分提示词设置</div>';
        
        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('使用自定义评分提示词')
            .setDesc('启用后将使用下方自定义的评分提示词，而非默认提示词。')
            .addToggle(toggle => toggle
                .setValue(this.plugin.settings.useCustomScoringPrompt)
                .onChange(async (value) => {
                    this.plugin.settings.useCustomScoringPrompt = value;
                    await this.plugin.saveSettings();
                    this.display(); // 重新渲染设置页面
                })
            );
        
        // 添加自定义提示词文本框
        const promptContainer = containerEl.createEl('div', { cls: 'jina-settings-block' });
        promptContainer.createEl('div', { 
            text: '自定义评分提示词', 
            cls: 'setting-item-name' 
        });
        
        promptContainer.createEl('div', { 
            text: '自定义AI评分的提示词和评分标准。将作为指令发送给AI模型以指导评分过程。', 
            cls: 'setting-item-description' 
        });
        
        const textareaContainer = promptContainer.createEl('div', { cls: 'jina-textarea-container' });
        const textarea = textareaContainer.createEl('textarea', {
            cls: 'jina-textarea',
            attr: {
                rows: '10',
                placeholder: '在此输入自定义评分提示词...'
            }
        });
        
        textarea.value = this.plugin.settings.customScoringPrompt || DEFAULT_SCORING_PROMPT;
        textarea.addEventListener('change', async () => {
            this.plugin.settings.customScoringPrompt = textarea.value;
            await this.plugin.saveSettings();
        });
        
        // 添加恢复默认按钮
        const buttonContainer = promptContainer.createEl('div', { cls: 'jina-button-container' });
        const resetButton = buttonContainer.createEl('button', {
            text: '恢复默认提示词',
            cls: 'mod-warning'
        });
        
        resetButton.addEventListener('click', async () => {
            textarea.value = DEFAULT_SCORING_PROMPT;
            this.plugin.settings.customScoringPrompt = DEFAULT_SCORING_PROMPT;
            await this.plugin.saveSettings();
            new Notice('已恢复默认评分提示词');
        });
        
        // 如果没有启用自定义提示词，禁用相关控件
        if (!this.plugin.settings.useCustomScoringPrompt) {
            textarea.disabled = true;
            resetButton.disabled = true;
            textarea.classList.add('jina-disabled');
            resetButton.classList.add('jina-disabled');
        }
        
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
        
        // ------------------- AI 标签生成 -------------------
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div class="jina-settings-section-title">AI 标签生成</div>';

        // 已移除“标签生成模式”设置，由弹窗选择生成

        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('每篇笔记最多标签数')
            .addText(t=> t
                .setPlaceholder('5')
                .setValue(String(this.plugin.settings.maxTagsPerNote))
                .onChange(async v=>{ this.plugin.settings.maxTagsPerNote = parseInt(v)||5; await this.plugin.saveSettings(); })
            );

        new Setting(containerEl)
            .setClass('jina-settings-block')
            .setName('使用自定义标签提示词')
            .setDesc('启用后将使用下方自定义的标签提示词，而非默认提示词。')
            .addToggle(tg => tg
                .setValue(this.plugin.settings.useCustomTagPrompt)
                .onChange(async v => {
                    this.plugin.settings.useCustomTagPrompt = v;
                    await this.plugin.saveSettings();
                    this.display(); // 重新渲染
                }));

        // 自定义标签提示词文本框
        const tagPromptContainer = containerEl.createEl('div', { cls: 'jina-settings-block' });
        tagPromptContainer.createEl('div', {
            text: '自定义标签提示词',
            cls: 'setting-item-name'
        });

        tagPromptContainer.createEl('div', {
            text: '自定义 AI 生成标签的提示词，将作为指令发送给 AI 模型以指导标签生成。',
            cls: 'setting-item-description'
        });

        const tagTextareaContainer = tagPromptContainer.createEl('div', { cls: 'jina-textarea-container' });
        const tagTextarea = tagTextareaContainer.createEl('textarea', {
            cls: 'jina-textarea',
            attr: {
                rows: '10',
                placeholder: '在此输入自定义标签提示词...'
            }
        });

        tagTextarea.value = this.plugin.settings.customTagPrompt || DEFAULT_TAG_PROMPT;
        tagTextarea.addEventListener('change', async () => {
            this.plugin.settings.customTagPrompt = tagTextarea.value;
            await this.plugin.saveSettings();
        });

        // 恢复默认按钮
        const tagBtnContainer = tagPromptContainer.createEl('div', { cls: 'jina-button-container' });
        const tagResetBtn = tagBtnContainer.createEl('button', {
            text: '恢复默认提示词',
            cls: 'mod-warning'
        });

        tagResetBtn.addEventListener('click', async () => {
            tagTextarea.value = DEFAULT_TAG_PROMPT;
            this.plugin.settings.customTagPrompt = DEFAULT_TAG_PROMPT;
            await this.plugin.saveSettings();
            new Notice('已恢复默认标签提示词');
        });

        // 根据开关禁用控件
        if (!this.plugin.settings.useCustomTagPrompt) {
            tagTextarea.disabled = true;
            tagResetBtn.disabled = true;
            tagTextarea.classList.add('jina-disabled');
            tagResetBtn.classList.add('jina-disabled');
        }
        
        containerEl.createEl('div', { cls: 'jina-settings-section', text: '' }).innerHTML = '<div style="margin-top: 2em; color: var(--text-muted); font-size: 0.9em;">Jina AI Linker v' + this.plugin.manifest.version + '</div>';

        // 添加自定义样式
        this.addCustomStyles();
    }

    displayAIProviderSettings(containerEl: HTMLElement): void {
        const selectedProvider = this.plugin.settings.selectedAIProvider;
        const aiConfig = this.plugin.settings.aiModels[selectedProvider];

        // 直接渲染选中 AI 提供商的配置，无需启用开关
        aiConfig.enabled = true;

        {
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
        
        const suggestionContainer = containerEl.createEl('div', { cls: 'jina-model-suggestions' });
        suggestionContainer.createEl('span', { text: '常用模型: ', cls: 'jina-suggestion-label' });
        
        for (const suggestion of suggestions) {
            const suggestionEl = suggestionContainer.createEl('span', { 
                text: suggestion,
                cls: 'jina-model-suggestion'
            });
            
            suggestionEl.addEventListener('click', async () => {
                this.plugin.settings.aiModels[provider].modelName = suggestion;
                await this.plugin.saveSettings();
                this.display(); // 重新渲染
            });
        }
    }

    getModelSuggestions(provider: AIProvider): string[] {
        switch(provider) {
            case 'deepseek':
                return ['deepseek-chat', 'deepseek-reasoner'];
            case 'openai':
                return [ 'gpt-o3-mini', 'gpt-4o'];
            case 'claude':
                return ['claude-4-opus', 'claude-3.7-sonnet'];
            case 'gemini':
                return ['gemini-20.5 flash', 'gemini-2.5-pro'];
            default:
                return [];
        }
    }

    addCustomStyles(): void {
        const styleEl = document.createElement('style');
        styleEl.id = 'jina-settings-custom-styles';
        
        // 如果已存在样式元素，则移除它
        const existingStyle = document.getElementById('jina-settings-custom-styles');
        if (existingStyle) {
            existingStyle.remove();
        }
        
        styleEl.textContent = `
            .jina-textarea-container {
                width: 100%;
                margin-bottom: 10px;
            }
            
            .jina-textarea {
                width: 100%;
                min-height: 200px;
                border: 1px solid var(--background-modifier-border);
                border-radius: 4px;
                padding: 8px;
                font-family: var(--font-monospace);
                background-color: var(--background-primary);
                color: var(--text-normal);
                resize: vertical;
            }
            
            .jina-button-container {
                display: flex;
                justify-content: flex-end;
                margin-top: 8px;
            }
            
            .jina-disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            
            .jina-model-suggestions {
                margin-top: 6px;
                margin-bottom: 16px;
                margin-left: 24px;
            }
            
            .jina-suggestion-label {
                color: var(--text-muted);
                margin-right: 8px;
                font-size: 13px;
            }
            
            .jina-model-suggestion {
                display: inline-block;
                background-color: var(--interactive-accent);
                color: var(--text-on-accent);
                padding: 2px 8px;
                border-radius: 4px;
                margin-right: 8px;
                margin-bottom: 8px;
                font-size: 12px;
                cursor: pointer;
            }
            
            .jina-model-suggestion:hover {
                opacity: 0.85;
            }
        `;
        
        document.head.appendChild(styleEl);
    }
}