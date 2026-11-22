<script setup lang="ts">
/** WeKnora 的模型编辑抽屉，保存和测试均使用当前模型草稿。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import {
  createEnterpriseModelWithProvider, enterpriseModelProtocol, saveEnterpriseModel, testEnterpriseModelDraft,
  type EnterpriseModelConnectionResult, type EnterpriseModelInput, type EnterpriseModelProtocol,
  type EnterpriseModelType, type EnterpriseProviderInput,
} from '@nexus-web/core/api/enterprise-models'
import { isApiAddress, providerPresets } from './providerConfig'
import { modelTypeIcons, modelTypes, type ModelCard } from './modelTypes'

const props = defineProps<{ tenant: string; initialType: EnterpriseModelType; editing?: ModelCard }>()
const emit = defineEmits<{ close: []; saved: [type: EnterpriseModelType, editing: boolean] }>()
const { t } = useI18n()
const existing = props.editing?.provider
const existingModel = props.editing?.model
const savedOptions = existingModel?.options ?? {}
const savedPreset = providerPresets.find(item => item.label === existing?.name)
const supplier = ref(savedPreset?.value ?? (existing ? 'existing' : 'custom'))
const form = reactive({
  name: existingModel?.name ?? '',
  displayName: existingModel?.display_name === existingModel?.name ? '' : existingModel?.display_name ?? '',
  type: existingModel?.model_type ?? props.initialType,
  baseUrl: existing?.base_url ?? '',
  apiKey: '',
  protocol: enterpriseModelProtocol(savedOptions.protocol),
  temperature: typeof savedOptions.temperature === 'number' ? savedOptions.temperature : undefined,
  reasoningEffort: typeof savedOptions.reasoning_effort === 'string' ? savedOptions.reasoning_effort : '',
  rerankApi: typeof savedOptions.rerank_api === 'string' ? savedOptions.rerank_api : 'cohere',
})
const preset = computed(() => providerPresets.find(item => item.value === supplier.value))
const supplierOptions = computed(() => [
  ...(existing && !savedPreset ? [{ value: 'existing', label: existing.name, icon: '', baseUrl: '' }] : []),
  ...providerPresets.filter(item => form.type === 'chat' || item.protocol !== 'anthropic_messages'),
  { value: 'custom', label: t('modelSettings.source.custom'), icon: '', baseUrl: '' },
])
const catalogModels = computed(() => (preset.value?.models[form.type] ?? []).map(value => ({ value, label: value })))
const protocols: EnterpriseModelProtocol[] = ['openai_chat_completions', 'openai_responses', 'anthropic_messages']
const rerankApis = [
  { value: 'cohere', label: 'Cohere' },
  { value: 'tei', label: 'Text Embeddings Inference (TEI)' },
  { value: 'dashscope', label: 'DashScope' },
]
const providerInput = computed<EnterpriseProviderInput>(() => ({
  name: preset.value?.label ?? (supplier.value === 'existing' ? existing?.name : undefined) ?? 'OpenAI Compatible',
  base_url: form.baseUrl.trim(),
  scope: 'tenant',
  ...(form.apiKey ? { api_key: form.apiKey } : {}),
}))
const modelInput = computed<EnterpriseModelInput>(() => {
  const options: Record<string, unknown> = { protocol: form.protocol }
  if (form.type === 'chat') {
    options.reasoning_effort = form.reasoningEffort || ''
    if (typeof form.temperature === 'number') options.temperature = form.temperature
  }
  if (form.type === 'rerank') options.rerank_api = form.rerankApi
  return { name: form.name.trim(), display_name: form.displayName.trim(), model_type: form.type, options }
})
const testable = computed(() => ['chat', 'embedding', 'rerank'].includes(form.type))
const advanced = ref(false), saving = ref(false), checking = ref(false), error = ref('')
const result = ref<EnterpriseModelConnectionResult | null>(null), stale = ref(false)
let generation = 0, alive = true

function selectSupplier(value: unknown) {
  if (typeof value !== 'string' || value === supplier.value) return
  supplier.value = value
  form.baseUrl = preset.value?.baseUrl ?? (value === 'existing' ? existing?.base_url : '') ?? ''
  form.protocol = preset.value?.protocol ?? 'openai_chat_completions'
  form.apiKey = ''
  if (!existing) form.name = ''
}
function selectType(type: EnterpriseModelType) {
  form.type = type
  if (type !== 'chat' && form.protocol === 'anthropic_messages') {
    selectSupplier('custom')
    form.protocol = 'openai_chat_completions'
  }
}
function validate() {
  if (!modelInput.value.name) return t('adminModels.modelRequired')
  if (!isApiAddress(providerInput.value.base_url)) return t('adminModels.providerAddressInvalid')
  if (!form.apiKey.trim() && (!existing || providerInput.value.base_url !== existing.base_url)) {
    return t(existing ? 'adminModels.keyRequiredForAddressChange' : 'adminModels.keyRequired')
  }
  return ''
}
watch([modelInput, providerInput], () => {
  generation++
  checking.value = false
  stale.value ||= result.value !== null
  result.value = null
  error.value = ''
}, { flush: 'sync' })
onBeforeUnmount(() => { alive = false; form.apiKey = '' })

async function testConnection() {
  if (checking.value || saving.value) return
  error.value = validate()
  if (error.value) return
  const attempt = ++generation
  checking.value = true
  stale.value = false
  result.value = null
  try {
    const reply = await testEnterpriseModelDraft(props.tenant, providerInput.value, modelInput.value, existing?.id)
    if (alive && attempt === generation) result.value = reply
  } catch {
    if (alive && attempt === generation) result.value = { ok: false, message: t('adminModels.testFailed') }
  } finally {
    if (alive && attempt === generation) checking.value = false
  }
}

async function save() {
  if (saving.value) return
  error.value = validate()
  if (error.value) return
  const provider = providerInput.value, input = modelInput.value
  saving.value = true
  try {
    if (existing && existingModel) {
      await saveEnterpriseModel(props.tenant, existing.id, existingModel.id, input, provider)
    } else {
      await createEnterpriseModelWithProvider(props.tenant, { ...provider, api_key: form.apiKey }, input)
    }
    if (alive) emit('saved', input.model_type, !!existing)
  } catch {
    if (alive) error.value = t('adminModels.saveFailed')
  } finally {
    if (alive) saving.value = false
  }
}
</script>

<template>
  <SettingDrawer :visible="true" :title="t(existing ? 'model.editor.editTitle' : 'model.editor.addTitle')"
    :description="t(existing ? 'adminModels.versionHint' : 'adminModels.modelOptionsHint')"
    :icon="modelTypeIcons[form.type]" width="560px" storage-key="setting-drawer:width:model-editor"
    :confirm-text="t('model.editor.saveAndClose')" :confirm-loading="saving" :cancel-disabled="saving"
    :close-on-overlay-click="!saving" :close-on-esc-keydown="!saving"
    @update:visible="value => { if (!value && !saving) emit('close') }" @confirm="save" @cancel="emit('close')">
    <template v-if="testable" #footer-left>
      <t-button variant="outline" :loading="checking" :disabled="saving || !form.name.trim() || !form.baseUrl.trim()"
        :aria-description="t('adminModels.testHint')" @click="testConnection">
        <template v-if="result" #icon>
          <t-icon :name="result.ok ? 'check-circle-filled' : 'close-circle-filled'" aria-hidden="true" />
        </template>
        {{ t(checking ? 'model.editor.testing' : 'model.editor.testConnection') }}
      </t-button>
    </template>
    <template #footer-extra>
      <p v-if="error" class="connection-result error" role="alert">{{ error }}</p>
      <p v-if="result" class="connection-result" :class="{ error: !result.ok }" role="status">{{ result.message }}</p>
      <p v-else-if="stale" class="form-desc" role="status">{{ t('model.editor.testStale') }}</p>
    </template>

    <t-form layout="vertical" :inert="saving || undefined">
      <section v-if="!existing" class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ t('model.editor.sectionType') }}</h4>
        <div class="model-type-options" role="group" :aria-label="t('model.editor.typeLabel')">
          <button v-for="type in modelTypes" :key="type" type="button" class="model-type-option"
            :class="{ 'is-active': form.type === type }" :aria-pressed="form.type === type" @click="selectType(type)">
            <t-icon :name="modelTypeIcons[type]" class="model-type-option__icon" aria-hidden="true" />
            <span class="model-type-option__label">{{ t('adminModels.types.' + type) }}</span>
          </button>
        </div>
      </section>

      <section class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ t('model.editor.sectionSource') }}</h4>
        <span class="model-type-option is-active source-option">
          <t-icon name="cloud" class="model-type-option__icon" aria-hidden="true" />{{ t('model.editor.sourceRemote') }}
        </span>
      </section>

      <section class="setting-drawer__section editor-fields">
        <h4 class="setting-drawer__section-title">{{ t('model.editor.sectionProvider') }}</h4>
        <label>{{ t('model.editor.providerLabel') }}
          <t-select :value="supplier" filterable @change="selectSupplier">
            <t-option v-for="option in supplierOptions" :key="option.value" :value="option.value" :label="option.label"
              :show-overflow-tooltip="false">
              <div class="provider-option">
                <img v-if="option.icon" :src="option.icon" alt="" />
                <div>
                  <span>{{ option.label }}</span>
                  <span v-if="option.baseUrl" class="form-desc">{{ option.baseUrl }}</span>
                </div>
              </div>
            </t-option>
          </t-select>
        </label>
        <label>{{ t('model.modelName') }}
          <t-select v-if="catalogModels.length" v-model="form.name"
            :options="catalogModels" filterable creatable clearable @create="(value: unknown) => { form.name = String(value) }" />
          <t-input v-else v-model="form.name" :maxlength="160" clearable autocomplete="off" />
        </label>
        <label>{{ t('model.editor.displayNameLabel') }}
          <t-input v-model="form.displayName" :maxlength="160" :placeholder="t('model.editor.displayNamePlaceholder')" />
          <span class="form-desc">{{ t('model.editor.displayNameDesc') }}</span>
        </label>
        <label>{{ t('model.editor.baseUrlLabel') }}
          <t-input v-model="form.baseUrl" :maxlength="512" autocomplete="off" :spell-check="false"
            :placeholder="t('model.editor.baseUrlPlaceholder')" />
        </label>
        <label>{{ t('adminModels.apiKey') }}
          <t-input v-model="form.apiKey" type="password" autocomplete="new-password" :spell-check="false"
            :placeholder="existing?.key_configured ? existing.key_mask : t('model.editor.apiKeyPlaceholder')">
            <template #prefix-icon><t-icon name="lock-on" aria-hidden="true" /></template>
          </t-input>
          <span v-if="existing?.key_configured" class="form-desc">{{ t('adminModels.keyKeepHint') }}</span>
        </label>
      </section>

      <section v-if="testable" class="setting-drawer__section editor-fields">
        <button type="button" class="advanced-toggle" :aria-expanded="advanced" @click="advanced = !advanced">
          <t-icon :name="advanced ? 'chevron-down' : 'chevron-right'" aria-hidden="true" />
          {{ t('model.editor.sectionAdvanced') }}
        </button>
        <template v-if="advanced">
          <label v-if="form.type !== 'rerank'">{{ t('adminModels.protocol') }}
            <t-select v-model="form.protocol" :options="protocols.filter(value => form.type === 'chat' || value !== 'anthropic_messages')
              .map(value => ({ value, label: t('adminModels.protocols.' + value) }))" />
          </label>
          <label v-else>{{ t('adminModels.protocol') }}
            <t-select v-model="form.rerankApi" :options="rerankApis" />
          </label>
          <template v-if="form.type === 'chat'">
            <label>{{ t('adminModels.temperature') }}
              <t-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" :decimal-places="1" />
            </label>
            <label>{{ t('adminModels.reasoningEffort') }}
              <t-select v-model="form.reasoningEffort" clearable
                :options="['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].map(value => ({ value, label: value }))" />
            </label>
          </template>
        </template>
      </section>
    </t-form>
  </SettingDrawer>
</template>

<style scoped lang="less">
@import './ModelEditor.reference.less';

.editor-fields { display: grid; gap: 16px; }
.editor-fields .setting-drawer__section-title { margin-bottom: 0; }
.editor-fields label { display: grid; min-width: 0; gap: 8px; }
.source-option { cursor: default; }
.provider-option { display: flex; align-items: center; gap: 8px; padding-block: 4px; }
.provider-option img { width: 20px; height: 20px; object-fit: contain; }
.provider-option span { display: block; }
.form-desc { margin: 0; font-size: var(--app-text-sm); color: var(--td-text-color-secondary); }
.connection-result { margin: 0; overflow-wrap: anywhere; color: var(--td-success-color); }
.connection-result.error { color: var(--td-error-color); }
.advanced-toggle {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-self: start;
  padding: 0;
  border: 0;
  color: var(--td-text-color-primary);
  background: none;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
</style>
