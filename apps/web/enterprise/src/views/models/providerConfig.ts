/** 常用接入地址。模板预填表单，保存时使用用户最终确认的值。 */
export const providerPresets = [
  { value: 'preset:openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { value: 'preset:deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { value: 'preset:qwen', label: 'Qwen (DashScope)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'preset:openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
]

/** 检查地址格式，服务端执行真实网络许可与归一化。 */
export function isApiAddress(value: string): boolean {
  if (!/^https?:\/\//i.test(value) || /[\s\\?#]/.test(value)) return false
  try {
    const url = new URL(value)
    return Boolean(url.hostname && !url.username && !url.password)
  } catch {
    return false
  }
}
