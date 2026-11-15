/** 企业解析引擎已有配置接口；Available 是配置完整度，不是网络探测结果。 */
import { get, put } from '../utils/request'
/** 目录条目；configured 为配置完整度，reason 保留服务端的未就绪说明。 */
export interface ParserEngine { name: string; description: string; file_types: string[]; configured: boolean; reason: string }
/** 服务端全量配置快照；兼容字段保留，已知密钥仅接受脱敏占位。 */
export type ParserConfig = Record<string, unknown>
export const PARSER_SECRET_KEYS = ['mineru_api_key', 'mineru_server_api_key', 'paddleocr_vl_cloud_token'] as const
export const PARSER_SECRET_MASK = '******'
/** 可编辑参数的描述；boolean 使用默认/开启/关闭三态，secret 为只写字段。 */
export interface ParserField { key: string; label: string; boolean?: boolean; secret?: boolean }
/** 已实现解析服务与其实际消费的参数集合。 */
export interface ParserGroup { name: string; fields: ParserField[] }
const field = (key: string, label: string, boolean = false, secret = false): ParserField => ({ key, label, boolean, secret })
/** 与服务端 ingest.engines 与 parsers._OPTIONAL 对应；扩展字段只保留，不擅自覆盖。 */
export const PARSER_GROUPS: ParserGroup[] = [
  { name: 'MinerU', fields: [field('mineru_endpoint', 'URL'), field('mineru_server_api_key', 'API Key', false, true), field('mineru_model', 'Backend'), field('mineru_vlm_server_url', 'vLLM URL'), field('mineru_parse_method', 'Parse method (auto / ocr / txt)'), field('mineru_language', 'settings.parser.language'), field('mineru_enable_formula', 'settings.parser.formulaRecognition', true), field('mineru_enable_table', 'settings.parser.tableRecognition', true)] },
  { name: 'MinerU Cloud', fields: [field('mineru_api_key', 'API Key', false, true), field('mineru_cloud_model', 'Model'), field('mineru_cloud_language', 'settings.parser.language'), field('mineru_cloud_enable_formula', 'settings.parser.formulaRecognition', true), field('mineru_cloud_enable_table', 'settings.parser.tableRecognition', true), field('mineru_cloud_enable_ocr', 'OCR', true)] },
  { name: 'PaddleOCR-VL', fields: [field('paddleocr_vl_endpoint', 'URL'), field('paddleocr_vl_use_seal_recognition', 'settings.parser.sealRecognition', true), field('paddleocr_vl_use_chart_recognition', 'settings.parser.chartRecognition', true)] },
  { name: 'PaddleOCR-VL Cloud', fields: [field('paddleocr_vl_cloud_token', 'API Token', false, true), field('paddleocr_vl_cloud_model', 'Model'), field('paddleocr_vl_cloud_use_seal_recognition', 'settings.parser.sealRecognition', true), field('paddleocr_vl_cloud_use_chart_recognition', 'settings.parser.chartRecognition', true)] },
]
const object = (v: unknown): Record<string, unknown> => { if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('parser_response_invalid'); return v as Record<string, unknown> }
const string = (v: unknown): string => { if (typeof v !== 'string') throw new Error('parser_response_invalid'); return v }
/** 解析 GET/PUT 的 data 配置；结构、字段类型或密钥脱敏异常时抛出 parser_response_invalid。 */
export function parserConfigFromResponse(value: unknown): ParserConfig {
  const config = object(object(value).data)
  for (const f of PARSER_GROUPS.flatMap(g => g.fields)) {
    const v = config[f.key]
    if (v == null) continue
    if (typeof v !== (f.boolean ? 'boolean' : 'string') || (f.secret && v !== '' && v !== PARSER_SECRET_MASK)) throw new Error('parser_response_invalid')
  }
  return { ...config }
}
function base(tenant: string) { return `/api/v1/tenants/${encodeURIComponent(tenant)}/admin/knowledge` }
/** 读取 tenant 对应企业的脱敏配置；网络及响应错误交由调用方呈现。 */
export async function getEnterpriseParserConfig(tenant: string): Promise<ParserConfig> { return parserConfigFromResponse(await get(`${base(tenant)}/parser-engine-config`)) }
/** 整体替换 tenant 的配置并返回脱敏快照；调用方须保留未编辑字段，服务端复核 owner/admin。 */
export async function saveEnterpriseParserConfig(tenant: string, config: ParserConfig): Promise<ParserConfig> { return parserConfigFromResponse(await put(`${base(tenant)}/parser-engine-config`, config)) }
/** 读取 tenant 的引擎目录并规范化状态；非法目录条目抛出 parser_response_invalid。 */
export async function listEnterpriseParserEngines(tenant: string): Promise<ParserEngine[]> {
  const data = object(await get(`${base(tenant)}/parser-engines`)).data
  if (!Array.isArray(data)) throw new Error('parser_response_invalid')
  return data.map(v => {
    const r = object(v)
    if (!Array.isArray(r.FileTypes) || r.FileTypes.some(v => typeof v !== 'string') || typeof r.Available !== 'boolean') throw new Error('parser_response_invalid')
    return { name: string(r.Name), description: string(r.Description), file_types: r.FileTypes as string[], configured: r.Available, reason: string(r.UnavailableReason) }
  })
}
/** 替换整个配置时保留快照扩展；空密钥保持原值，只有显式清除才删除。 */
export function parserConfigPayload(snapshot: ParserConfig, draft: ParserConfig, cleared: string[]): ParserConfig {
  const result = { ...snapshot }
  for (const f of PARSER_GROUPS.flatMap(g => g.fields)) {
    const v = draft[f.key]
    if (f.secret) {
      if (cleared.includes(f.key)) delete result[f.key]
      else if (typeof v === 'string' && v.trim()) result[f.key] = v.trim()
    } else if (v === undefined || v === null || v === '') delete result[f.key]
    else result[f.key] = typeof v === 'string' ? v.trim() : v
  }
  return result
}
