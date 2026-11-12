/**
 * 新会话的默认标题：取首条消息的前 `maxLength` 个字符（空白压缩为单个空格）。
 * 与 WeKnora 新会话的命名方式一致；空消息返回空串，由服务端或界面显示「未命名会话」。
 */
export function deriveSessionTitle(message: string, maxLength = 40): string {
  return message.replace(/\s+/g, ' ').trim().slice(0, maxLength)
}
