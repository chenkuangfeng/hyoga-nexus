<script setup lang="ts">
/** 企业服务商的接入配置。表单持有临时凭据，只在通过校验后提交给页面。 */
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormInstanceFunctions, FormRules, SubmitContext } from 'tdesign-vue-next'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import type { EnterpriseModelProvider, EnterpriseProviderInput } from '@nexus-web/core/api/enterprise-models'

type ProviderDraft = { name: string; baseUrl: string; apiKey: string }

const props = defineProps<{
  visible: boolean
  provider: Pick<EnterpriseModelProvider, 'name' | 'base_url'> | null
  busy: boolean
  error: string
}>()
const emit = defineEmits<{
  close: []
  save: [input: Omit<EnterpriseProviderInput, 'scope'>]
}>()

const { t } = useI18n()
const form = ref<FormInstanceFunctions<ProviderDraft>>()
const draft = reactive<ProviderDraft>({ name: '', baseUrl: '', apiKey: '' })
const preset = ref('custom')

// 模板只填入表单字段，服务商身份及模型协议继续由企业配置决定。
const presets = [
  { value: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { value: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { value: 'qwen', label: 'Qwen (DashScope)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
]
const addressChanged = computed(() => props.provider !== null && draft.baseUrl.trim() !== props.provider.base_url)
const keyRequired = computed(() => !props.provider || addressChanged.value)
const keyRequiredMessage = computed(() => t(addressChanged.value ? 'adminModels.keyRequiredForAddressChange' : 'adminModels.keyRequired'))

const rules = computed<FormRules<ProviderDraft>>(() => ({
  name: [{ validator: () => !!draft.name.trim(), message: t('adminModels.providerNameRequired') }],
  baseUrl: [{ validator: () => isApiAddress(draft.baseUrl.trim()), message: t('adminModels.providerAddressInvalid') }],
  apiKey: [{ validator: () => !keyRequired.value || !!draft.apiKey.trim(), message: keyRequiredMessage.value }],
}))

/** 校验地址格式，具体网络许可和地址归一化由服务端处理。 */
function isApiAddress(value: string) {
  if (!/^https?:\/\//i.test(value) || /[\s\\?#]/.test(value)) return false
  try {
    const url = new URL(value)
    return Boolean(url.hostname && !url.username && !url.password)
  } catch {
    return false
  }
}

function applyPreset(value: string) {
  const selected = presets.find(option => option.value === value)
  draft.name = selected?.label ?? ''
  draft.baseUrl = selected?.baseUrl ?? ''
  // 切换接入地址时立即移除上一家服务商的密钥。
  draft.apiKey = ''
  form.value?.clearValidate()
}

watch([() => props.visible, () => props.provider], ([visible, provider]) => {
  preset.value = 'custom'
  draft.name = visible ? provider?.name ?? '' : ''
  draft.baseUrl = visible ? provider?.base_url ?? '' : ''
  draft.apiKey = ''
  form.value?.clearValidate()
}, { immediate: true })

function submit({ validateResult }: SubmitContext<ProviderDraft>) {
  if (validateResult !== true || !props.visible || props.busy) return
  emit('save', {
    name: draft.name.trim(),
    base_url: draft.baseUrl.trim(),
    ...(draft.apiKey ? { api_key: draft.apiKey } : {}),
  })
}
</script>

<template>
  <SettingDrawer :visible="visible" placement="center" width="560px" icon="cloud" :resizable="false"
    :title="t(provider ? 'adminModels.editProviderTitle' : 'adminModels.addProviderTitle')"
    :confirm-text="t('model.editor.saveAndClose')" :confirm-loading="busy" :confirm-disabled="busy"
    :cancel-disabled="busy" :close-btn="!busy" :close-on-overlay-click="!busy" :close-on-esc-keydown="!busy"
    @confirm="form?.submit()" @update:visible="(value: boolean) => { if (!value && !busy) emit('close') }">
    <template v-if="error" #footer-extra>
      <t-alert theme="error" :message="error" />
    </template>

    <t-form ref="form" :data="draft" :rules="rules" :disabled="busy" layout="vertical"
      :label-width="0" scroll-to-first-error="auto" @submit="submit">
      <section class="setting-drawer__section provider-config">
        <h4 class="setting-drawer__section-title">{{ t('model.editor.sectionProvider') }}</h4>
        <t-form-item v-if="!provider">
          <label class="provider-field">
            <span>{{ t('adminModels.providerTemplate') }}</span>
            <t-select v-model="preset" filterable
              :popup-props="{ overlayInnerClassName: 'model-provider-presets' }" @change="applyPreset">
              <t-option value="custom" :label="t('modelSettings.source.custom')" />
              <t-option v-for="option in presets" :key="option.value" :value="option.value" :label="option.label">
                <span class="provider-preset">
                  <strong>{{ option.label }}</strong>
                  <span>{{ option.baseUrl }}</span>
                </span>
              </t-option>
            </t-select>
          </label>
        </t-form-item>
        <t-form-item name="name">
          <label class="provider-field">
            <span class="required">{{ t('adminModels.providerName') }}</span>
            <t-input v-model="draft.name" :maxlength="160" :placeholder="t('nexusModels.providerNamePlaceholder')" />
          </label>
        </t-form-item>
        <t-form-item name="baseUrl">
          <label class="provider-field">
            <span class="required">{{ t('adminModels.baseUrl') }}</span>
            <t-input v-model="draft.baseUrl" :maxlength="512" :placeholder="t('nexusModels.baseUrlPlaceholder')"
              autocomplete="off" :spell-check="false" />
          </label>
        </t-form-item>
        <t-form-item name="apiKey"
          :help="addressChanged ? keyRequiredMessage : t('adminModels.keyWriteOnly')">
          <label class="provider-field">
            <span :class="{ required: keyRequired }">{{ t('adminModels.apiKey') }}</span>
            <t-input v-model="draft.apiKey" type="password" :placeholder="keyRequired ? t('adminModels.keyRequired') : t('adminModels.keyKeepHint')"
              autocomplete="new-password" :spell-check="false">
              <template #prefix-icon><t-icon name="lock-on" aria-hidden="true" /></template>
            </t-input>
          </label>
        </t-form-item>
      </section>
    </t-form>
  </SettingDrawer>
</template>

<style scoped lang="less">
.provider-config :deep(.t-form__item) { margin-bottom: 0; }

.provider-field {
  display: grid;
  width: 100%;
  min-width: 0;
  gap: 6px;
  color: var(--td-text-color-primary);
  font-size: var(--app-text-md);
  font-weight: 500;

  .required::before {
    content: '*';
    margin-inline-end: 4px;
    color: var(--td-error-color);
  }
}

.provider-preset {
  display: grid;
  min-width: 0;
  gap: 2px;
  padding-block: 5px;
  line-height: 1.35;

  strong { font-weight: 500; color: var(--td-text-color-primary); }
  span { color: var(--td-text-color-secondary); font-size: var(--app-text-sm); overflow-wrap: anywhere; }
}

:global(.model-provider-presets .t-select-option) {
  height: auto;
  white-space: normal;
}
</style>
