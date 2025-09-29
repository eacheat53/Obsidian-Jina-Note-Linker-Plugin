import { App, TFile, parseYaml, stringifyYaml } from 'obsidian';
import { JinaLinkerSettings } from '../models/settings';
import { log } from '../utils/error-handler';
import { NotificationService } from '../utils/notification-service';
import * as crypto from 'crypto';

/**
 * UUID Manager Service
 * 
 * Handles UUID generation, validation, and management for notes with exclusion support.
 * Follows the modular service architecture pattern consistent with other managers.
 */
export class UuidManager {
    private app: App;
    private settings: JinaLinkerSettings;
    private notificationService: NotificationService;

    constructor(app: App, settings: JinaLinkerSettings) {
        this.app = app;
        this.settings = settings;
        this.notificationService = NotificationService.getInstance();
    }

    /**
     * Ensures a note has a unique UUID, following exclusion rules
     * @param file The TFile to process
     * @returns Promise<void>
     */
    async ensureUniqueNoteId(file: TFile): Promise<void> {
        try {
            // Check if file should be excluded
            if (this.shouldExcludeFile(file.path)) {
                log('info', `Skipping UUID processing for excluded file: ${file.path}`);
                return;
            }

            // Read file content
            const content = await this.app.vault.read(file);
            
            // Parse frontmatter with more precise regex matching
            const fmRegex = /^---\s*?\n([\s\S]*?)\n---\s*?\n/;
            const fmMatch = content.match(fmRegex);
            
            if (!fmMatch) {
                // No frontmatter, add one with note_id
                const noteId = this.generateUniqueId();
                const newContent = `---
note_id: ${noteId}
---

${content}`;
                await this.app.vault.modify(file, newContent);
                log('info', `Added frontmatter and note_id to new file ${file.path}: ${noteId}`);
                return;
            }
            
            // Extract frontmatter parts and remaining content
            const fullFmMatch = fmMatch[0];  // Complete frontmatter including separators
            const fmContent = fmMatch[1];    // Frontmatter content only (without ---)
            const contentAfterFm = content.slice(fullFmMatch.length);
            
            try {
                // Parse frontmatter using Obsidian's parseYaml
                const fmData = parseYaml(fmContent) || {};
                
                // Check if note_id exists
                if (!fmData.note_id) {
                    // Add note_id
                    fmData.note_id = this.generateUniqueId();
                    
                    // Generate new frontmatter using stringifyYaml
                    const newFmContent = stringifyYaml(fmData);
                    const newContent = `---\n${newFmContent}---\n${contentAfterFm}`;
                    
                    await this.app.vault.modify(file, newContent);
                    log('info', `Added note_id to new file ${file.path}: ${fmData.note_id}`);
                } else if (typeof fmData.note_id === 'string' && this.isTemplateId(fmData.note_id)) {
                    // If existing ID is template-generated (e.g., has specific prefix or format characteristics), replace it
                    const oldId = fmData.note_id;
                    fmData.note_id = this.generateUniqueId();
                    
                    // Generate new frontmatter using stringifyYaml
                    const newFmContent = stringifyYaml(fmData);
                    const newContent = `---\n${newFmContent}---\n${contentAfterFm}`;
                    
                    await this.app.vault.modify(file, newContent);
                    log('info', `Replaced template ID ${oldId} with new ID for file ${file.path}: ${fmData.note_id}`);
                }
                
            } catch (yamlError) {
                // YAML parsing error handling
                log('error', `Error parsing frontmatter for file ${file.path}`, yamlError);
                
                // Try simple approach
                if (!fmContent.includes('note_id:')) {
                    const noteId = this.generateUniqueId();
                    const newFmContent = fmContent.trim() + `\nnote_id: ${noteId}`;
                    const newContent = content.replace(fmContent, newFmContent);
                    await this.app.vault.modify(file, newContent);
                    log('info', `Added note_id using simple processing for file ${file.path}: ${noteId}`);
                }
            }
        } catch (error) {
            log('error', `Error processing note_id for file ${file.path}`, error);
            this.notificationService.showError(`Error adding ID to file ${file.path}`);
        }
    }

    /**
     * Checks if a file should be excluded from UUID processing based on configuration
     * @param filePath The path of the file to check
     * @returns boolean indicating if file should be excluded
     */
    shouldExcludeFile(filePath: string): boolean {
        // Check excluded folders
        const excludedFolders = this.settings.excludedFolders
            .split(',')
            .map(folder => folder.trim())
            .filter(folder => folder.length > 0);

        for (const folder of excludedFolders) {
            if (filePath.startsWith(folder + '/') || filePath === folder || filePath.includes('/' + folder + '/')) {
                return true;
            }
        }

        // Check excluded file patterns
        const excludedPatterns = this.settings.excludedFilesPatterns
            .split(',')
            .map(pattern => pattern.trim())
            .filter(pattern => pattern.length > 0);

        const fileName = filePath.split('/').pop() || '';
        const fileNameWithoutExt = fileName.replace(/\.[^/.]+$/, '');

        for (const pattern of excludedPatterns) {
            if (this.matchesPattern(fileName, pattern) || this.matchesPattern(fileNameWithoutExt, pattern)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Checks if an ID is a template-generated ID that should be replaced
     * @param id The ID to check
     * @returns boolean indicating if ID is template-generated
     */
    private isTemplateId(id: string): boolean {
        // These conditions can be adjusted based on actual requirements
        return id.includes('template') || 
               id === '00000000-0000-0000-0000-000000000000' ||
               id.match(/^[a-f0-9]{8}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{12}$/i) === null;
    }

    /**
     * Generates a unique UUID
     * @returns string A new UUID
     */
    generateUniqueId(): string {
        try {
            return crypto.randomUUID();
        } catch (e) {
            // Fallback approach, generate a simplified UUID format
            const random = () => Math.floor(Math.random() * 1e10).toString(16);
            return `${random()}-${random()}-${random()}-${random()}`;
        }
    }

    /**
     * Validates if a string is a properly formatted UUID
     * @param uuid The string to validate
     * @returns boolean indicating if string is valid UUID
     */
    isValidUuid(uuid: string): boolean {
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
        return uuidRegex.test(uuid);
    }

    /**
     * Processes multiple files to ensure they all have unique UUIDs
     * @param files Array of TFiles to process
     * @returns Promise with processing results
     */
    async ensureUniqueIdsForFiles(files: TFile[]): Promise<{processed: number, updated: number, skipped: number}> {
        let processed = 0;
        let updated = 0;
        let skipped = 0;

        for (const file of files) {
            if (file.extension !== 'md') {
                continue;
            }

            processed++;

            if (this.shouldExcludeFile(file.path)) {
                skipped++;
                continue;
            }

            const originalContent = await this.app.vault.read(file);
            await this.ensureUniqueNoteId(file);
            const newContent = await this.app.vault.read(file);

            if (originalContent !== newContent) {
                updated++;
            }
        }

        return { processed, updated, skipped };
    }

    /**
     * Pattern matching helper for file exclusion
     * @param text Text to match against
     * @param pattern Pattern to match (supports wildcards)
     * @returns boolean indicating if pattern matches
     */
    private matchesPattern(text: string, pattern: string): boolean {
        // Handle exact match
        if (pattern === text) {
            return true;
        }

        // Handle ^ prefix (exact start match)
        if (pattern.startsWith('^') && pattern.endsWith('$')) {
            const exactPattern = pattern.slice(1, -1);
            return text === exactPattern;
        }

        // Handle * wildcards
        if (pattern.includes('*')) {
            const regexPattern = pattern
                .replace(/[.+?^${}()|[\]\\]/g, '\\$&') // Escape regex special chars
                .replace(/\*/g, '.*'); // Replace * with .*
            
            const regex = new RegExp(`^${regexPattern}$`, 'i');
            return regex.test(text);
        }

        // Handle partial match
        return text.toLowerCase().includes(pattern.toLowerCase());
    }

    /**
     * Gets statistics about UUIDs in the vault
     * @param scanPath Optional path to scan (defaults to entire vault)
     * @returns Promise with UUID statistics
     */
    async getUuidStatistics(scanPath?: string): Promise<{
        totalFiles: number;
        filesWithUuid: number;
        filesWithoutUuid: number;
        excludedFiles: number;
        duplicateUuids: number;
        invalidUuids: number;
    }> {
        const allFiles = scanPath ? 
            this.app.vault.getMarkdownFiles().filter(f => f.path.startsWith(scanPath)) :
            this.app.vault.getMarkdownFiles();

        let totalFiles = 0;
        let filesWithUuid = 0;
        let filesWithoutUuid = 0;
        let excludedFiles = 0;
        let invalidUuids = 0;
        const uuidMap = new Map<string, number>();

        for (const file of allFiles) {
            totalFiles++;

            if (this.shouldExcludeFile(file.path)) {
                excludedFiles++;
                continue;
            }

            try {
                const content = await this.app.vault.read(file);
                const fmRegex = /^---\s*?\n([\s\S]*?)\n---\s*?\n/;
                const fmMatch = content.match(fmRegex);

                if (fmMatch) {
                    const fmData = parseYaml(fmMatch[1]) || {};
                    if (fmData.note_id) {
                        filesWithUuid++;
                        
                        // Check UUID validity
                        if (!this.isValidUuid(fmData.note_id)) {
                            invalidUuids++;
                        }

                        // Track duplicates
                        const count = uuidMap.get(fmData.note_id) || 0;
                        uuidMap.set(fmData.note_id, count + 1);
                    } else {
                        filesWithoutUuid++;
                    }
                } else {
                    filesWithoutUuid++;
                }
            } catch (error) {
                log('error', `Error reading file ${file.path} for UUID statistics`, error);
            }
        }

        // Count duplicate UUIDs
        let duplicateUuids = 0;
        for (const [uuid, count] of uuidMap.entries()) {
            if (count > 1) {
                duplicateUuids += count;
            }
        }

        return {
            totalFiles,
            filesWithUuid,
            filesWithoutUuid,
            excludedFiles,
            duplicateUuids,
            invalidUuids
        };
    }
}