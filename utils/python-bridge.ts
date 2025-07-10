import { spawn, ChildProcess } from 'child_process';
import { Notice } from 'obsidian';
import * as path from 'path';
import { createProcessingError, log } from '../utils/error-handler';
import { OperationResult, ProcessingError } from '../models/interfaces';
import { DEFAULT_OUTPUT_DIR_IN_VAULT, HASH_BOUNDARY_MARKER } from '../models/constants';
import { JinaLinkerSettings } from '../models/settings';
import { FilePathUtils } from '../utils/path-utils';
import { NotificationService } from './notification-service';

export class PythonBridge {
    private currentOperation: AbortController | null = null;
    private notificationService = NotificationService.getInstance();

    constructor(private settings: JinaLinkerSettings) {}

    cancelOperation(): void {
        if (this.currentOperation) {
            this.currentOperation.abort();
            this.currentOperation = null;
            log('info', '用户取消了当前操作');
        }
    }

    async runPythonScript(
        scanPathFromModal: string, 
        scoringModeFromModal: "force" | "smart" | "skip",
        manifestDir: string, 
        vaultBasePath: string
    ): Promise<OperationResult<boolean>> {
        log('info', '开始执行：Python CLI 处理');
        log('info', `扫描路径: ${scanPathFromModal}`);
        log('info', `AI评分模式: ${scoringModeFromModal}`);
        
        try {
            this.currentOperation = new AbortController();
            
            return new Promise(async (resolve) => {
                // 解析 Python 解释器与脚本路径
                if (!manifestDir) {
                    const error = createProcessingError('FILE_NOT_FOUND', '无法确定插件目录以定位 cli.py');
                    resolve({ success: false, error });
                    return;
                }
                const pythonExe = this.settings.pythonPath || 'python';
                const scriptPath = path.join(vaultBasePath, manifestDir, 'python_src', 'cli.py');

                // 使用默认输出目录
                const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
                const fullOutputDirPath = path.join(vaultBasePath, outputDirInVault);
                
                try {
                    const fs = require('fs');
                    if (!fs.existsSync(fullOutputDirPath)) {
                        fs.mkdirSync(fullOutputDirPath, { recursive: true });
                    }
                } catch (error: any) {
                    const processingError = createProcessingError('PERMISSION_DENIED', 
                        `创建输出目录 "${outputDirInVault}" 失败`, 
                        error instanceof Error ? error.message : String(error));
                    resolve({ success: false, error: processingError });
                    return;
                }

                // 构建命令行参数（无脚本路径）
                let args: string[] = [
                    '--project_root', vaultBasePath,
                    '--output_dir', outputDirInVault,
                    '--jina_api_key', this.settings.jinaApiKey,
                    '--ai_scoring_mode', scoringModeFromModal,
                    '--similarity_threshold', this.settings.similarityThreshold.toString(),
                    '--jina_model_name', this.settings.jinaModelName,
                    '--max_chars_for_jina', this.settings.maxCharsForJina.toString(),
                    '--max_content_length_for_ai', this.settings.maxContentLengthForAI.toString(),
                    '--ai_scoring_batch_size', this.settings.maxPairsPerRequest.toString(),
                    '--max_chars_per_note', this.settings.maxCharsPerNote.toString(),
                    '--max_total_chars_per_request', this.settings.maxTotalCharsPerRequest.toString(),
                    '--export_json'
                ];
                
                // 传递选中的AI模型配置
                const selectedAIModel = this.settings.aiModels[this.settings.selectedAIProvider];
                if (selectedAIModel && selectedAIModel.enabled && selectedAIModel.apiKey) {
                    args.push('--ai_provider', this.settings.selectedAIProvider);
                    args.push('--ai_api_url', selectedAIModel.apiUrl);
                    args.push('--ai_api_key', selectedAIModel.apiKey);
                    args.push('--ai_model_name', selectedAIModel.modelName);
                }
                
                // -------- AI 评分自定义提示词 --------
                if (this.settings.useCustomScoringPrompt) {
                    args.push('--use_custom_scoring_prompt');
                    args.push('--custom_scoring_prompt', this.settings.customScoringPrompt);
                }

                // -------- AI 标签生成相关参数 --------
                // tags_mode: force / smart / skip
                args.push('--tags_mode', this.settings.tagsMode);

                // 使用自定义标签提示词时沿用现有参数名 (复用 --custom_scoring_prompt 逻辑)
                if (this.settings.useCustomTagPrompt) {
                    args.push('--use_custom_scoring_prompt');
                    args.push('--custom_scoring_prompt', this.settings.customTagPrompt);
                }
                
                // 添加扫描路径
                if (scanPathFromModal && scanPathFromModal.trim() !== '/') {
                    args.push('--scan_target_folders');
                    const folders = scanPathFromModal.split(',').map(f => f.trim()).filter(f => f);
                    args = args.concat(folders);
                }
                
                // 添加排除文件夹
                if (this.settings.excludedFolders) {
                    args.push('--excluded_folders');
                    const excludedFolders = this.settings.excludedFolders.split(',').map(f => f.trim()).filter(f => f);
                    args = args.concat(excludedFolders);
                }
                
                // 添加排除文件模式
                if (this.settings.excludedFilesPatterns) {
                    args.push('--excluded_files_patterns');
                    const patterns = this.settings.excludedFilesPatterns.split(',').map(p => p.trim()).filter(p => p);
                    args = args.concat(patterns);
                }
                
                this.notificationService.showNotice('🚀 JinaLinker: 开始执行后端程序...', 5000);
                
                log('info', `执行后端程序: ${pythonExe} ${[scriptPath, ...this.sanitizeArgsForLog(args)].join(' ')}`);
                const pythonProcess = spawn(pythonExe, [scriptPath, ...args], {
                    stdio: ['pipe', 'pipe', 'pipe'],
                    signal: this.currentOperation?.signal
                });
            
                // 处理Python脚本输出
                this.handlePythonProcessOutput(pythonProcess, resolve);
            });
        } catch (error: any) {
            const processingError = createProcessingError('UNKNOWN',
                '执行Python脚本时发生未知错误',
                error instanceof Error ? error.message : String(error));
            return { success: false, error: processingError };
        }
    }

    private handlePythonProcessOutput(pythonProcess: ChildProcess, resolve: (value: OperationResult<boolean>) => void): void {
        let scriptOutput = '';
        let scriptError = '';
        let lastProgressUpdate = 0;
        const progressUpdateInterval = 500; // 至少间隔500ms更新一次进度
        let currentProgress = 0;
        let totalFiles = 0;
        let operationStarted = false;

        pythonProcess.stdout?.on('data', (data) => {
            if (this.currentOperation?.signal.aborted) return;
            const outputChunk = data.toString();
            scriptOutput += outputChunk;
            log('info', `后端输出: ${outputChunk.trim()}`);
            
            // 检测进度信息
            const progressMatch = outputChunk.match(/处理 (\d+)\/(\d+) 个文件/);
            if (progressMatch) {
                const processed = parseInt(progressMatch[1]);
                const total = parseInt(progressMatch[2]);
                
                if (!operationStarted) {
                    operationStarted = true;
                    this.notificationService.startProgress('处理文件', total);
                    totalFiles = total;
                    lastProgressUpdate = Date.now();
                }
                
                currentProgress = processed;
                const now = Date.now();
                if (now - lastProgressUpdate >= progressUpdateInterval || processed === total) {
                    lastProgressUpdate = now;
                    this.notificationService.updateProgress(processed);
                }
            }
        });

        pythonProcess.stderr?.on('data', (data) => {
            if (this.currentOperation?.signal.aborted) return;
            const errorChunk = data.toString();
            scriptError += errorChunk;
            log('error', `后端错误: ${errorChunk.trim()}`);
        });

        pythonProcess.on('close', (code) => {
            this.currentOperation = null;
            
            if (code === 0) {
                this.notificationService.completeProgress('后端程序执行成功');
                log('info', '后端程序执行成功', scriptOutput);
                resolve({ success: true, data: true });
            } else {
                const error = createProcessingError('UNKNOWN',
                    '后端程序执行失败',
                    `退出码: ${code}, 错误输出: ${scriptError}`);
                this.notificationService.showError(error.message);
                resolve({ success: false, error });
            }
        });

        pythonProcess.on('error', (err: Error) => {
            this.currentOperation = null;
            
            let error: ProcessingError;
            if (err.message.includes('ENOENT')) {
                error = createProcessingError('PYTHON_NOT_FOUND',
                    '找不到后端程序 (jina-linker.exe)',
                    err.message);
            } else {
                error = createProcessingError('UNKNOWN',
                    '启动后端程序失败',
                    err.message);
            }
            
            this.notificationService.showError(error.message);
            resolve({ success: false, error });
        });

        // 处理操作取消
        this.currentOperation?.signal.addEventListener('abort', () => {
            pythonProcess.kill();
            const error = createProcessingError('UNKNOWN', '操作已被用户取消');
            this.notificationService.showNotice('❌ 操作已被用户取消', 3000);
            resolve({ success: false, error });
        });
    }

    async runMigration(manifestDir: string, vaultBasePath: string): Promise<void> {
        this.notificationService.showNotice('开始数据迁移到SQLite...', 5000);
        log('info', '开始数据迁移到SQLite...');

        if (!manifestDir) {
            const errorMsg = '无法确定插件目录。无法运行迁移。';
            log('error', errorMsg);
            this.notificationService.showError(errorMsg);
            return Promise.reject(new Error(errorMsg));
        }

        if (!this.settings.pythonPath) {
            log('warn', '缺少 pythonPath，跳过数据迁移。');
            this.notificationService.showNotice('⚠️ 未配置 Python 路径，已跳过旧数据迁移', 4000);
            return Promise.resolve();
        }

        return new Promise((resolve, reject) => {
            const scriptToExecutePath = path.join(vaultBasePath, manifestDir, 'main.py');
            const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT; 

            const args = [
                scriptToExecutePath,
                '--project_root', vaultBasePath,
                '--output_dir', outputDirInVault,
                '--migrate'
            ];

            const pythonProcess = spawn(this.settings.pythonPath, args);

            pythonProcess.stdout.on('data', (data) => {
                log('info', `迁移脚本输出: ${data}`);
            });

            pythonProcess.stderr.on('data', (data) => {
                log('error', `迁移脚本错误: ${data}`);
            });

            pythonProcess.on('close', async (code) => {
                if (code === 0) {
                    this.notificationService.showNotice('✅ 数据迁移到SQLite成功完成！', 5000);
                    log('info', '数据迁移到SQLite成功完成！');
                    resolve();
                } else {
                    const errorMsg = `❌ 数据迁移失败，退出码: ${code}。查看控制台了解详情。`;
                    this.notificationService.showError(errorMsg);
                    log('error', `数据迁移失败，退出码: ${code}`);
                    reject(new Error(`迁移失败，退出码: ${code}`));
                }
            });

            pythonProcess.on('error', (err) => {
                const errorMsg = '❌ 启动迁移脚本失败。查看控制台了解详情。';
                this.notificationService.showError(errorMsg);
                log('error', '启动迁移脚本失败:', err);
                reject(err);
            });
        });
    }

    // 脱敏日志中的API密钥
    private sanitizeArgsForLog(args: string[]): string[] {
        const sanitizedArgs: string[] = [];
        for (let i = 0; i < args.length; i++) {
            if ((args[i] === '--jina_api_key' || args[i] === '--ai_api_key') && i + 1 < args.length) {
                sanitizedArgs.push(args[i]);
                sanitizedArgs.push('********');
                i++; // 跳过实际的密钥值
            } else {
                sanitizedArgs.push(args[i]);
            }
        }
        return sanitizedArgs;
    }
}