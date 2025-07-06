import { TFile } from 'obsidian';

export class CacheManager {
    private fileContentCache = new Map<string, {content: string, mtime: number}>();
    
    async getCachedFileContent(file: TFile, vault: any): Promise<string> {
        const mtime = file.stat.mtime;
        const cached = this.fileContentCache.get(file.path);
        if (cached && cached.mtime === mtime) {
            return cached.content;
        }
        const content = await vault.read(file);
        this.fileContentCache.set(file.path, {content, mtime});
        
        // 限制缓存大小
        if (this.fileContentCache.size > 100) {
            const firstKey = this.fileContentCache.keys().next().value;
            this.fileContentCache.delete(firstKey);
        }
        
        return content;
    }
    
    clearCache(): void {
        this.fileContentCache.clear();
    }
    
    getCacheSize(): number {
        return this.fileContentCache.size;
    }
}