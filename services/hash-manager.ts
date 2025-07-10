import { Notice, TFile } from 'obsidian';
import * as crypto from 'crypto';
import { HASH_BOUNDARY_MARKER } from '../models/constants';
import { log } from '../utils/error-handler';
import { CacheManager } from '../utils/cache-manager';

export class HashManager {
    constructor(private app: any, private cacheManager: CacheManager) {}

    // 从完整文本中提取用于哈希的正文部分（在 frontmatter 之后，到哈希边界标记之前）
    extractContentForHashingFromText(fullContent: string): string | null {
        let body = fullContent;
        // 去除 frontmatter
        const fmRegex = /^---\s*\n([\s\S]*?)\n---\s*\n?/m;
        const fmMatch = fullContent.match(fmRegex);
        if (fmMatch) {
            body = fullContent.slice(fmMatch[0].length);
        }
        // 找到哈希边界标记位置
        const idx = body.indexOf(HASH_BOUNDARY_MARKER);
        if (idx === -1) return null;
        // 提取边界前内容
        let contentToHash = body.slice(0, idx);
        if (!contentToHash.trim()) {
            return "\n";
        }
        // 规范换行并去尾空白
        contentToHash = contentToHash.replace(/\r\n/g, "\n").replace(/\s+$/, "");
        return contentToHash + "\n";
    }

    // 计算单个文件的内容哈希
    async calculateNoteContentHashForFile(file: TFile): Promise<string | null> {
        try {
            const text = await this.cacheManager.getCachedFileContent(file, this.app.vault);
            const toHash = this.extractContentForHashingFromText(text);
            if (toHash === null) {
                new Notice(`错误: 文件 "${file.path}" 中未找到哈希边界标记 "${HASH_BOUNDARY_MARKER}"`);
                return null;
            }
            const hasher = crypto.createHash('sha256');
            hasher.update(toHash, 'utf-8');
            return hasher.digest('hex');
        } catch (error: any) {
            log('error', `计算文件 Hash 失败 ${file.path}`, error);
            new Notice(`计算文件 "${file.path}" 哈希时出错: ${error.message}`);
            return null;
        }
    }
} 