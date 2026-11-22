<script setup lang="ts">
/** Nexus 企业默认值独立于模型目录，通过当前企业的已保存模型版本设置。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  listEnterpriseModelSettings, setEnterpriseModelDefault, type EnterpriseModelSettings, type EnterpriseModelType,
} from '@nexus-web/core/api/enterprise-models'
import { useEnterpriseContext } from '../../stores/context'
import { modelLabel, modelTypes } from './modelTypes'

const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('models:manage'))
const settings = ref<EnterpriseModelSettings | null>(null), loading = ref(false), busy = ref(false), error = ref('')
let epoch = 0
const defaultOptions = computed(() => Object.fromEntries(modelTypes.map(type => [type,
  settings.value?.providers.flatMap(provider => provider.models.filter(model => model.model_type === type)
    .map(model => ({ value: model.version_id, label: `${provider.name} · ${modelLabel(model)}` }))) ?? [],
])))
function reset() {
  epoch++
  settings.value = null
  loading.value = busy.value = false
  error.value = ''
}
async function load() {
  if (!tenant.value || !canManage.value || loading.value) return
  const scope = epoch
  loading.value = true
  error.value = ''
  try {
    const result = await listEnterpriseModelSettings(tenant.value)
    if (scope === epoch) settings.value = result
  } catch {
    if (scope === epoch) error.value = t('adminModels.loadFailed')
  } finally {
    if (scope === epoch) loading.value = false
  }
}
async function save(type: EnterpriseModelType, value: unknown) {
  if (!settings.value || busy.value || !canManage.value) return
  const scope = epoch, next = typeof value === 'string' && value ? value : null
  busy.value = true
  error.value = ''
  try {
    await setEnterpriseModelDefault(tenant.value, type, next)
    if (scope !== epoch || !settings.value) return
    settings.value.defaults = { ...settings.value.defaults, [type]: next || undefined }
    void MessagePlugin.success(t('adminModels.defaultSaved'))
  } catch {
    if (scope === epoch) error.value = t('adminModels.defaultFailed')
  } finally {
    if (scope === epoch) busy.value = false
  }
}
watch([tenant, () => auth.user?.id, () => context.revision, canManage], () => { reset(); void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(reset)
</script>

<template>
  <section class="defaults-panel">
    <h2>{{ t('adminModels.defaultsTitle') }}</h2>
    <p>{{ t('adminModels.defaultsHint') }}</p>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-button v-if="error && !settings" variant="text" @click="load">{{ t('connectionUi.refresh') }}</t-button>
      <t-loading :loading="loading">
        <div v-if="settings" class="defaults-grid">
          <label v-for="type in modelTypes" :key="type">
            {{ t('adminModels.types.' + type) }}
            <t-select :value="settings.defaults[type] || ''" :options="defaultOptions[type]"
              :placeholder="t('adminModels.noDefault')" clearable filterable
              :disabled="busy || !defaultOptions[type]?.length" @change="(value: unknown) => save(type, value)" />
          </label>
        </div>
      </t-loading>
    </template>
  </section>
</template>

<style scoped>
.defaults-panel { min-width: 0; }
.defaults-panel h2 { margin: 0; }
.defaults-panel p { color: var(--td-text-color-secondary); }
.defaults-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  gap: 16px;
  margin-top: 16px;
}
.defaults-grid label { display: grid; min-width: 0; gap: 8px; }
</style>
