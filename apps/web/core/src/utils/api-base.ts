/**
 * API 与两个 Web 应用共用部署前缀。管理端的 /enterprise/ 只属于静态页面，
 * 不能成为 API 前缀；例如 /nexus/enterprise/ 的 API 位于 /nexus/api/v1/。
 * 其他前缀保留 LocalHub 等子路径部署的既有行为。
 */
export function getApiBaseUrl(): string {
  const base = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '')
  return base.replace(/\/enterprise$/, '')
}
