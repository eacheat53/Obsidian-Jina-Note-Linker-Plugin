import { App, Modal } from 'obsidian';

export class ProgressModal extends Modal {
    private progressBar: HTMLElement;
    private statusText: HTMLElement;
    private detailsText: HTMLElement;
    private cancelButton: HTMLElement;
    private onCancel?: () => void;
    
    constructor(app: App, title: string, onCancel?: () => void) {
        super(app);
        this.onCancel = onCancel;
        this.modalEl.addClass('jina-progress-modal');
        this.titleEl.setText(title);
    }
    
    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        
        // 状态文本
        this.statusText = contentEl.createEl('div', { 
            cls: 'jina-progress-status',
            text: '准备中...' 
        });
        
        // 进度条容器
        const progressContainer = contentEl.createDiv('jina-progress-container');
        const progressTrack = progressContainer.createDiv('jina-progress-track');
        this.progressBar = progressTrack.createDiv('jina-progress-bar');
        
        // 详细信息
        this.detailsText = contentEl.createEl('div', { 
            cls: 'jina-progress-details',
            text: '' 
        });
        
        // 取消按钮
        if (this.onCancel) {
            const buttonContainer = contentEl.createDiv('jina-progress-buttons');
            this.cancelButton = buttonContainer.createEl('button', {
                text: '取消操作',
                cls: 'mod-warning'
            });
            this.cancelButton.addEventListener('click', () => {
                this.onCancel?.();
                this.close();
            });
        }
        
        this.addStyles();
    }
    
    updateProgress(current: number, total: number, status: string, details?: string) {
        const percentage = total > 0 ? (current / total) * 100 : 0;
        this.progressBar.style.width = `${percentage}%`;
        this.statusText.textContent = `${status} (${current}/${total})`;
        
        if (details) {
            this.detailsText.textContent = details;
        }
    }
    
    setCompleted(message: string) {
        this.progressBar.style.width = '100%';
        this.statusText.textContent = message;
        this.detailsText.textContent = '';
        
        if (this.cancelButton) {
            this.cancelButton.textContent = '关闭';
            this.cancelButton.removeClass('mod-warning');
            this.cancelButton.addClass('mod-cta');
        }
    }
    
    setError(message: string) {
        this.statusText.textContent = `❌ ${message}`;
        this.progressBar.style.backgroundColor = 'var(--color-red)';
        
        if (this.cancelButton) {
            this.cancelButton.textContent = '关闭';
            this.cancelButton.removeClass('mod-warning');
        }
    }
    
    private addStyles() {
        const styleEl = this.contentEl.createEl('style');
        styleEl.textContent = `
            .jina-progress-modal .modal-content {
                padding: 20px;
                min-width: 400px;
            }
            .jina-progress-status {
                font-size: 16px;
                font-weight: 500;
                margin-bottom: 15px;
                color: var(--text-normal);
            }
            .jina-progress-container {
                margin-bottom: 15px;
            }
            .jina-progress-track {
                width: 100%;
                height: 8px;
                background-color: var(--background-secondary);
                border-radius: 4px;
                overflow: hidden;
            }
            .jina-progress-bar {
                height: 100%;
                background-color: var(--interactive-accent);
                transition: width 0.3s ease;
                width: 0%;
            }
            .jina-progress-details {
                font-size: 14px;
                color: var(--text-muted);
                margin-bottom: 15px;
                min-height: 20px;
            }
            .jina-progress-buttons {
                display: flex;
                justify-content: flex-end;
            }
        `;
    }
    
    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}