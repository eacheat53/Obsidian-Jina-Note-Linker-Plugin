import { Notice, TFile, TFolder, normalizePath } from 'obsidian';
import { HASH_BOUNDARY_MARKER } from '../models/constants';
import { OperationResult } from '../models/interfaces';
import { log } from '../utils/error-handler';
import { CacheManager } from '../utils/cache-manager';
// HashManager 仅在旧的哈希更新功能中使用，已移除

export class FileProcessor {
    constructor(private app: any, private cacheManager: CacheManager) {}

    // 递归获取文件夹中的所有Markdown文件
    getMarkdownFilesInFolder(folder: TFolder): TFile[] {
        const allFiles = this.app.vault.getAllLoadedFiles();
        return allFiles.filter((file: any) =>
            file instanceof TFile && file.extension === 'md' && file.path.startsWith(folder.path)
        ) as TFile[];
    }

    // 旧版更新哈希功能已废弃，保留占位避免潜在引用错误。

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