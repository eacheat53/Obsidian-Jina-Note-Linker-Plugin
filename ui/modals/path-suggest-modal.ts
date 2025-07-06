import { App, FuzzySuggestModal, FuzzyMatch } from 'obsidian';

export class PathSuggestModal extends FuzzySuggestModal<string> {
    paths: string[];
    inputText: string;
    callback: (selectedPath: string) => void;
    
    constructor(app: App, paths: string[], inputText: string, callback: (selectedPath: string) => void) {
        super(app);
        this.paths = paths;
        this.inputText = inputText || '';
        this.callback = callback;
        this.setPlaceholder('选择文件或文件夹路径');
        
        // 设置初始查询文本
        if (this.inputText) {
            this.inputEl.value = this.inputText;
            // 触发输入事件以显示初始结果
            this.inputEl.dispatchEvent(new Event('input'));
        }
    }
    
    getItems(): string[] {
        return this.paths;
    }
    
    getItemText(path: string): string {
        return path;
    }
    
    onChooseItem(path: string, evt: MouseEvent | KeyboardEvent): void {
        this.callback(path);
    }
    
    renderSuggestion(item: FuzzyMatch<string>, el: HTMLElement): void {
        const match = item.item;
        el.setText(match);
        
        // 如果路径以/结尾，表示是文件夹，添加特殊样式
        if (match.endsWith('/')) {
            el.addClass('jina-folder-path');
            const iconEl = el.createSpan({cls: 'jina-folder-icon'});
            iconEl.setText('📁 ');
            el.prepend(iconEl);
        } else {
            el.addClass('jina-file-path');
            const iconEl = el.createSpan({cls: 'jina-file-icon'});
            iconEl.setText('📄 ');
            el.prepend(iconEl);
        }
    }
}