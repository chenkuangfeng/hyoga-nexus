import { computed } from 'vue'
import { getApiBaseUrl } from '@nexus-web/core/utils/api-base'

/** 返回可复制到外部客户端的 API 地址，保留部署前缀，不依赖桌面绑定。 */
export function useApiBaseUrlDisplay() {
  const apiBaseUrlDisplay = computed(() => {
    const base = getApiBaseUrl().trim().replace(/\/+$/, '')
    const path = `${base}/api/v1`
    const origin = typeof window !== 'undefined' ? window.location.origin : ''
    return origin && origin !== 'null' ? new URL(path, origin).href : path
  })
  return { apiBaseUrlDisplay }
}
