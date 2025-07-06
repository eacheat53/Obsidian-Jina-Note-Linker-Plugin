import { normalizePath, TFile } from 'obsidian';
import * as path from 'path';

export class FilePathUtils {
    static normalizePath(filePath: string): string {
        return normalizePath(filePath);
    }
    
    static isMarkdownFile(file: TFile): boolean {
        return file.extension === 'md';
    }
    
    static getRelativePath(file: TFile, basePath: string): string {
        return path.relative(basePath, file.path);
    }
    
    static validatePath(inputPath: string): boolean {
        if (inputPath.includes('..') || inputPath.includes('~')) {
            return false;
        }
        return true;
    }
    
    static sanitizePathForLog(inputPath: string): string {
        return inputPath.replace(/\\Users\\[^\\]+/, '/Users/***');
    }
}