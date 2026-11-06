/**
 * WeKnora knowledge endpoints Nexus has not implemented (openspec 2026-11-06-knowledge-base, decision 5).
 *
 * The copied knowledge pages still call these URLs. The request layer rejects a matching request with a
 * {@link PlannedFeatureError} before it is sent, so the page shows "待实现 · stage" instead of a 404 or a
 * network error. When a stage implements a feature, its module stops calling the WeKnora URL (or its
 * pattern is removed here) and the capability catalog flips to `available`.
 */
import { PlannedFeatureError } from './nexusAdapter'

interface PlannedEndpoint { pattern: RegExp, feature: string, stage: string }

export const PLANNED_ENDPOINTS: readonly PlannedEndpoint[] = [
  { pattern: /^\/api\/v1\/datasource(\/|\?|$)/, feature: '数据源同步', stage: 'K7' },
  { pattern: /^\/api\/v1\/knowledgebase\/[^/]+\/wiki(\/|\?|$)/, feature: 'Wiki', stage: 'K6' },
  { pattern: /^\/api\/v1\/initialization\/extract\//, feature: '知识图谱抽取', stage: 'K2' },
  { pattern: /^\/api\/v1\/initialization\/(initialize|config)\//, feature: '知识库模型配置', stage: 'K5' },
  { pattern: /^\/api\/v1\/system\/(parser-engines|docreader)/, feature: '解析引擎', stage: 'K4' },
  { pattern: /^\/api\/v1\/tenants\/kv\/parser-engine-config/, feature: '解析引擎', stage: 'K4' },
  { pattern: /^\/api\/v1\/knowledge-bases\/[^/]+\/shares/, feature: '知识库共享（界面）', stage: 'K1' },
  { pattern: /^\/api\/v1\/organizations\/[^/]+\/shared-knowledge-bases/, feature: '知识库共享（界面）', stage: 'K1' },
  { pattern: /^\/api\/v1\/organizations\/shared-knowledge-bases/, feature: '知识库共享（界面）', stage: 'K1' },
]

/** The planned-feature error for a request URL (path and query, no host), or null when it is not planned. */
export function plannedErrorFor(url: string | undefined): PlannedFeatureError | null {
  if (!url) return null
  const path = url.replace(/^https?:\/\/[^/]+/, '')
  for (const item of PLANNED_ENDPOINTS) {
    if (item.pattern.test(path)) return new PlannedFeatureError(item.feature, item.stage)
  }
  return null
}
