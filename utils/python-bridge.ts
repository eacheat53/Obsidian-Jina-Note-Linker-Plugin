import { spawn, ChildProcess } from 'child_process';
import { Notice } from 'obsidian';
import * as path from 'path';
import { createProcessingError, log } from '../utils/error-handler';
import { OperationResult, ProcessingError } from '../models/interfaces';
import { DEFAULT_OUTPUT_DIR_IN_VAULT, HASH_BOUNDARY_MARKER } from '../models/constants';
import { JinaLinkerSettings } from '../models/settings';
import { FilePathUtils } from '../utils/path-utils';

export class PythonBridge {
    private currentOperation: AbortController | null = null;

    constructor(private settings: JinaLinkerSettings) {}

    sanitizeArgsForLog(args: string[]): string[] {
        return args.map(arg => {
            if (arg.includes('api_key') || arg.startsWith('sk-') || arg.startsWith('Bearer ')) {
                return arg.replace(/sk-[a-zA-Z0-9]+/g, 'sk-***').replace(/Bearer [a-zA-Z0-9]+/g, 'Bearer ***');
            }
            return FilePathUtils.sanitizePathForLog(arg);
        });
    }

    cancelCurrentOperation(): void {
        if (this.currentOperation) {
            this.currentOperation.abort();
            this.currentOperation = null;
            new Notice('⚠️ 操作已取消', 3000);
        }
    }

    async runPythonScript(
        scanPathFromModal: string, 
        scoringModeFromModal: "force" | "smart" | "skip",
        manifestDir: string, 
        vaultBasePath: string
    ): Promise<OperationResult<boolean>> {
        log('info', '开始执行：Python脚本处理');
        log('info', `扫描路径: ${scanPathFromModal}`);
        log('info', `AI评分模式: ${scoringModeFromModal}`);
        
        try {
            this.currentOperation = new AbortController();
            
            return new Promise(async (resolve) => {
                let scriptToExecutePath = '';
                const bundledScriptName = 'main.py';
        
                // 默认使用插件自带脚本
                if (manifestDir) {
                    scriptToExecutePath = path.join(vaultBasePath, manifestDir, bundledScriptName);
                } else {
                    const error = createProcessingError('FILE_NOT_FOUND', 'Python 脚本路径无法确定');
                    resolve({ success: false, error });
                    return;
                }
            
                // 使用默认输出目录
                const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
                const fullOutputDirPath = path.join(vaultBasePath, outputDirInVault);
                
                try {
                    // 创建输出目录
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

                // 构建命令行参数
                let args = this.buildPythonScriptArgs(
                    scriptToExecutePath, 
                    vaultBasePath, 
                    outputDirInVault, 
                    scanPathFromModal,
                    scoringModeFromModal
                );
                
                new Notice('🚀 JinaLinker: 开始执行 Python 脚本...', 5000);
                
                log('info', `执行 Python 命令: ${this.settings.pythonPath} ${this.sanitizeArgsForLog(args).join(' ')}`);
                const pythonProcess = spawn(this.settings.pythonPath, args, {
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

    private buildPythonScriptArgs(
        scriptPath: string, 
        vaultBasePath: string, 
        outputDir: string,
        scanPath: string,
        scoringMode: string
    ): string[] {
        let args = [
            scriptPath,
            '--project_root', vaultBasePath,
            '--output_dir', outputDir,
            '--jina_api_key', this.settings.jinaApiKey,
            '--ai_scoring_mode', scoringMode,
            '--similarity_threshold', this.settings.similarityThreshold.toString(),
            '--jina_model_name', this.settings.jinaModelName,
            '--max_chars_for_jina', this.settings.maxCharsForJina.toString(),
            '--max_candidates_per_source_for_ai_scoring', this.settings.maxCandidatesPerSourceForAIScoring.toString(),
            '--hash_boundary_marker', HASH_BOUNDARY_MARKER.replace(/"/g, '\"'),
            '--max_content_length_for_ai', this.settings.maxContentLengthForAI.toString(),
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
        
        // 添加扫描路径
        if (scanPath && scanPath.trim() !== '/') {
            args.push('--scan_target_folders');
            const folders = scanPath.split(',').map(f => f.trim()).filter(f => f);
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
        
        return args;
    }

    private handlePythonProcessOutput(pythonProcess: ChildProcess, resolve: (value: OperationResult<boolean>) => void): void {
        let scriptOutput = '';
        let scriptError = '';

        pythonProcess.stdout?.on('data', (data) => {
            if (this.currentOperation?.signal.aborted) return;
            const outputChunk = data.toString();
            scriptOutput += outputChunk;
            log('info', `Python stdout: ${outputChunk.trim()}`);
        });

        pythonProcess.stderr?.on('data', (data) => {
            if (this.currentOperation?.signal.aborted) return;
            const errorChunk = data.toString();
            scriptError += errorChunk;
            log('error', `Python stderr: ${errorChunk.trim()}`);
        });

        pythonProcess.on('close', (code) => {
            this.currentOperation = null;
            
            if (code === 0) {
                new Notice('✅ Python 脚本执行成功', 3000);
                log('info', 'Python 脚本执行成功', scriptOutput);
                resolve({ success: true, data: true });
            } else {
                const error = createProcessingError('UNKNOWN',
                    'Python 脚本执行失败',
                    `退出码: ${code}, 错误输出: ${scriptError}`);
                resolve({ success: false, error });
            }
        });

        pythonProcess.on('error', (err: Error) => {
            this.currentOperation = null;
            
            let error: ProcessingError;
            if (err.message.includes('ENOENT')) {
                error = createProcessingError('PYTHON_NOT_FOUND',
                    '找不到Python解释器',
                    err.message);
            } else {
                error = createProcessingError('UNKNOWN',
                    '启动 Python 脚本失败',
                    err.message);
            }
            
            resolve({ success: false, error });
        });

        // 处理操作取消
        this.currentOperation?.signal.addEventListener('abort', () => {
            pythonProcess.kill();
            const error = createProcessingError('UNKNOWN', '操作已被用户取消');
            resolve({ success: false, error });
        });
    }

    async runMigration(manifestDir: string, vaultBasePath: string): Promise<void> {
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

            pythonProcess.stdout?.on('data', (data) => {
                console.log(`Migration script stdout: ${data}`);
            });

            pythonProcess.stderr?.on('data', (data) => {
                console.error(`Migration script stderr: ${data}`);
            });

            pythonProcess.on('close', (code) => {
                if (code === 0) {
                    new Notice('✅ Data migration to SQLite completed successfully!');
                    resolve();
                } else {
                    new Notice(`❌ Data migration failed with code ${code}. Check console for details.`, 0);
                    reject(new Error(`Migration failed with code ${code}`));
                }
            });

            pythonProcess.on('error', (err) => {
                new Notice('❌ Failed to start migration script. Check console for details.', 0);
                console.error('Failed to start migration script:', err);
                reject(err);
            });
        });
    }
}