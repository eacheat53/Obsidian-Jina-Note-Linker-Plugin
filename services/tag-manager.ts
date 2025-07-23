import { App, Notice, TFile, parseYaml, stringifyYaml } from 'obsidian';
import { JinaLinkerSettings } from '../models/settings';
import { CacheManager } from '../utils/cache-manager';
import { log } from '../utils/error-handler';
import { HASH_BOUNDARY_MARKER } from '../models/constants';

export class TagManager {
    constructor(private app: App, private settings: JinaLinkerSettings, private cacheManager: CacheManager) {}

    async insertAIGeneratedTagsIntoNotes(targetFoldersOption: string): Promise<{processed:number, updated:number}> {
        const vaultBase = (this.app.vault.adapter as any).basePath || '';
        const jsonPath = `${vaultBase}/.jina-linker/ai_tags.json`;
        let data: any = {};
        try {
            data = JSON.parse(await window.require('fs').promises.readFile(jsonPath, 'utf-8'));
        } catch (e) {
            log('warn', '读取 ai_tags.json 失败', e);
            return {processed:0,updated:0};
        }
        const tagMap: Record<string,string[]> = data.ai_tags_by_note || {};
        const targetFolders = targetFoldersOption.split(',').map(s=>s.trim()).filter(Boolean);
        const shouldProcessAll = targetFoldersOption.trim()==='/' || targetFolders.length===0;

        let processed = 0, updated = 0;
        for(const filePath of Object.keys(tagMap)){
            if(!shouldProcessAll){
                const inFolder = targetFolders.some(f=> filePath.startsWith(f.endsWith('/')?f:f+'/') || filePath===f);
                if(!inFolder) continue;
            }
            const file = this.app.vault.getAbstractFileByPath(filePath);
            if(!(file instanceof TFile)) continue;
            const tagsToInsert = tagMap[filePath].slice(0,this.settings.maxTagsPerNote);
            if(!tagsToInsert.length) continue;

            let content = await this.cacheManager.getCachedFileContent(file,this.app.vault);
            
            // 检查哈希边界标记位置，以便后续保留其后内容
            const hashBoundaryIndex = content.indexOf(HASH_BOUNDARY_MARKER);
            let contentAfterBoundary = '';
            
            if (hashBoundaryIndex !== -1) {
                // 保存哈希边界标记及其后的所有内容
                contentAfterBoundary = content.substring(hashBoundaryIndex);
                // 截取只包含边界标记之前内容的部分
                content = content.substring(0, hashBoundaryIndex);
                // 删除此日志输出
            }
            
            // 处理frontmatter
            const fmRegex = /^---\s*$[\s\S]*?^---\s*$\n?/m;
            let fm = '';
            if(fmRegex.test(content)){
                fm = content.match(fmRegex)![0];
            } else {
                fm = '---\n---\n';
                content = fm + content;
            }
            const body = content.slice(fm.length);
            const fmObj = fmRegex.test(content)? parseYaml(fm.replace(/^---\s*|---\s*$/g,'')) || {} : {};
            let tagsArr: string[] = Array.isArray((fmObj as any).tags)? (fmObj as any).tags: [];
            const beforeLen = tagsArr.length;
            for(const t of tagsToInsert){ if(!tagsArr.includes(t)) tagsArr.push(t); }
            if(tagsArr.length===beforeLen) { 
                processed++; 
                continue; 
            }
            (fmObj as any).tags = tagsArr;
            const newFm = `---\n${stringifyYaml(fmObj).trim()}\n---\n`;
            
            // 拼接新内容，确保保留哈希边界及其后内容
            let newContent = newFm + body;
            
            // 如果有哈希边界内容，添加回去
            if (contentAfterBoundary) {
                newContent = newContent.trimEnd() + '\n\n' + contentAfterBoundary;
            }
            
            await this.app.vault.modify(file, newContent);
            
            // 缓存简单替换
            // 无 updateCache 方法, 直接放入缓存Map
            (this.cacheManager as any).fileContentCache?.set(file.path,{content:newContent,mtime:file.stat.mtime});
            processed++; updated++;
        }
        new Notice(`AI 标签写入完成：处理 ${processed} 文件，更新 ${updated}`);
        return {processed,updated};
    }
} 