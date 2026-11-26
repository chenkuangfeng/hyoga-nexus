<script setup lang="ts">
/** WeKnora's settings drawer sections adapted to Nexus named profiles and deployment references. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import { saveSandboxConfiguration, type SandboxBackend, type SandboxConfiguration, type SandboxDetails } from '@nexus-web/core/api/nexus-sandboxes'
import SandboxConfigField from './SandboxConfigField.vue'
import { advancedFields, backendNames, connectionFields, resourceFields } from './sandboxConfigFields'
const props = defineProps<{
  tenant: string; record: SandboxDetails | null; revision: number
  defaults: Record<SandboxBackend, SandboxConfiguration>; preset: SandboxBackend
}>()
const emit = defineEmits<{ close: []; saved: [record: SandboxDetails] }>()
const { t } = useI18n()
const kind = ref<SandboxBackend>(props.record?.type || props.preset)
function cloneValues(source: SandboxConfiguration): SandboxConfiguration {
  return Object.fromEntries(Object.entries(source).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value]))
}
const values = ref<SandboxConfiguration>(cloneValues(props.record?.configuration || props.defaults[kind.value]))
const name = ref(props.record?.display_name || props.record?.name || '')
const description = ref(props.record?.description || '')
const saving = ref(false)
const failure = ref('')
let disposed = false
onBeforeUnmount(() => { disposed = true })
const advanced = ref(false)
const fields = computed(() => resourceFields(kind.value, !!String(values.value.cgroup_root || '').trim()))
const valid = computed(() => name.value.trim().length > 0
  && connectionFields[kind.value].every(field => !field.required || String(values.value[field.key] || '').trim())
  && [...connectionFields[kind.value], ...fields.value, ...advancedFields(kind.value)]
    .filter(field => field.input === 'number' && values.value[field.key] !== undefined)
    .every(field => {
      const value = Number(values.value[field.key])
      return Number.isFinite(value) && value >= (field.min ?? 0) && value <= (field.max ?? Infinity)
        && (field.step === 0.1 || Number.isInteger(value))
    })
  && Number(values.value.skill_timeout_seconds) <= Number(values.value.skill_timeout_max_seconds))
watch(kind, type => {
  values.value = cloneValues(props.defaults[type])
})
function change(key: string, value: string | number | boolean | string[]) {
  values.value[key] = value
  if (key === 'cgroup_root' && value) {
    values.value.cpus ??= 1
    values.value.pids ??= 128
  }
}
async function save() {
  if (!valid.value || saving.value) return
  saving.value = true
  failure.value = ''
  const candidate: SandboxConfiguration = { ...values.value, type: kind.value,
    display_name: name.value.trim(), description: description.value.trim() }
  if (kind.value === 'bwrap' && !candidate.cgroup_root) { delete candidate.cpus; delete candidate.pids }
  try {
    const saved = await saveSandboxConfiguration(props.tenant, props.record?.name || null, candidate, props.revision)
    if (!disposed) emit('saved', saved)
  } catch (error: unknown) {
    if (!disposed) {
      const status = error && typeof error === 'object' && 'status' in error ? error.status : undefined
      failure.value = status === 403 ? 'saveForbidden' : status === 409 ? 'saveConflict'
        : status === 422 ? 'saveInvalid' : status === 503 ? 'saveUnavailable' : 'saveFailed'
    }
  } finally {
    if (!disposed) saving.value = false
  }
}
</script>

<template>
  <SettingDrawer :visible="true" class="sandbox-config-drawer" icon="code"
    :title="t(record ? 'sandboxConfig.edit' : 'sandboxConfig.add')"
    :description="t('sandboxConfig.editorDescription')" width="680px" :min-width="560" :max-width="920"
    storage-key="setting-drawer:sandbox-config" :confirm-loading="saving" :cancel-disabled="saving"
    :confirm-disabled="!valid" :confirm-text="t('sandboxConfig.save')" @confirm="save" @cancel="emit('close')"
    @update:visible="value => { if (!value && !saving) emit('close') }">
    <template #footer-extra>
      <t-alert v-if="failure" role="alert" theme="error" :message="t(`sandboxConfig.${failure}`)" />
      <p v-else-if="!valid" role="status" class="sandbox-validation-hint">{{ t('sandboxConfig.incomplete') }}</p>
    </template>
    <t-form label-align="top" class="sandbox-editor-form" @submit="save">
      <section class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ t('sandboxConfig.basic') }}</h4>
        <t-form-item :label="t('sandboxConfig.name')" required-mark>
          <label class="sandbox-control">
            <span class="sandbox-control__label">{{ t('sandboxConfig.name') }}</span>
            <t-input v-model="name" name="sandbox_display_name" :maxlength="160" :disabled="saving" />
          </label>
        </t-form-item>
        <t-form-item :label="t('sandboxConfig.description')">
          <label class="sandbox-control">
            <span class="sandbox-control__label">{{ t('sandboxConfig.description') }}</span>
            <t-textarea v-model="description" :maxlength="1000" :disabled="saving" />
          </label>
        </t-form-item>
        <t-form-item :label="t('sandboxConfig.backend')" required-mark>
          <t-select v-model="kind" :disabled="saving || !!record" :aria-label="t('sandboxConfig.backend')"
            :options="Object.entries(backendNames).map(([value, label]) => ({ value, label }))" />
        </t-form-item>
      </section>
      <section class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ t('sandboxConfig.connection') }}</h4>
        <t-alert class="compact-alert" theme="info" :message="t(`sandboxConfig.hints.${kind}`)" />
        <SandboxConfigField v-for="field in connectionFields[kind]" :key="field.key" :field="field" :values="values"
          :disabled="saving" @change="change" />
      </section>
      <section class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ t('sandboxConfig.resources') }}</h4>
        <div class="resource-grid">
          <SandboxConfigField v-for="field in fields" :key="field.key" :field="field" :values="values"
            :disabled="saving" @change="change" />
        </div>
      </section>
      <t-collapse v-if="advancedFields(kind).length" :value="advanced ? ['advanced'] : []"
        @change="advanced = !advanced">
        <t-collapse-panel value="advanced" :header="t('sandboxConfig.advanced')">
          <div class="resource-grid">
            <SandboxConfigField v-for="field in advancedFields(kind)" :key="field.key" :field="field" :values="values"
              :disabled="saving" @change="change" />
          </div>
        </t-collapse-panel>
      </t-collapse>
    </t-form>
  </SettingDrawer>
</template>

<style scoped lang="less">
.sandbox-editor-form { display: flex; flex-direction: column; gap: 20px; }
.sandbox-validation-hint { margin: 0; color: var(--td-text-color-secondary); }
.sandbox-control { display: block; width: 100%; }
.sandbox-control__label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.setting-drawer__section + .setting-drawer__section { padding-top: 16px; border-top: 1px solid var(--td-component-stroke); }
.setting-drawer__section-title { margin: 0 0 16px; font-weight: 600; font-size: var(--app-text-md); }
.compact-alert { margin-bottom: 16px; }
.resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
@media (max-width: 560px) { .resource-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
