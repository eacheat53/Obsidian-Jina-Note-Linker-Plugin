import { Notice, TFile, TFolder, normalizePath } from 'obsidian';
import * as path from 'path';
import * as crypto from 'crypto';
import { DEFAULT_OUTPUT_DIR_IN_VAULT, EMBEDDINGS_FILE_NAME, HASH_BOUNDARY_MARKER } from '../models/constants';
import { OperationResult } from '../models/interfaces';
import { createProcessingError, log } from '../utils/error-handler';
import { CacheManager } from '../utils/cache-manager';
import { HashManager } from './ash-manager';

export class FileProcessor {
    constructor(private app: any, private cacheManager: CacheManager) {}

    // 递归获取文件夹中的所有Markdown文件
    getMarkdownFilesInFolder(folder: TFolder): TFile[] {
        const allFiles = this.app.vault.getAllLoadedFiles();
        return allFiles.filter((file: any) =>
            file instanceof TFile && file.extension === 'md' && file.path.startsWith(folder.path)
        ) as TFile[];
    }

    // 更新嵌入JSON和文件frontmatter中的哈希值
    async updateHashesInEmbeddingsFile(targetRelativePaths: string[]): Promise<void> {
        new Notice(`开始处理 ${targetRelativePaths.length} 个路径，更新哈希值...`);
        const outputDirInVault = DEFAULT_OUTPUT_DIR_IN_VAULT;
        const embeddingsFilePath = normalizePath(path.join(outputDirInVault, EMBEDDINGS_FILE_NAME));
        let embeddingsData: any;
        try {
            if (!(await this.app.vault.adapter.exists(embeddingsFilePath))) {
                new Notice(`错误: 嵌入文件 "${embeddingsFilePath}" 未找到。`);
                return;
            }
            const rawData = await this.app.vault.adapter.read(embeddingsFilePath);
            embeddingsData = JSON.parse(rawData);
            if (!embeddingsData.files || typeof embeddingsData.files !== 'object') {
                throw new Error("嵌入文件结构不正确，缺少 'files' 对象。");
            }
        } catch (error: any) {
            new Notice(`读取或解析嵌入文件 "${embeddingsFilePath}" 失败: ${error.message}`);
            return;
        }

        const hashManager = new HashManager(this.app, this.cacheManager);
        let updatedJsonCount = 0, updatedFrontmatterCount = 0, notFoundCount = 0, hashFailCount = 0, noChangeCount = 0;

        // 收集要处理的文件
        let files: TFile[] = [];
        for (const rel of targetRelativePaths) {
            const norm = normalizePath(rel);
            const af = this.app.vault.getAbstractFileByPath(norm);
            if (af instanceof TFolder) {
                files.push(...this.getMarkdownFilesInFolder(af));
            } else if (af instanceof TFile && af.extension === 'md') {
                files.push(af);
            }
        }
        files = Array.from(new Set(files));

        for (const tFile of files) {
            const relPath = tFile.path;
            const newHash = await hashManager.calculateNoteContentHashForFile(tFile);
            if (!newHash) { hashFailCount++; continue; }

            if (embeddingsData.files.hasOwnProperty(relPath)) {
                if (embeddingsData.files[relPath].hash !== newHash) {
                    embeddingsData.files[relPath].hash = newHash;
                    embeddingsData.files[relPath].last_hash_updated_at = new Date().toISOString();
                    updatedJsonCount++;
                }
            } else {
                notFoundCount++;
            }

            try {
                const content = await this.cacheManager.getCachedFileContent(tFile, this.app.vault);
                const fmRegex = /^---\s*\n([\s\S]*?)\n---\s*\n/;
                const fmMatch = content.match(fmRegex);
                let newContent: string;
                if (fmMatch) {
                    const fmBody = fmMatch[1];
                    const jinaRegex = /^jina_hash:\s*.*$/m;
                    if (jinaRegex.test(fmBody)) {
                        newContent = content.replace(jinaRegex, `jina_hash: ${newHash}`);
                    } else {
                        const replaced = `${fmBody}\njina_hash: ${newHash}`;
                        newContent = content.replace(fmRegex, `---\n${replaced}\n---\n`);
                    }
                } else {
                    newContent = `---\njina_hash: ${newHash}\n---\n\n${content}`;
                }
                if (newContent !== content) {
                    await this.app.vault.modify(tFile, newContent);
                    updatedFrontmatterCount++;
                } else {
                    noChangeCount++;
                }
            } catch (error: any) {
                log('error', `更新前置属性失败 ${relPath}`, error);
            }
        }

        if (updatedJsonCount > 0) {
            try {
                await this.app.vault.adapter.write(embeddingsFilePath, JSON.stringify(embeddingsData, null, 4));
            } catch (error: any) {
                new Notice(`写入嵌入文件失败: ${error.message}`);
                return;
            }
        }

        new Notice(`更新完成：JSON(${updatedJsonCount}) frontmatter(${updatedFrontmatterCount}) 未更改(${noChangeCount}) 未找到(${notFoundCount}) 失败(${hashFailCount})`);
    }

    // 批量添加哈希边界标记
    async addHashBoundaryMarkers(targetRelativePaths: string): Promise<OperationResult<{processedFiles: number, updatedFiles: number}>> {
        new Notice('🔄 开始批量添加哈希边界标记...');
        let files: TFile[] = [];
        if (!targetRelativePaths.trim()) {
            files = this.app.vault.getMarkdownFiles();
        } else {
            const arr = targetRelativePaths.split(',').map(s => s.trim()).filter(s => s);
            for (const rel of arr) {
                const norm = normalizePath(rel);
                const af = this.app.vault.getAbstractFileByPath(norm);
                if (af instanceof TFolder) {
                    files.push(...this.getMarkdownFilesInFolder(af));
                } else if (af instanceof TFile && af.extension === 'md') {
                    files.push(af);
                }
            }
        }
        files = Array.from(new Set(files));

        let processed = 0, updated = 0;
        for (const file of files) {
            processed++;
            try {
                const content = await this.cacheManager.getCachedFileContent(file, this.app.vault);
                if (content.includes(HASH_BOUNDARY_MARKER)) continue;
                const fmRegex = /^---\s*\n([\s\S]*?)\n---\s*\n?/m;
                const match = content.match(fmRegex);
                let body = match ? content.slice(match[0].length) : content;
                const lines = body.split(/\r?\n/);
                let lastIdx = -1;
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (lines[i].trim().length > 0) { lastIdx = i; break; }
                }
                if (lastIdx < 0) lastIdx = 0;
                lines.splice(lastIdx + 1, 0, '', HASH_BOUNDARY_MARKER);
                const newBody = lines.join('\n');
                const newText = match ? match[0] + newBody : newBody;
                await this.app.vault.modify(file, newText);
                updated++;
            } catch (error: any) {
                log('error', `添加边界标记失败 ${file.path}`, error);
            }
        }
        return { success: true, data: { processedFiles: processed, updatedFiles: updated } };
    }
}