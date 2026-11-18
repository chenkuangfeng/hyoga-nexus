<script setup lang="ts">
import UsagePage from '../usage/UsagePage.vue'
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
/** 企业模型目录：只管理当前企业共享 Provider、模型版本和租户默认值。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  disableEnterpriseModel, disableEnterpriseModelProvider, listEnterpriseModelSettings, saveEnterpriseModel,
  saveEnterpriseModelProvider, setEnterpriseModelDefault, testEnterpriseModel,
  enterpriseModelProtocol, type EnterpriseModelConnectionResult, type EnterpriseModelInput,
  type EnterpriseModelProvider, type EnterpriseModelProfile, type EnterpriseModelProtocol, type EnterpriseModelSettings,
  type EnterpriseModelType,
} from '@nexus-web/core/api/enterprise-models'
import { useAdminContext } from '../../stores/context'

const auth = useAuthStore(), context = useAdminContext(), { t } = useI18n()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('models:manage'))
const settings = ref<EnterpriseModelSettings | null>(null), loading = ref(false), busy = ref(false), error = ref(''), ready = ref(false)
const activeTab = ref('models'), activeType = ref<EnterpriseModelType>('chat'), modelQuery = ref('')
const filteredModels = computed(() => models.value.filter(({ model, provider }) => model.model_type === activeType.value && `${model.name} ${provider.name}`.toLowerCase().includes(modelQuery.value.toLowerCase())))
const types: EnterpriseModelType[] = ['chat', 'embedding', 'rerank', 'vision', 'speech']
const defaultsDraft = ref<Partial<Record<EnterpriseModelType, string>>>({})
const providerDialog = ref(false), providerEditId = ref<string | null>(null)
const providerForm = ref({ name: '', baseUrl: '', apiKey: '' })
const modelDialog = ref(false), modelProviderId = ref<string | null>(null), modelEditId = ref<string | null>(null)
const modelForm = ref({ name: '', type: 'chat' as EnterpriseModelType, protocol: 'openai_chat_completions' as EnterpriseModelProtocol, temperature: null as number | null, reasoningEffort: '' })
const connections = ref<Record<string, EnterpriseModelConnectionResult>>({}), testingId = ref('')
let epoch = 0, read = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const typeOptions = computed(() => types.map(value => ({ value, label: t(`adminModels.types.${value}`) })))
const providers = computed(() => settings.value?.providers || [])
const models = computed(() => providers.value.flatMap(provider => provider.models.map(model => ({ provider, model }))))
const defaultOptions = computed(() => Object.fromEntries(types.map(type => [type, models.value
  .filter(({ model }) => model.model_type === type)
  .map(({ provider, model }) => ({ value: model.version_id, label: `${provider.name} · ${model.name}` }))])))
function currentScope(current: number, scope: string, user: string) {
  return current === epoch && scope === tenant.value && user === String(auth.user?.id || '') && canManage.value
}
function clearForms() {
  providerDialog.value = false; providerEditId.value = null; providerForm.value = { name: '', baseUrl: '', apiKey: '' }
  modelDialog.value = false; modelProviderId.value = null; modelEditId.value = null
  modelForm.value = { name: '', type: 'chat', protocol: 'openai_chat_completions', temperature: null, reasoningEffort: '' }
  connections.value = {}; testingId.value = ''
}
function invalidate() {
  epoch++; read++; confirmation?.hide(); confirmation = undefined
  settings.value = null; loading.value = false; busy.value = false; error.value = ''; ready.value = false
  defaultsDraft.value = {}; clearForms()
}
async function load(refreshAfterWrite = false) {
  if (!canManage.value || !tenant.value || (busy.value && !refreshAfterWrite)) return
  const current = epoch, request = ++read, scope = tenant.value, user = String(auth.user?.id || '')
  loading.value = true; ready.value = false; error.value = ''
  try {
    const result = await listEnterpriseModelSettings(scope)
    if (!currentScope(current, scope, user) || request !== read) return
    settings.value = result; defaultsDraft.value = { ...result.defaults }; ready.value = true
  } catch { if (currentScope(current, scope, user) && request === read) error.value = t('adminModels.loadFailed') }
  finally { if (currentScope(current, scope, user) && request === read) loading.value = false }
}
function openProvider(row?: EnterpriseModelProvider) {
  if (!canManage.value || !ready.value || busy.value) return
  providerEditId.value = row?.id || null
  providerForm.value = { name: row?.name || '', baseUrl: row?.base_url || '', apiKey: '' }
  providerDialog.value = true; error.value = ''
}
async function saveProvider() {
  if (!tenant.value || busy.value) return
  const name = providerForm.value.name.trim(), baseUrl = providerForm.value.baseUrl.trim(), apiKey = providerForm.value.apiKey
  if (!name || !baseUrl || (!providerEditId.value && !apiKey.trim())) { error.value = t('adminModels.providerRequired'); return }
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = providerEditId.value
  if (id) {
    const existing = providers.value.find(row => row.id === id)
    if (existing && existing.base_url !== baseUrl && !apiKey.trim()) { error.value = t('adminModels.keyRequiredForAddressChange'); return }
  }
  busy.value = true; error.value = ''
  try {
    await saveEnterpriseModelProvider(scope, { name, base_url: baseUrl, scope: 'tenant', ...(apiKey ? { api_key: apiKey } : {}) }, id || undefined)
    if (!currentScope(current, scope, user)) return
    clearForms(); void MessagePlugin.success(t('adminModels.providerSaved'))
    await load(true)
  } catch { if (currentScope(current, scope, user)) error.value = t('adminModels.saveFailed') }
  finally { if (currentScope(current, scope, user)) busy.value = false }
}
function openModel(provider: EnterpriseModelProvider, row?: EnterpriseModelProfile) {
  if (!canManage.value || !ready.value || busy.value) return
  modelProviderId.value = provider.id; modelEditId.value = row?.id || null
  const options = row?.options || {}
  modelForm.value = {
    name: row?.name || '', type: row?.model_type || 'chat', protocol: enterpriseModelProtocol(options.protocol),
    temperature: typeof options.temperature === 'number' ? options.temperature : null,
    reasoningEffort: typeof options.reasoning_effort === 'string' ? options.reasoning_effort : '',
  }
  modelDialog.value = true; error.value = ''
}
async function saveModel() {
  const providerId = modelProviderId.value
  if (!tenant.value || !providerId || busy.value) return
  const name = modelForm.value.name.trim()
  if (!name) { error.value = t('adminModels.modelRequired'); return }
  const options: Record<string, unknown> = { protocol: modelForm.value.protocol }
  if (modelForm.value.temperature !== null) options.temperature = modelForm.value.temperature
  else if (modelEditId.value) {
    const existing = providers.value.find(row => row.id === modelProviderId.value)?.models.find(row => row.id === modelEditId.value)
    if (typeof existing?.options.temperature === 'number') options.temperature = existing.options.temperature
  }
  options.reasoning_effort = modelForm.value.reasoningEffort
  const input: EnterpriseModelInput = { name, model_type: modelForm.value.type, options }
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), profileId = modelEditId.value
  busy.value = true; error.value = ''
  try {
    await saveEnterpriseModel(scope, providerId, input, profileId || undefined)
    if (!currentScope(current, scope, user)) return
    clearForms(); void MessagePlugin.success(t(profileId ? 'adminModels.modelVersionSaved' : 'adminModels.modelSaved'))
    await load(true)
  } catch { if (currentScope(current, scope, user)) error.value = t('adminModels.saveFailed') }
  finally { if (currentScope(current, scope, user)) busy.value = false }
}
async function saveDefault(type: EnterpriseModelType, value: unknown) {
  if (!tenant.value || busy.value) return
  const next = typeof value === 'string' && value ? value : null
  const previous = settings.value?.defaults[type]
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || '')
  busy.value = true; error.value = ''
  try {
    await setEnterpriseModelDefault(scope, type, next)
    if (!currentScope(current, scope, user)) return
    defaultsDraft.value = { ...defaultsDraft.value, [type]: next || undefined }
    if (settings.value) settings.value.defaults = { ...settings.value.defaults, [type]: next || undefined }
    void MessagePlugin.success(t('adminModels.defaultSaved'))
  } catch {
    if (currentScope(current, scope, user)) {
      defaultsDraft.value = { ...defaultsDraft.value, [type]: previous }
      error.value = t('adminModels.defaultFailed')
    }
  } finally { if (currentScope(current, scope, user)) busy.value = false }
}
function confirmDisable(kind: 'provider' | 'model', provider: EnterpriseModelProvider, model?: EnterpriseModelProfile) {
  if (!canManage.value || !ready.value || busy.value || confirmation) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || '')
  const name = kind === 'provider' ? provider.name : model?.name || ''
  const dialog = DialogPlugin.confirm({ header: t(kind === 'provider' ? 'adminModels.deleteProviderTitle' : 'adminModels.deleteModelTitle'),
    body: t(kind === 'provider' ? 'adminModels.deleteProviderConfirm' : 'adminModels.deleteModelConfirm', { name }), theme: 'danger',
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (!currentScope(current, scope, user) || busy.value) return
      busy.value = true; error.value = ''
      try {
        if (kind === 'provider') await disableEnterpriseModelProvider(scope, provider.id)
        else if (model) await disableEnterpriseModel(scope, provider.id, model.id)
        if (!currentScope(current, scope, user)) return
        void MessagePlugin.success(t(kind === 'provider' ? 'adminModels.providerDisabled' : 'adminModels.modelDisabled', { name }))
        await load(true)
      } catch { if (currentScope(current, scope, user)) error.value = t('adminModels.deleteFailed') }
      finally { if (currentScope(current, scope, user)) busy.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
async function testModel(provider: EnterpriseModelProvider, model: EnterpriseModelProfile) {
  if (!tenant.value || busy.value || testingId.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || '')
  testingId.value = model.id; error.value = ''
  try {
    const result = await testEnterpriseModel(scope, provider.id, model.id)
    if (!currentScope(current, scope, user)) return
    connections.value = { ...connections.value, [model.id]: result }
  } catch { if (currentScope(current, scope, user)) error.value = t('adminModels.testFailed') }
  finally { if (currentScope(current, scope, user)) testingId.value = '' }
}
watch([tenant, () => auth.user?.id, () => context.revision, canManage], () => { invalidate(); void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(invalidate)
</script>

<template>
  <section class="models-page">
    <header class="section-header">
      <div><h2>{{ t('consoleLayout.modelManagement') }}</h2><p>{{ t('adminModels.description') }}</p></div>
      <div class="actions"><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button><t-button v-if="canManage" theme="primary" :disabled="!ready || busy" @click="openProvider()"><t-icon name="add" />{{ t('adminModels.addProvider') }}</t-button></div>
    </header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminModels.scopeHint')" />
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert theme="info" :message="t('adminModels.testHint')" />
      <t-tabs v-model="activeTab"><t-tab-panel value="models" :label="t('consoleLayout.modelManagement')" /><t-tab-panel value="defaults" :label="t('adminModels.defaultsTitle')" /><t-tab-panel value="usage" :label="t('adminUsage.title')" /></t-tabs>
      <UsagePage v-if="activeTab === 'usage'" />
      <template v-else-if="activeTab === 'defaults'">      <section class="defaults-panel">
        <header><div><h3>{{ t('adminModels.defaultsTitle') }}</h3><p>{{ t('adminModels.defaultsHint') }}</p></div></header>
        <div class="defaults-grid"><label v-for="type in types" :key="type">{{ t(`adminModels.types.${type}`) }}<t-select :value="defaultsDraft[type] || ''" :options="defaultOptions[type] || []" :placeholder="t('adminModels.noDefault')" clearable filterable :disabled="busy || !ready || !(defaultOptions[type]?.length)" @change="(value: unknown) => saveDefault(type, value)" /></label></div>
      </section>
</template>
      <template v-else>
        <div class="model-tabbar"><t-tabs v-model="activeType" class="model-type-tabs"><t-tab-panel v-for="type in types" :key="type" :value="type"><template #label><span class="model-type-tab"><t-icon name="control-platform" size="16px" />{{ t(`adminModels.types.${type}`) }}<span class="model-tab-count">{{ models.filter(row => row.model.model_type === type).length }}</span></span></template></t-tab-panel></t-tabs><t-input v-model="modelQuery" class="model-search" clearable :placeholder="t('menu.search')" :aria-label="t('menu.search')"><template #prefix-icon><t-icon name="search" /></template></t-input></div>
        <t-loading :loading="loading"><div v-if="ready" class="model-grid">
          <article v-for="{ provider, model } in filteredModels" :key="model.id" class="model-card" :class="`model-card--${model.model_type}`">
            <div class="model-card__badge"><t-icon name="control-platform" size="16px" /></div><div class="model-card__body"><div class="model-card__header"><h3 class="model-card__title">{{ model.name }}</h3><div class="model-card__actions"><t-dropdown :options="[{content:t('adminModels.editModel'),value:'model'},{content:t('adminModels.editProvider'),value:'provider'},{content:t('adminModels.disable'),value:'disable'}]" @click="(option: { value?: string | number }) => { if(option.value === 'model') openModel(provider,model); if(option.value === 'provider') openProvider(provider); if(option.value === 'disable') confirmDisable('model',provider,model) }"><t-button variant="text" shape="square" :disabled="busy" :aria-label="t('common.expand')"><t-icon name="ellipsis" /></t-button></t-dropdown></div></div><p class="model-card__subtitle">{{ provider.name }} · {{ t(`adminModels.types.${model.model_type}`) }}</p><div class="model-card__meta"><t-tag variant="light">{{ t('adminModels.modelVersion',{version:model.version}) }}</t-tag><t-button variant="text" :loading="testingId === model.id" :disabled="busy || !!testingId" @click="testModel(provider, model)">{{ t('adminModels.test') }}</t-button></div><p v-if="connections[model.id]" role="status">{{ connections[model.id].message }}</p></div>
          </article>
          <button v-for="provider in providers" :key="`add-${provider.id}`" type="button" class="model-card model-card--add" :disabled="busy" @click="openModel(provider)"><t-icon name="add" /><span>{{ provider.name }} · {{ t('adminModels.addModel') }}</span></button>
        </div><t-empty v-if="ready && !providers.length" :description="t('adminModels.noProviders')" /></t-loading>
        <div class="provider-management"><t-dropdown v-for="provider in providers" :key="provider.id" :options="[{content:t('adminModels.editProvider'),value:'edit'},{content:t('adminModels.disable'),value:'disable'}]" @click="(option: { value?: string | number }) => { if (option.value === 'edit') openProvider(provider); else confirmDisable('provider',provider) }"><t-button variant="text" :disabled="busy">{{ provider.name }}<t-icon name="chevron-down" /></t-button></t-dropdown></div>
      </template>
    </template>
    <EditorDialog :visible="providerDialog" :header="t(providerEditId ? 'adminModels.editProviderTitle' : 'adminModels.addProviderTitle')" width="min(560px, calc(100vw - 24px))" :confirm-btn="{ content: t('adminModels.save'), loading: busy, disabled: busy }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" :close-btn="!busy" :close-on-overlay-click="!busy" @confirm="saveProvider" @close="!busy && (providerDialog = false)">
      <div class="editor-form"><label>{{ t('adminModels.providerName') }}<t-input v-model="providerForm.name" maxlength="160" /></label><label>{{ t('adminModels.baseUrl') }}<t-input v-model="providerForm.baseUrl" maxlength="512" /></label><label>{{ t('adminModels.apiKey') }}<t-input v-model="providerForm.apiKey" type="password" autocomplete="new-password" :placeholder="t(providerEditId ? 'adminModels.keyKeepHint' : 'adminModels.keyRequired')" /></label><p class="field-hint">{{ t('adminModels.keyWriteOnly') }}</p></div>
    </EditorDialog>
    <EditorDialog :visible="modelDialog" :header="t(modelEditId ? 'adminModels.editModelTitle' : 'adminModels.addModelTitle')" width="min(600px, calc(100vw - 24px))" :confirm-btn="{ content: t('adminModels.save'), loading: busy, disabled: busy }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" :close-btn="!busy" :close-on-overlay-click="!busy" @confirm="saveModel" @close="!busy && (modelDialog = false)">
      <div class="editor-form"><label>{{ t('adminModels.modelName') }}<t-input v-model="modelForm.name" maxlength="160" /></label><label>{{ t('adminModels.modelType') }}<t-select v-model="modelForm.type" :options="typeOptions" :disabled="!!modelEditId" /></label><label>{{ t('adminModels.protocol') }}<t-select v-model="modelForm.protocol" :options="[{value:'openai_chat_completions',label:t('adminModels.protocols.openai_chat_completions')},{value:'openai_responses',label:t('adminModels.protocols.openai_responses')},{value:'anthropic_messages',label:t('adminModels.protocols.anthropic_messages')}]" /></label><label>{{ t('adminModels.temperature') }}<t-input-number v-model="modelForm.temperature" :min="0" :max="2" :step="0.1" :decimal-places="1" /></label><label>{{ t('adminModels.reasoningEffort') }}<t-select v-model="modelForm.reasoningEffort" clearable :options="['none','minimal','low','medium','high','xhigh','max'].map(value => ({value,label:value}))" /></label><p class="field-hint">{{ t(modelEditId ? 'adminModels.versionHint' : 'adminModels.modelOptionsHint') }}</p></div>
    </EditorDialog>
  </section>
</template>

<style scoped lang="less">
@import './ModelsPage.reference.less';
.models-page { min-width: 0; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.defaults-panel, .provider-card { margin-top: 20px; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.defaults-panel header, .provider-header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
h3 { margin: 0; font-size: var(--app-text-lg); }
.defaults-panel p { margin: 6px 0 0; color: var(--td-text-color-secondary); }
.defaults-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 16px; margin-top: 16px; }
.defaults-grid label, .editor-form label { display: grid; min-width: 0; gap: 8px; color: var(--td-text-color-primary); }
.provider-title { display: flex; align-items: center; gap: 12px; min-width: 0; }
.provider-title > :deep(.t-icon) { flex-shrink: 0; color: var(--td-brand-color); font-size: 22px; }
.provider-title h3 { overflow-wrap: anywhere; }
.provider-title code, .key-info { display: block; margin-top: 6px; color: var(--td-text-color-secondary); overflow-wrap: anywhere; }
.key-info code { color: var(--td-text-color-primary); }
.model-list { margin-top: 16px; border-top: 1px solid var(--td-component-stroke); }
.model-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--td-component-stroke); }
.model-row:last-child { border-bottom: 0; padding-bottom: 0; }
.model-info { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; min-width: 0; }
.model-info strong { overflow-wrap: anywhere; }
.model-info > span, .model-info small { color: var(--td-text-color-secondary); }
.model-info small { overflow-wrap: anywhere; }
.connection-result { flex-basis: 100%; margin: 0; color: var(--td-error-color); }
.connection-result.is-success { color: var(--td-success-color); }
.empty-models { color: var(--td-text-color-secondary); }
.empty-state { display: grid; justify-items: center; gap: 12px; padding: 52px 16px; color: var(--td-text-color-secondary); text-align: center; }
.editor-form { display: grid; gap: 16px; max-height: min(68vh, 720px); overflow-y: auto; padding: 2px; }
.field-hint { margin: 0; color: var(--td-text-color-secondary); line-height: 1.5; }
@media (max-width: 640px) { .provider-header, .model-row { align-items: stretch; flex-direction: column; } .model-row .actions { justify-content: flex-start; } }
</style>
