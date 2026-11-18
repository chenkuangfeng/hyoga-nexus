<script setup lang="ts">
/** 本浏览器的管理界面偏好；企业运行配置仍使用各自具备授权的页面。 */
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTheme } from '@nexus-web/core/composables/useTheme'
import { ADMIN_EDITOR_MODE } from '@nexus-web/core/composables/useEditorPresentation'
import SettingsRow from '@nexus-web/core/components/SettingsRow.vue'
const { t } = useI18n(), { currentTheme, setTheme } = useTheme(), mode = inject(ADMIN_EDITOR_MODE)!
</script>
<template>
  <section><header class="section-header"><div><h2>{{ t('consoleLayout.settings') }}</h2><p>{{ t('consoleLayout.localPreference') }}</p></div></header>
    <SettingsRow :label="t('consoleLayout.theme')"><t-select :value="currentTheme" :aria-label="t('consoleLayout.theme')" @change="(value: unknown) => { if (value === 'light' || value === 'dark' || value === 'system') setTheme(value) }"><t-option v-for="value in ['light', 'dark', 'system']" :key="value" :value="value" :label="t(`theme.${value}`)" /></t-select></SettingsRow>
    <SettingsRow :label="t('consoleLayout.editorMode')"><t-select v-model="mode" :aria-label="t('consoleLayout.editorMode')"><t-option v-for="value in ['modal', 'route', 'drawer']" :key="value" :value="value" :label="t(`consoleLayout.${value}`)" /></t-select></SettingsRow>
  </section>
</template>
