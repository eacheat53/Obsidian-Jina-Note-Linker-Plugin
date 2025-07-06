import { Notice, TFile } from 'obsidian';
import { OperationResult } from '../models/interfaces';
import { 
    DEFAULT_OUTPUT_DIR_IN_VAULT, 
    HASH_BOUNDARY_MARKER,
    LINKS_END_MARKER,
    LINKS_START_MARKER, 
    SUGGESTED_LINKS_TITLE 
} from '../models/constants';
import { JinaLinkerSettings } from '../models/settings';
import { FilePathUtils } from '../utils/path-utils';
import { createProcessingError, log } from '../utils/error-handler';
import { CacheManager } from '../utils/cache-manager';
import * as path from 'path';

export class LinkManager {
    constructor(
        private app: any, 
        private settings: JinaLinkerSettings,
        private cacheManager: CacheManager
    ) {}

    async insertAISuggestedLinksIntoNotes(targetFoldersOption: string): Promise<OperationResult<{processedFiles: number, updatedFiles: number}>> {
        log('info', '开始执行：插入AI建议链接');
        log('info', `目标文件夹: ${targetFoldersOption}`);
        
        try {
            // 使用默认输出目录
            const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
            const aiScoresFilePath = FilePathUtils.normalizePath(path.join(outputDirInVault, 'ai_scores.json'));

            // 检查AI评分文件是否存在
            const aiScoresFileExists = await this.app.vault.adapter.exists(aiScoresFilePath);
            if (!aiScoresFileExists) {
                const error = createProcessingError('FILE_NOT_FOUND',
                    `AI评分文件 "${aiScoresFilePath}" 未找到`,
                    '请先运行Python脚本生成AI评分数据');
                return { success: false, error };
            }

            // 读取AI评分数据
            const rawAiScoresData = await this.app.vault.adapter.read(aiScoresFilePath);
            let aiScoresData: any;
            
            try {
                aiScoresData = JSON.parse(rawAiScoresData);
            } catch (parseError: any) {
                const error = createProcessingError('UNKNOWN',
                    '解析AI评分数据文件失败',
                    parseError instanceof Error ? parseError.message : String(parseError));
                return { success: false, error };
            }

            log('info', "开始从JSON文件读取AI评分数据并插入建议链接");
            new Notice('🔄 正在从AI评分数据插入建议链接...', 3000);
            
            const allMarkdownFiles = this.app.vault.getMarkdownFiles().filter(FilePathUtils.isMarkdownFile);
            let processedFileCount = 0;
            let updatedFileCount = 0;

            const targetFolderPaths = targetFoldersOption.split(',').map(p => p.trim()).filter(p => p);
            const shouldProcessAll = targetFolderPaths.length === 0 || (targetFolderPaths.length === 1 && targetFolderPaths[0] === '/');
            log('info', `将为 ${allMarkdownFiles.length} 个 Markdown 文件执行链接插入`, {
                targetFolders: targetFolderPaths.length > 0 ? targetFoldersOption : '仓库根目录'
            });

            // 性能优化：批量处理文件
            const batchSize = 5;
            for (let i = 0; i < allMarkdownFiles.length; i += batchSize) {
                const batch = allMarkdownFiles.slice(i, i + batchSize);
                const batchResults = await Promise.allSettled(
                    batch.map((file: TFile) => this.processFileForLinkInsertionFromJSON(file, targetFolderPaths, shouldProcessAll, aiScoresData))
                );
                
                for (const result of batchResults) {
                    if (result.status === 'fulfilled' && result.value) {
                        processedFileCount++;
                        if (result.value.updated) {
                            updatedFileCount++;
                        }
                    }
                }
                
                // 显示进度
                if (i % 20 === 0) {
                    new Notice(`📊 已处理 ${Math.min(i + batchSize, allMarkdownFiles.length)}/${allMarkdownFiles.length} 个文件`, 2000);
                }
            }
            
            const summaryMessage = `链接插入处理完毕。共检查 ${processedFileCount} 个文件，更新了 ${updatedFileCount} 个文件。`;
            log('info', summaryMessage);
            new Notice(`✅ ${summaryMessage}`, 5000);
            
            return {
                success: true,
                data: { processedFiles: processedFileCount, updatedFiles: updatedFileCount }
            };
            
        } catch (error: any) {
            const processingError = createProcessingError('UNKNOWN',
                '插入建议链接时发生错误',
                error instanceof Error ? error.message : String(error));
            return { success: false, error: processingError };
        }
    }

    // 从JSON文件读取AI评分数据的文件处理逻辑
    private async processFileForLinkInsertionFromJSON(
        file: TFile,
        targetFolderPaths: string[],
        shouldProcessAll: boolean,
        aiScoresData: any
    ): Promise<{processed: boolean, updated: boolean} | null> {
        try {
            // 检查文件是否在目标文件夹中
            let inTargetFolder = shouldProcessAll;
            if (!shouldProcessAll) {
                for (const targetFolder of targetFolderPaths) {
                    const normalizedTarget = targetFolder.endsWith('/') ? targetFolder.slice(0, -1) : targetFolder;
                    const filePathNormalized = file.path;
                    if (filePathNormalized.startsWith(normalizedTarget + '/') || filePathNormalized === normalizedTarget) {
                        inTargetFolder = true;
                        break;
                    }
                }
            }
            
            if (!inTargetFolder) {
                return null;
            }

            // 从JSON数据中获取该文件的AI评分候选
            const candidates = this.getAICandidatesFromJSON(file.path, aiScoresData);
            if (!candidates || candidates.length === 0) {
                return { processed: true, updated: false };
            }

            // 使用缓存读取文件内容
            let fileContent = await this.cacheManager.getCachedFileContent(file, this.app.vault);
            const originalFileContentForComparison = fileContent;

            // 分离frontmatter和正文
            const fmRegex = /^---\s*$\n([\s\S]*?)\n^---\s*$\n?/m;
            const fmMatch = fileContent.match(fmRegex);
            let bodyContent = fileContent;
            let frontmatterPart = '';
           
            if (fmMatch) {
                frontmatterPart = fmMatch[0];
                bodyContent = fileContent.substring(frontmatterPart.length);
            }
            
            // 检查哈希边界标记，若没有则添加
            const boundaryMarker = HASH_BOUNDARY_MARKER;
            let boundaryIndexInBody = bodyContent.indexOf(boundaryMarker);
            
            // 如果没有哈希边界标记，则在正文末尾添加
            if (boundaryIndexInBody === -1) {
                // 找到最后一个非空行
                const lines = bodyContent.split(/\r?\n/);
                let lastNonEmptyLineIndex = -1;
                
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (lines[i].trim().length > 0) {
                        lastNonEmptyLineIndex = i;
                        break;
                    }
                }
                
                if (lastNonEmptyLineIndex !== -1) {
                    // 在最后一个非空行后插入哈希边界标记
                    lines.splice(lastNonEmptyLineIndex + 1, 0, boundaryMarker);
                    bodyContent = lines.join('\n');
                    boundaryIndexInBody = bodyContent.indexOf(boundaryMarker);
                    log('info', `在 ${file.path} 添加了哈希边界标记`);
                } else {
                    log('warn', `${file.path} 没有任何非空行，跳过`);
                    return { processed: false, updated: false };
                }
            }

            // 处理链接插入
            const linksSection = this.generateLinksSection(candidates);
            const updatedBodyContent = this.insertLinksIntoBody(bodyContent, linksSection, boundaryMarker);
            
            const finalContent = frontmatterPart + updatedBodyContent;
            
            // 检查内容是否有变化
            if (finalContent !== originalFileContentForComparison) {
                await this.app.vault.modify(file, finalContent);
                log('info', `更新了 ${file.path} 的建议链接`);
                return { processed: true, updated: true };
            } else {
                return { processed: true, updated: false };
            }
            
        } catch (error: any) {
            log('error', `处理文件 ${file.path} 时发生错误`, error);
            return null;
        }
    }

    // 从JSON数据中获取AI评分候选
    private getAICandidatesFromJSON(filePath: string, aiScoresData: any): any[] {
        try {
            const aiScores = aiScoresData?.ai_scores || {};
            const candidates: any[] = [];
            
            // 遍历AI评分数据，找到以当前文件为源的评分
            for (const [key, scoreEntry] of Object.entries(aiScores)) {
                if (typeof scoreEntry === 'object' && scoreEntry !== null) {
                    const entry = scoreEntry as any;
                    if (entry.source_path === filePath && entry.ai_score >= this.settings.minAiScoreForLinkInsertion) {
                        candidates.push({
                            targetPath: entry.target_path,
                            aiScore: entry.ai_score,
                            jinaScore: entry.jina_similarity
                        });
                    }
                }
            }
            
            // 按AI评分排序，取前N个
            candidates.sort((a: any, b: any) => (b.aiScore || 0) - (a.aiScore || 0));
            return candidates.slice(0, this.settings.maxLinksToInsertPerNote);
            
        } catch (error: any) {
            log('error', `从JSON获取AI候选时发生错误`, error);
            return [];
        }
    }

    // 生成链接部分的内容
    private generateLinksSection(candidates: any[]): string {
        if (!candidates || candidates.length === 0) {
            return '';
        }

        const linksToInsert: string[] = [];
        
        for (const cand of candidates) {
            if (cand && typeof cand === 'object' && cand.targetPath) {
                const targetTFile = this.app.vault.getAbstractFileByPath(cand.targetPath);
                if (targetTFile instanceof TFile) {
                    const linkText = this.app.metadataCache.fileToLinktext(targetTFile, '', true);
                    linksToInsert.push(`- [[${linkText}]]`);
                } else {
                    console.warn(`JinaLinker: 目标文件 ${cand.targetPath} 未找到。跳过此链接。`);
                }
            }
        }

        if (linksToInsert.length === 0) {
            return '';
        }

        const linksMarkdown = linksToInsert.join('\n');
        return `\n${SUGGESTED_LINKS_TITLE}\n${LINKS_START_MARKER}\n${linksMarkdown}\n${LINKS_END_MARKER}`;
    }

    // 将链接部分插入到正文中
    private insertLinksIntoBody(bodyContent: string, linksSection: string, boundaryMarker: string): string {
        // 找到哈希边界标记的位置
        const boundaryIndex = bodyContent.indexOf(boundaryMarker);
        if (boundaryIndex === -1) {
            return bodyContent;
        }

        // 分离哈希边界标记前后的内容
        const contentBeforeBoundary = bodyContent.substring(0, boundaryIndex);
        let contentAfterBoundary = bodyContent.substring(boundaryIndex + boundaryMarker.length);

        // 删除所有现有的建议链接部分
        const linkSectionRegex = new RegExp(`\\s*${this.escapeRegExp(SUGGESTED_LINKS_TITLE)}\\s*${this.escapeRegExp(LINKS_START_MARKER)}[\\s\\S]*?${this.escapeRegExp(LINKS_END_MARKER)}\\s*`, "g");
        
        // 清除所有现有的链接部分（可能有多个）
        let prevContent = '';
        // 循环替换直到内容不再变化
        while (prevContent !== contentAfterBoundary) {
            prevContent = contentAfterBoundary;
            contentAfterBoundary = contentAfterBoundary.replace(linkSectionRegex, '');
        }
        
        contentAfterBoundary = contentAfterBoundary.trim();

        // 构建最终内容
        let finalContent = contentBeforeBoundary + boundaryMarker;

        // 添加新的链接部分（如果有）
        if (linksSection) {
            finalContent += linksSection;
        }

        // 添加剩余内容
        if (contentAfterBoundary.length > 0) {
            finalContent += `\n\n${contentAfterBoundary}`;
        }

        return finalContent;
    }

    // 用于正则表达式的转义
    private escapeRegExp(string: string): string {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\$&');
    }

    // 测试函数，用于验证insertLinksIntoBody函数
    async testInsertLinksIntoBody(testFilePath: string): Promise<void> {
        const testFile = this.app.vault.getAbstractFileByPath(testFilePath);
        if (!(testFile instanceof TFile)) {
            new Notice('测试文件不存在');
            return;
        }
        
        const fileContent = await this.app.vault.read(testFile);
        
        const newLinksSection = `\n## 建议链接\n<!-- LINKS_START -->\n- [[梦是眼皮里的壁画]]\n- [[新的测试链接-${Date.now()}]]\n<!-- LINKS_END -->`;
        
        const boundaryMarker = '<!-- HASH_BOUNDARY -->';
        const processedContent = this.insertLinksIntoBody(fileContent, newLinksSection, boundaryMarker);
        
        const linkSectionCount = (processedContent.match(/## 建议链接/g) || []).length;
        
        await this.app.vault.modify(testFile, processedContent);
        
        new Notice(`测试完成，文件中包含 ${linkSectionCount} 个链接部分，应该为1`);
    }
}