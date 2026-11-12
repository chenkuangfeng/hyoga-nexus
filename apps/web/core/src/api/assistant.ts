/** 智能体与自动化沿用的写入授权级别契约；与已移除的浮动助手界面无关。 */
export type AssistantAccessLevel = 'read_only' | 'confirm' | 'auto_write'

export const ASSISTANT_ACCESS_LEVELS: AssistantAccessLevel[] = ['read_only', 'confirm', 'auto_write']
