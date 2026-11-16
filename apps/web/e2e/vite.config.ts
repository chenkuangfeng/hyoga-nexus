/** 复用应用配置，只限定依赖预打包范围；不替换路由、组件或业务模块。 */
import { mergeConfig } from 'vite'
import { createWebConfig } from '../vite.config'

const app = process.env.NEXUS_E2E_APP
if (app !== 'workspace' && app !== 'admin') throw new Error('NEXUS_E2E_APP must be workspace or admin')
export default mergeConfig(createWebConfig(app), {
  // 自动扫描所有懒加载的 Office/图表页面会在首个登录用例前耗尽小内存机器。
  // 用例仍加载实际页面依赖；需要的 CommonJS 依赖必须在此显式预打包。
  cacheDir: `../node_modules/.vite-e2e-${app}`,
  optimizeDeps: {
    noDiscovery: true,
    entries: [],
    include: [
      'vue', 'vue-router', 'pinia', 'vue-i18n',
      app === 'workspace' ? 'axios' : '@nexus-web/core > axios',
      'tdesign-vue-next',
      app === 'workspace' ? 'tdesign-icons-vue-next' : 'tdesign-vue-next > tdesign-icons-vue-next',
      ...['en_US', 'zh_CN', 'ko_KR', 'ja_JP', 'ru_RU', 'zh_TW'].map(locale => `tdesign-vue-next/esm/locale/${locale}`),
      ...(app === 'workspace' ? [
        'vue-virtual-scroller', 'vue-demi', 'highlight.js', 'dompurify',
        'katex', 'papaparse', 'jszip', '@xterm/xterm', '@xterm/addon-fit',
      ] : []),
    ],
  },
})
