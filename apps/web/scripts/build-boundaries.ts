/** 检查实际生产模块图，不把管理应用源码打入工作台，反向同样禁止。 */
import { resolve } from 'node:path'
import type { Plugin } from 'vite'
export function buildBoundaries(webRoot: string, app: 'workspace' | 'admin'): Plugin {
  const forbidden = `${resolve(webRoot, app === 'workspace' ? 'admin' : 'workspace', 'src').replaceAll('\\', '/')}/`
  return {
    name: 'application-build-boundaries', apply: 'build',
    generateBundle() {
      for (const id of this.getModuleIds()) if (id.replaceAll('\\', '/').startsWith(forbidden)) {
        this.error(`cross_application_source:${app}:${id}`)
      }
      this.info(`${app}: production module graph respects application boundaries`)
    },
  }
}
