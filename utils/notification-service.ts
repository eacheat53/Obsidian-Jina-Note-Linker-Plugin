import { Notice } from 'obsidian';

/**
 * 通知服务 - 用于管理并优化Obsidian中的通知显示
 * 解决弹窗太多的问题
 */
export class NotificationService {
    // 单例模式
    private static instance: NotificationService;
    
    // 活动通知
    private activeNotice: Notice | null = null;
    private progressNotice: Notice | null = null;
    
    // 最后通知时间戳，用于限制通知频率
    private lastNoticeTime = 0;
    private minNoticeInterval = 1000; // 最小通知间隔（毫秒）
    
    // 进度通知相关
    private currentOperation: string = '';
    private operationStartTime: number = 0;
    private totalItems: number = 0;
    private processedItems: number = 0;
    private noticeDebounceTimer: NodeJS.Timeout | null = null;
    
    private constructor() {}
    
    /**
     * 获取通知服务实例
     */
    public static getInstance(): NotificationService {
        if (!NotificationService.instance) {
            NotificationService.instance = new NotificationService();
        }
        return NotificationService.instance;
    }
    
    /**
     * 显示通知
     * @param message 通知消息
     * @param duration 持续时间（毫秒），0表示永久显示直到用户关闭
     */
    public showNotice(message: string, duration: number = 3000): void {
        // 关闭先前的通知
        if (this.activeNotice) {
            this.activeNotice.hide();
            this.activeNotice = null;
        }
        
        const now = Date.now();
        if (now - this.lastNoticeTime < this.minNoticeInterval) {
            // 通知太频繁，忽略
            return;
        }
        
        this.lastNoticeTime = now;
        this.activeNotice = new Notice(message, duration);
    }
    
    /**
     * 开始一个进度操作
     * @param operationName 操作名称
     * @param totalItems 总项目数
     */
    public startProgress(operationName: string, totalItems: number): void {
        this.currentOperation = operationName;
        this.operationStartTime = Date.now();
        this.totalItems = totalItems;
        this.processedItems = 0;
        
        if (this.progressNotice) {
            this.progressNotice.hide();
        }
        
        this.progressNotice = new Notice(`📊 ${operationName} (0/${totalItems})`, 0);
    }
    
    /**
     * 更新进度
     * @param processed 已处理的项目数
     * @param message 附加消息
     */
    public updateProgress(processed: number, message: string = ''): void {
        this.processedItems = processed;
        
        // 使用去抖动减少通知更新频率
        if (this.noticeDebounceTimer) {
            clearTimeout(this.noticeDebounceTimer);
        }
        
        this.noticeDebounceTimer = setTimeout(() => {
            // 只在进度有显著变化或超过一定时间后更新通知
            if (processed === this.totalItems || processed % Math.max(1, Math.floor(this.totalItems / 10)) === 0) {
                const percent = Math.floor((processed / this.totalItems) * 100);
                
                if (this.progressNotice) {
                    this.progressNotice.hide();
                }
                
                const progressText = message ? 
                    `📊 ${this.currentOperation} (${processed}/${this.totalItems}, ${percent}%) - ${message}` : 
                    `📊 ${this.currentOperation} (${processed}/${this.totalItems}, ${percent}%)`;
                
                this.progressNotice = new Notice(progressText, 0);
            }
        }, 300);
    }
    
    /**
     * 完成进度操作
     * @param message 完成消息
     */
    public completeProgress(message: string): void {
        const duration = ((Date.now() - this.operationStartTime) / 1000).toFixed(1);
        
        if (this.progressNotice) {
            this.progressNotice.hide();
            this.progressNotice = null;
        }
        
        if (this.noticeDebounceTimer) {
            clearTimeout(this.noticeDebounceTimer);
            this.noticeDebounceTimer = null;
        }
        
        const completeMessage = `✅ ${message} (用时: ${duration}秒)`;
        this.showNotice(completeMessage, 5000);
    }
    
    /**
     * 显示错误消息
     * @param message 错误消息
     */
    public showError(message: string): void {
        if (this.progressNotice) {
            this.progressNotice.hide();
            this.progressNotice = null;
        }
        
        const errorMessage = `❌ ${message}`;
        this.showNotice(errorMessage, 0); // 错误信息保持显示直到用户关闭
    }
} 