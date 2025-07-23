import { App, MetadataCache, Notice, TFile, Vault, normalizePath } from 'obsidian';
import { HASH_BOUNDARY_MARKER, LINKS_END_MARKER, LINKS_START_MARKER, SUGGESTED_LINKS_TITLE } from '../models/constants';
import { JinaLinkerSettings } from '../models/settings';
import { OperationResult } from '../models/interfaces';
import { CacheManager } from '../utils/cache-manager';
import { createProcessingError, log } from '../utils/error-handler';
import { NotificationService } from '../utils/notification-service';

/**
 * 查找在哪里插入建议链接
 * - 如果存在 YAML frontmatter, 将链接放在其后
 * - 否则放在文件开头
 */
function findLinkInsertionPosition(content: string): number {
    // 首先查找 frontmatter
    const fmMatch = content.match(/^---\s*\n([\s\S]*?)\n^---\s*$/m);
    if (fmMatch) {
        // 如果有frontmatter，放在其后
        return fmMatch[0].length;
    }

    // 找到正文第一行
    const firstLineMatch = content.match(/^.*$/m);
    if (firstLineMatch) {
        return firstLineMatch[0].length;
    }

    // 否则直接放在开头
    return 0;
}

/**
 * 用于添加哈希边界标记的函数
 * @param file 目标文件
 * @param content 文件内容
 * @returns 添加了边界标记的内容
 */
async function addHashBoundaryToFile(file: TFile, content: string): Promise<string> {
    // 这里我们假设内容已经加载
    if (content.includes(HASH_BOUNDARY_MARKER)) {
        return content;
    }

    // 找到最后一个非空行
    const lines = content.split(/\r?\n/);
    let lastNonEmptyLineIndex = -1;
    
    for (let i = lines.length - 1; i >= 0; i--) {
        if (lines[i].trim().length > 0) {
            lastNonEmptyLineIndex = i;
            break;
        }
    }
    
    if (lastNonEmptyLineIndex !== -1) {
        // 在最后一个非空行后插入哈希边界标记
        lines.splice(lastNonEmptyLineIndex + 1, 0, '', HASH_BOUNDARY_MARKER);
        return lines.join('\n');
    } else {
        // 如果没有非空行，直接添加
        return content + '\n\n' + HASH_BOUNDARY_MARKER;
    }
}

export class LinkManager {
    private notificationService = NotificationService.getInstance();
    
    constructor(
        private app: App, 
        private settings: JinaLinkerSettings,
        private cacheManager: CacheManager
    ) {}

    async insertAISuggestedLinksIntoNotes(targetFoldersOption: string): Promise<OperationResult<{processedFiles: number, updatedFiles: number}>> {
        try {
            log('info', '开始执行：插入AI建议链接');
            log('info', `目标文件夹: ${targetFoldersOption}`);
            
            // 解析目标文件夹路径
            const targetFolders = targetFoldersOption.split(',').map(s => s.trim()).filter(Boolean);
            const shouldProcessAll = targetFoldersOption.trim() === '/' || targetFolders.length === 0;
            const targetFolderPaths = targetFolders.map(f => normalizePath(f));
            
            // 验证文件夹路径
            for (const folderPath of targetFolderPaths) {
                const folder = this.app.vault.getAbstractFileByPath(folderPath);
                if (!folder) {
                    return { 
                        success: false, 
                        error: createProcessingError('UNKNOWN', `文件夹路径不存在: ${folderPath}`) 
                    };
                }
            }
            
            // 获取所有 Markdown 文件
            let allMarkdownFiles = this.app.vault.getMarkdownFiles();
            
            // 根据保存的嵌入和AI评分导入建议链接
            log('info', "开始从JSON文件读取AI评分数据并插入建议链接");
            
            // 读取JSON文件
            const vaultBasePath = (this.app.vault.adapter as any).basePath;
            const aiScoresJsonPath = `${vaultBasePath}/.jina-linker/ai_scores.json`;

            try {
                const aiScoresData = JSON.parse(await window.require('fs').promises.readFile(aiScoresJsonPath, 'utf-8'));
                
                log('info', `将为 ${allMarkdownFiles.length} 个 Markdown 文件执行链接插入`, {
                    targetFolders: targetFolderPaths,
                    shouldProcessAll,
                    aiScoresDataLength: Object.keys(aiScoresData?.ai_scores_by_source || {}).length
                });
                
                let processedCount = 0;
                let updatedCount = 0;
                
                for (const file of allMarkdownFiles) {
                    const result = await this.processFileForLinkInsertionFromJSON(
                        file, 
                        targetFolderPaths, 
                        shouldProcessAll, 
                        aiScoresData
                    );
                    
                    if (result) {
                        if (result.processed) processedCount++;
                        if (result.updated) updatedCount++;
                    }
                }
                
                const summaryMessage = `链接插入完成: 处理了 ${processedCount} 个文件，更新了 ${updatedCount} 个文件`;
                log('info', summaryMessage);
                
                this.notificationService.showNotice(`✅ ${summaryMessage}`);
                
                return { 
                    success: true, 
                    data: { 
                        processedFiles: processedCount, 
                        updatedFiles: updatedCount 
                    } 
                };
                
            } catch (error) {
                console.error('读取或解析 AI 评分 JSON 文件时出错:', error);
                return { 
                    success: false, 
                    error: createProcessingError('UNKNOWN', 'AI评分数据读取失败', String(error)) 
                };
            }
        } catch (error) {
            console.error('插入AI链接时出错:', error);
            return { 
                success: false, 
                error: createProcessingError('UNKNOWN', '未知错误', String(error)) 
            };
        }
    }

    private async processFileForLinkInsertionFromJSON(
        file: TFile,
        targetFolderPaths: string[],
        shouldProcessAll: boolean,
        aiScoresData: any
    ): Promise<{processed: boolean, updated: boolean} | null> {
        try {
            // 检查文件是否在目标文件夹中
            let inTargetFolder = shouldProcessAll;
            if (!inTargetFolder) {
                for (const folderPath of targetFolderPaths) {
                    if (file.path === folderPath || file.path.startsWith(folderPath + '/')) {
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
                    // 删除日志输出
                } else {
                    log('warn', `${file.path} 没有任何非空行，跳过`);
                    return { processed: false, updated: false };
                }
            }

            // 生成链接 markdown
            const linksSection = this.generateLinksSection(candidates);

            // 如果本次没有任何链接需要插入，则保持文件原状，避免误动边界标记
            if (!linksSection) {
                return { processed: true, updated: false };
            }

            // 有链接需要插入才继续
            const updatedBodyContent = this.insertLinksIntoBody(bodyContent, linksSection, boundaryMarker);
            const finalContent = frontmatterPart + updatedBodyContent;

            if (finalContent !== originalFileContentForComparison) {
                await this.app.vault.modify(file, finalContent);
                // 删除日志输出
                return { processed: true, updated: true };
            }

            return { processed: true, updated: false };
            
        } catch (error: any) {
            log('error', `处理文件 ${file.path} 时发生错误`, error);
            return null;
        }
    }

    // 从JSON数据中获取AI评分候选
    private getAICandidatesFromJSON(filePath: string, aiScoresData: any): any[] {
        try {
            const bySource = aiScoresData?.ai_scores_by_source || {};
            const rawList: any[] = bySource[filePath] || [];
            const minScore = this.settings.minAiScoreForLinkInsertion ?? 0;

            const candidates = rawList
                .filter(([_, score]) => (score || 0) >= minScore)
                .slice(0, this.settings.maxLinksToInsertPerNote)
                .map(([targetPath, score]) => ({ targetPath, aiScore: score }));

            return candidates;
            
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