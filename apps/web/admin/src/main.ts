/** 企业管理应用独立启动；认证、主题与语言状态由公共包提供。 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/dist/tdesign.css'
import i18n from '@nexus-web/core/i18n'
import { initTheme } from '@nexus-web/core/composables/useTheme'
import { initFont } from '@nexus-web/core/composables/useFont'
import App from './App.vue'
import router from './router'

initTheme()
initFont()
const app = createApp(App)
app.use(createPinia()).use(TDesign).use(i18n).use(router)
router.isReady().then(() => app.mount('#app'))
