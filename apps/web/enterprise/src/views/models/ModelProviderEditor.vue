<script setup lang="ts">
/** 企业服务商的接入配置。表单持有临时凭据，只在通过校验后提交给页面。 */
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormInstanceFunctions, FormRules, SubmitContext } from 'tdesign-vue-next'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import { isApiAddress } from './providerConfig'
import type { EnterpriseModelProvider, EnterpriseProviderInput } from '@nexus-web/core/api/enterprise-models'

type ProviderDraft = { name: string; baseUrl: string; apiKey: string }

const props = defineProps<{
  visible: boolean
  provider: Pick<EnterpriseModelProvider, 'name' | 'base_url'>
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
const keyRequired = computed(() => draft.baseUrl.trim() !== props.provider.base_url)
const keyRequiredMessage = computed(() => t('adminModels.keyRequiredForAddressChange'))

const rules = computed<FormRules<ProviderDraft>>(() => ({
  name: [{ validator: () => !!draft.name.trim(), message: t('adminModels.providerNameRequired') }],
  baseUrl: [{ validator: () => isApiAddress(draft.baseUrl.trim()), message: t('adminModels.providerAddressInvalid') }],
  apiKey: [{ validator: () => !keyRequired.value || !!draft.apiKey.trim(), message: keyRequiredMessage.value }],
}))

watch([() => props.visible, () => props.provider], ([visible, provider]) => {
  draft.name = visible ? provider.name : ''
  draft.baseUrl = visible ? provider.base_url : ''
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
    :title="t('adminModels.editProviderTitle')"
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
          :help="keyRequired ? keyRequiredMessage : t('adminModels.keyWriteOnly')">
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
</style>
