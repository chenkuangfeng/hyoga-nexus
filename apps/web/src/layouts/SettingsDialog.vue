<script setup lang="ts">
/**
 * Settings dialog, laid out like WeKnora's: section list on the left, content on the right. Phase 1
 * implements 常规设置 only; the other sections are listed (in WeKnora's order, without Ollama) and
 * marked as planned until their phase lands.
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { LOCALES, setLocale, type Locale } from '../i18n'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const { t, locale } = useI18n()

const sections = [
  { key: 'general', label: 'settings.general', available: true },
  { key: 'models', label: 'settings.sections.models', available: false },
  { key: 'search', label: 'settings.sections.search', available: false },
  { key: 'messages', label: 'settings.sections.messages', available: false },
  { key: 'parsing', label: 'settings.sections.parsing', available: false },
  { key: 'storage', label: 'settings.sections.storage', available: false },
  { key: 'mcp', label: 'settings.sections.mcp', available: false },
  { key: 'system', label: 'settings.sections.system', available: false },
  { key: 'tenant', label: 'settings.sections.tenant', available: false },
  { key: 'api', label: 'settings.sections.api', available: false },
]
const current = ref('general')

function changeLocale(value: Locale) { setLocale(value); locale.value = value }
</script>

<template>
  <el-dialog :model-value="modelValue" :title="t('settings.title')" width="min(880px, 96vw)" class="settings-dialog" @update:model-value="(value: boolean) => emit('update:modelValue', value)">
    <div class="settings-layout">
      <nav class="settings-nav" :aria-label="t('settings.title')">
        <ul>
          <li v-for="section in sections" :key="section.key">
            <button type="button" class="settings-item" :class="{ active: current === section.key }" :aria-current="current === section.key ? 'true' : undefined" :disabled="!section.available" @click="current = section.key">
              <span>{{ t(section.label) }}</span>
              <span v-if="!section.available" class="soon">{{ t('common.soon') }}</span>
            </button>
          </li>
        </ul>
      </nav>
      <section class="settings-content" :aria-label="t('settings.general')">
        <template v-if="current === 'general'">
          <h2>{{ t('settings.general') }}</h2>
          <p class="muted">{{ t('settings.subtitle') }}</p>
          <div class="setting-row">
            <div>
              <label for="setting-language">{{ t('settings.languageLabel') }}</label>
              <p class="muted">{{ t('settings.languageHint') }}</p>
            </div>
            <el-select id="setting-language" :model-value="locale" class="setting-control" @change="(value: Locale) => changeLocale(value)">
              <el-option v-for="item in LOCALES" :key="item.value" :value="item.value" :label="item.label" />
            </el-select>
          </div>
          <div class="setting-row">
            <div>
              <label for="setting-theme">{{ t('settings.themeLabel') }}</label>
              <p class="muted">{{ t('settings.themeHint') }}</p>
            </div>
            <el-select id="setting-theme" model-value="light" class="setting-control" disabled>
              <el-option value="light" :label="t('settings.themeLight')" />
            </el-select>
          </div>
        </template>
        <p v-else class="muted">{{ t('settings.sectionsLater') }}</p>
      </section>
    </div>
  </el-dialog>
</template>

<style scoped>
.settings-layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 24px; min-height: 360px; }
.settings-nav ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.settings-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; min-height: 40px; padding: 6px 12px; border: 0; border-radius: 6px; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.settings-item:hover:not(:disabled) { background: var(--selected); }
.settings-item.active { background: var(--selected); color: var(--el-color-primary); font-weight: 600; }
.settings-item:disabled { color: var(--muted-text); cursor: not-allowed; }
.settings-item:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.soon { font-size: 12px; color: var(--muted-text); }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; border-bottom: 1px solid var(--border); }
.setting-row label { font-weight: 600; }
.setting-control { width: 220px; }
.muted { color: var(--muted-text); font-size: 13px; line-height: 1.6; margin: 4px 0 0; }
@media (max-width: 760px) { .settings-layout { grid-template-columns: 1fr; } .setting-row { flex-direction: column; align-items: stretch; } .setting-control { width: 100%; } }
</style>
