import type { EnterpriseModelProtocol, EnterpriseModelType } from '@nexus-web/core/api/enterprise-models'
import openaiIcon from './assets/openai.svg'
import deepseekIcon from './assets/deepseek.svg'
import aliyunIcon from './assets/aliyun.svg'
import anthropicIcon from './assets/anthropic.svg'
import openrouterIcon from './assets/openrouter.svg'

interface ProviderPreset {
  value: string
  label: string
  baseUrl: string
  icon: string
  protocol?: EnterpriseModelProtocol
  models: Partial<Record<EnterpriseModelType, string[]>>
}

/** 常用远程厂商的地址与模型候选。候选只是输入辅助，保存使用用户确认的模型 ID。 */
export const providerPresets: ProviderPreset[] = [
  { value: 'openai', label: 'OpenAI', icon: openaiIcon, baseUrl: 'https://api.openai.com/v1', models: {
    chat: ['gpt-5', 'gpt-5-mini', 'gpt-4.1'], embedding: ['text-embedding-3-small', 'text-embedding-3-large'],
    vision: ['gpt-4.1'], speech: ['whisper-1'],
  } },
  { value: 'deepseek', label: 'DeepSeek', icon: deepseekIcon, baseUrl: 'https://api.deepseek.com', models: {
    chat: ['deepseek-flash', 'deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner'],
  } },
  { value: 'anthropic', label: 'Anthropic', icon: anthropicIcon, baseUrl: 'https://api.anthropic.com/v1', protocol: 'anthropic_messages', models: {} },
  { value: 'qwen', label: 'Qwen (DashScope)', icon: aliyunIcon, baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: {
    chat: ['qwen-plus', 'qwen-max'], embedding: ['text-embedding-v4'], vision: ['qwen-vl-max'],
  } },
  { value: 'openrouter', label: 'OpenRouter', icon: openrouterIcon, baseUrl: 'https://openrouter.ai/api/v1', models: {} },
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
