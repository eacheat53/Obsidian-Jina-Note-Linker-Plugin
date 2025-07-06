import { Notice } from 'obsidian';
import { ProcessingError } from '../models/interfaces';

export function createProcessingError(
    type: ProcessingError['type'], 
    message: string, 
    details?: string
): ProcessingError {
    const suggestions: string[] = [];
    
    switch (type) {
        case 'PYTHON_NOT_FOUND':
            suggestions.push('请检查Python路径设置是否正确');
            suggestions.push('确保Python已正确安装并在PATH中');
            break;
        case 'API_KEY_INVALID':
            suggestions.push('请检查API密钥是否正确配置');
            suggestions.push('确认API密钥有效且未过期');
            break;
        // 其他错误类型处理...
    }
    
    return { type, message, details, suggestions };
}

export function handleError(error: ProcessingError): void {
    new Notice(`❌ ${error.message}`, 0);
    
    if (error.suggestions && error.suggestions.length > 0) {
        setTimeout(() => {
            error.suggestions!.forEach((suggestion, index) => {
                new Notice(`💡 建议${index + 1}: ${suggestion}`, 8000);
            });
        }, 1000);
    }
    
    console.error(`[${new Date().toISOString()}] [ERROR] JinaLinker: ${error.message}`, error);
}

export function log(level: 'info' | 'warn' | 'error', message: string, data?: any): void {
    const timestamp = new Date().toISOString();
    const logEntry = `[${timestamp}] [${level.toUpperCase()}] JinaLinker: ${message}`;
    
    switch (level) {
        case 'error':
            console.error(logEntry, data);
            break;
        case 'warn':
            console.warn(logEntry, data);
            break;
        default:
            console.log(logEntry, data);
    }
}