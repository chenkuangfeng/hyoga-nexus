<script setup lang="ts">
/** 系统设置复用员工常规设置的标题、设置行、说明与主题色选择器。 */
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTheme } from '@nexus-web/core/composables/useTheme'
import { ADMIN_EDITOR_MODE } from '@nexus-web/core/composables/useEditorPresentation'
import BrandColorPicker from '@nexus-web/core/components/BrandColorPicker.vue'
const { t } = useI18n(), { currentTheme, setTheme } = useTheme(), mode = inject(ADMIN_EDITOR_MODE)!
</script>
<template>
  <section class="system-settings"><header class="section-header"><div><h2>{{ t('consoleLayout.settings') }}</h2><p class="section-description">{{ t('consoleLayout.localPreference') }}</p></div></header>
    <div class="settings-group">
      <div class="setting-row"><div class="setting-info"><label>{{ t('theme.theme') }}</label><p class="desc">{{ t('theme.themeDescription') }}</p></div><div class="setting-control"><t-select :value="currentTheme" style="width: 280px" :aria-label="t('theme.theme')" @change="(value: unknown) => { if (value === 'light' || value === 'dark' || value === 'system') setTheme(value) }"><t-option v-for="value in ['light', 'dark', 'system']" :key="value" :value="value" :label="t(`theme.${value}`)" /></t-select></div></div>
      <div class="setting-row"><div class="setting-info"><label>{{ t('theme.brandColor') }}</label><p class="desc">{{ t('theme.brandColorDescription') }}</p></div><div class="setting-control"><BrandColorPicker /></div></div>
      <div class="setting-row"><div class="setting-info"><label>{{ t('consoleLayout.editorMode') }}</label><p class="desc">{{ t('enterpriseLayout.editorModeHint') }}</p></div><div class="setting-control"><t-select v-model="mode" style="width: 280px" :aria-label="t('consoleLayout.editorMode')"><t-option v-for="value in ['modal', 'route', 'drawer']" :key="value" :value="value" :label="t(`consoleLayout.${value}`)" /></t-select></div></div>
    </div>
  </section>
</template>
<style scoped lang="less">
@import (reference) '@nexus-web/core/styles/settings-section.less';
.system-settings { width: 100%; min-width: 0; }
.section-header { .settings-section-header(); }
.settings-group { display: flex; flex-direction: column; gap: 0; }
.setting-row { .setting-row(); } .setting-info { .setting-info(); } .setting-control { .setting-control(); }
@media(max-width:720px) { .setting-row { flex-wrap: wrap; gap: 12px; } .setting-control { max-width: 100%; min-width: 0; } .setting-control :deep(.t-select) { max-width: 100%; } }
</style>
