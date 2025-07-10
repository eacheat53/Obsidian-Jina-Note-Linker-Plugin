import { AIModelConfig, AIProvider } from './interfaces';
import { DEFAULT_AI_MODELS } from './constants';

export interface JinaLinkerSettings {
    pythonPath: string;
    jinaApiKey: string;
    aiModels: {
        deepseek: AIModelConfig;
        openai: AIModelConfig;
        claude: AIModelConfig;
        gemini: AIModelConfig;
        custom: AIModelConfig;
    };
    selectedAIProvider: AIProvider;
    similarityThreshold: number;
    excludedFolders: string;
    excludedFilesPatterns: string;
    defaultScanPath: string;
    jinaModelName: string;
    maxCharsForJina: number;
    maxContentLengthForAI: number;
    maxCandidatesPerSourceForAIScoring: number;
    minAiScoreForLinkInsertion: number;
    maxLinksToInsertPerNote: number;
    dataMigrationCompleted: boolean;
    customScoringPrompt: string;
    useCustomScoringPrompt: boolean;
    // 批量处理设置
    maxPairsPerRequest: number;   // 每次API请求的最大笔记对数
    maxCharsPerNote: number;      // 每个笔记在AI评分时的最大字符数
    maxTotalCharsPerRequest: number;  // 每次API请求的最大总字符数
    // AI 标签生成
    tagsMode: 'force' | 'smart' | 'skip';
    maxTagsPerNote: number;
    useCustomTagPrompt: boolean;
    customTagPrompt: string;
}

// 默认评分提示词
export const DEFAULT_SCORING_PROMPT = `作为笔记关联性评分专家，请评估以下多对内容的关联度。这些内容可能包括知识笔记、诗歌创作、灵感片段、散文、情感记录等多样化形式。对每对内容给出0-10的整数评分，基于以下全面标准：

【评分标准：】
10分 - 深度关联：
  • 内容间存在明显的思想、情感或意象共鸣
  • 一篇内容直接启发、延伸或回应另一篇
  • 两篇形成完整的表达整体，共同构建一个更丰富的意境或思想
  • 同时阅读会产生"啊哈"时刻，带来新的领悟

8-9分 - 强烈关联：
  • 共享核心情感、意象或主题
  • 表达相似的思想但通过不同角度或形式
  • 创作背景或灵感来源紧密相连
  • 一篇可以深化对另一篇的理解和欣赏

6-7分 - 明显关联：
  • 存在清晰的主题或情绪连接
  • 使用相似的意象或表达方式
  • 关联点足够丰富，能激发新的思考
  • 并置阅读能够丰富整体体验

4-5分 - 中等关联：
  • 有一些共通元素，但整体走向不同
  • 某些片段或意象存在呼应，但不是主体
  • 关联更加微妙或需要一定解读
  • 链接可能对部分读者有启发价值

2-3分 - 轻微关联：
  • 关联仅限于表面术语或零星概念
  • 主题、风格或情感基调大不相同
  • 联系需要刻意寻找才能发现
  • 链接价值有限，大多数读者难以察觉关联

0-1分 - 几乎无关联：
  • 内容、主题、意象几乎完全不同
  • 无法找到明显的思想或情感连接
  • 链接不会为读者理解任一内容增添价值
  • 并置阅读无法产生有意义的关联或启发

请只回复一个0-10的整数评分，不要有任何解释或额外文字！`;

// 新增: 默认标签提示词常量
export const DEFAULT_TAG_PROMPT = `你是一位知识管理与卡片笔记法（Zettelkasten）专家，擅长构建结构清晰、易于连接和检索的个人知识库。

你的任务是：针对我提供的每一篇笔记正文，为其生成一组精准、精炼且具有系统性的「中文标签」。这些标签应揭示笔记的核心思想，并帮助我将其融入到更广阔的知识网络中。

请严格遵循以下原则：
1. 【核心主题】识别笔记最关键、最核心的主题或关键词。
2. 【抽象概念】提炼能抽象出更高层次思想的概念。
3. 【知识领域】尽量使用分层标签定位知识领域，格式如：哲学/古希腊哲学、计算机科学/人工智能。
4. 【关联性】思考本笔记可与哪些主题产生有意义的连接。

输出规则：
• 每篇笔记最多 5 个标签；
• 标签全部使用中文；
• 标签之间使用英文逗号","分隔，逗号后不加空格；
• 每个标签内部不得包含空格；
• 只回复一行，且严格使用以下格式（注意冒号后有一个空格）：
  <笔记标题>: 标签1,标签2,标签3

除了这行标签信息之外，不要输出任何额外的说明、解释或多余文字！`;

export const DEFAULT_SETTINGS: JinaLinkerSettings = {
    pythonPath: '',
    jinaApiKey: '',
    aiModels: { ...DEFAULT_AI_MODELS },
    selectedAIProvider: 'deepseek',
    similarityThreshold: 0.70,
    excludedFolders: '.obsidian, Scripts, assets, Excalidraw, .trash, Python-Templater-Plugin-Output, 20_巴别塔/音乐',
    excludedFilesPatterns: '*excalidraw*, template*.md, *.kanban.md, ^moc$, ^index$',
    defaultScanPath: '/',
    jinaModelName: 'jina-embeddings-v3',
    maxCharsForJina: 8000,
    maxContentLengthForAI: 5000,
    maxCandidatesPerSourceForAIScoring: 20,
    minAiScoreForLinkInsertion: 6,
    maxLinksToInsertPerNote: 10,
    dataMigrationCompleted: true,
    customScoringPrompt: DEFAULT_SCORING_PROMPT,
    useCustomScoringPrompt: false,
    // 批量处理默认设置
    maxPairsPerRequest: 10,
    maxCharsPerNote: 2000,
    maxTotalCharsPerRequest: 23000,
    // 标签生成默认
    tagsMode: 'smart',
    maxTagsPerNote: 5,
    useCustomTagPrompt: false,
    customTagPrompt: DEFAULT_TAG_PROMPT,
};