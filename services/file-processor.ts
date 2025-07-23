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
                
                // 检查文件是否已经包含哈希边界标记
                if (content.includes(HASH_BOUNDARY_MARKER)) {
                    // 删除日志输出，直接跳过
                    continue;
                }
                
                // 分离frontmatter和正文
                const fmRegex = /^---\s*\n([\s\S]*?)\n---\s*\n?/m;
                const match = content.match(fmRegex);
                let frontmatterPart = match ? match[0] : '';
                let body = match ? content.slice(match[0].length) : content;
                
                // 找到正文最后一个非空行
                const lines = body.split(/\r?\n/);
                let lastIdx = -1;
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (lines[i].trim().length > 0) { lastIdx = i; break; }
                }
                if (lastIdx < 0) lastIdx = 0;
                
                // 在最后一个非空行后添加哈希边界标记
                lines.splice(lastIdx + 1, 0, '', HASH_BOUNDARY_MARKER);
                const newBody = lines.join('\n');
                const newText = frontmatterPart + newBody;
                
                // 写入修改后的内容
                await this.app.vault.modify(file, newText);
                updated++;
                
                // 更新缓存
                this.cacheManager.getCachedFileContent(file, this.app.vault, true);
                
        } catch (error: any) {
                log('error', `添加边界标记失败 ${file.path}`, error);
            }
        }
        return { success: true, data: { processedFiles: processed, updatedFiles: updated } };
    }

    async addHashBoundaryToFile(file: TFile): Promise<boolean> {
        try {
            const content = await this.app.vault.read(file);

            // 检查文件是否已经包含哈希边界标记
            if (content.includes(HASH_BOUNDARY_MARKER)) {
                // 移除此处的日志输出
                return false; // 已有标记，不需要添加
            }

            // 处理Front Matter
            const fmMatch = content.match(/^---\s*$[\s\S]*?^---\s*$/m);
            let updatedContent: string;

            if (fmMatch) {
                const fm = fmMatch[0];
                const bodyStart = content.indexOf(fm) + fm.length;
                const body = content.substring(bodyStart).trim();
                updatedContent = `${fm}\n\n${body}\n\n${HASH_BOUNDARY_MARKER}`;
            } else {
                // 没有 Front Matter，直接在文件末尾添加边界标记
                updatedContent = `${content.trim()}\n\n${HASH_BOUNDARY_MARKER}`;
            }

            // 更新文件内容
            await this.app.vault.modify(file, updatedContent);
            
            // 更新缓存
            await this.cacheManager.getCachedFileContent(file, this.app.vault, true);

            return true;
        } catch (error) {
            log('error', `在文件 ${file.path} 中添加哈希边界标记时出错`, error);
            return false;
        }
    }
}