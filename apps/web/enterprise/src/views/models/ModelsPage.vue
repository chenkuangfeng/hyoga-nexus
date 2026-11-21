<script setup lang="ts">
import UsagePage from '../usage/UsagePage.vue'
import ModelActions from './ModelActions.vue'
import ModelProviderEditor from './ModelProviderEditor.vue'
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
/** 企业模型目录：只管理当前企业共享 Provider、模型版本和租户默认值。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  copyEnterpriseModel, disableEnterpriseModel, disableEnterpriseModelProvider, listEnterpriseModelSettings, saveEnterpriseModel,
  saveEnterpriseModelProvider, setEnterpriseModelDefault, testEnterpriseModel,
  testEnterpriseModelDraft,
  enterpriseModelProtocol, type EnterpriseModelConnectionResult, type EnterpriseModelInput,
  type EnterpriseModelProvider, type EnterpriseModelProfile, type EnterpriseModelProtocol, type EnterpriseModelSettings,
  type EnterpriseModelType, type EnterpriseProviderInput,
} from '@nexus-web/core/api/enterprise-models'
import { useEnterpriseContext } from '../../stores/context'

const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('models:manage'))
const settings = ref<EnterpriseModelSettings | null>(null), loading = ref(false), busy = ref(false), error = ref(''), ready = ref(false)
const activeTab = ref('models'), activeType = ref<EnterpriseModelType | 'all'>('all'), modelQuery = ref('')
const types: EnterpriseModelType[] = ['chat', 'embedding', 'rerank', 'vision', 'speech']
const typeIcons: Record<EnterpriseModelType | 'all', string> = {
  all: 'view-module', chat: 'chat', embedding: 'chart-bubble', rerank: 'filter-sort', vision: 'image', speech: 'sound',
}
const defaultsDraft = ref<Partial<Record<EnterpriseModelType, string>>>({})
const providerDialog = ref(false), providerError = ref('')
const editingProvider = ref<EnterpriseModelProvider | null>(null)
const modelDialog = ref(false), modelProviderId = ref<string | null>(null), modelEditId = ref<string | null>(null)
const rerankApis = [
  { value: 'cohere', label: 'Cohere' },
  { value: 'tei', label: 'Text Embeddings Inference (TEI)' },
  { value: 'dashscope', label: 'DashScope' },
]
function emptyModelForm(type: EnterpriseModelType = 'chat') {
  return { name: '', displayName: '', type, protocol: 'openai_chat_completions' as EnterpriseModelProtocol,
    temperature: null as number | null, reasoningEffort: '', rerankApi: 'cohere' }
}
const modelForm = ref(emptyModelForm())
watch(() => modelForm.value.type, type => {
  if (type === 'embedding' && modelForm.value.protocol === 'anthropic_messages' && !modelEditId.value) {
    modelForm.value.protocol = 'openai_chat_completions'
  }
})
const draftConnection = ref<EnterpriseModelConnectionResult | null>(null), testingDraft = ref(false)
const connections = ref<Record<string, EnterpriseModelConnectionResult>>({}), testingId = ref('')
let epoch = 0, read = 0, draftRequest = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const typeOptions = computed(() => types.map(value => ({ value, label: t(`adminModels.types.${value}`) })))
const providers = computed(() => settings.value?.providers || [])
const selectedProvider = computed(() => providers.value.find(row => row.id === modelProviderId.value))
const providerOptions = computed(() => providers.value.map(provider => ({ value: provider.id, label: provider.name })))
const providerActions = computed(() => providers.value.flatMap(provider => [
  { label: `${provider.name} · ${t('adminModels.editProvider')}`, key: `edit-${provider.id}`, run: () => openProvider(provider) },
  { label: `${provider.name} · ${t('adminModels.disable')}`, key: `disable-${provider.id}`, danger: true, run: () => confirmDisable('provider', provider) },
]))
const models = computed(() => providers.value.flatMap(provider => provider.models.map(model => ({ provider, model }))))
const typeTabs = computed(() => {
  const counts = { all: models.value.length, chat: 0, embedding: 0, rerank: 0, vision: 0, speech: 0 }
  for (const { model } of models.value) counts[model.model_type]++
  return [{ value: 'all' as const, label: t('common.all') }, ...typeOptions.value]
    .map(tab => ({ ...tab, icon: typeIcons[tab.value], count: counts[tab.value] }))
})
const query = computed(() => modelQuery.value.trim().toLowerCase())
const filteredModels = computed(() => models.value.filter(({ model, provider }) =>
  (activeType.value === 'all' || model.model_type === activeType.value)
  && [model.name, modelLabel(model), provider.name].some(name => name.toLowerCase().includes(query.value)),
))
const defaultOptions = computed(() => Object.fromEntries(types.map(type => [type, models.value
  .filter(({ model }) => model.model_type === type)
  .map(({ provider, model }) => ({ value: model.version_id, label: `${provider.name} · ${modelLabel(model)}` }))])))
function modelLabel(model: EnterpriseModelProfile) {
  return model.display_name || model.name
}
function currentScope(current: number, scope: string, user: string) {
  return current === epoch && scope === tenant.value && user === String(auth.user?.id || '') && canManage.value
}
function clearForms() {
  closeProvider()
  modelDialog.value = false; modelProviderId.value = null; modelEditId.value = null
  modelForm.value = emptyModelForm()
  connections.value = {}; testingId.value = ''
}
function invalidate() {
  epoch++; read++; confirmation?.hide(); confirmation = undefined
  settings.value = null; loading.value = false; busy.value = false; error.value = ''; ready.value = false
  defaultsDraft.value = {}; clearForms()
  activeType.value = 'all'; modelQuery.value = ''
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
  editingProvider.value = row ?? null
  providerError.value = ''
  providerDialog.value = true
  error.value = ''
}
function closeProvider() {
  providerDialog.value = false
  editingProvider.value = null
  providerError.value = ''
}
async function saveProvider(input: Omit<EnterpriseProviderInput, 'scope'>) {
  if (!tenant.value || !canManage.value || !ready.value || !providerDialog.value || busy.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = editingProvider.value?.id
  busy.value = true
  providerError.value = ''
  try {
    await saveEnterpriseModelProvider(scope, { ...input, scope: 'tenant' }, id)
    if (!currentScope(current, scope, user)) return
    clearForms(); void MessagePlugin.success(t('adminModels.providerSaved'))
    await load(true)
  } catch { if (currentScope(current, scope, user)) providerError.value = t('adminModels.saveFailed') }
  finally { if (currentScope(current, scope, user)) busy.value = false }
}
/** 新增时可选企业服务商，编辑时继续使用原服务商和模型类型。 */
function openModel(provider?: EnterpriseModelProvider, row?: EnterpriseModelProfile) {
  if (!canManage.value || !ready.value || busy.value) return
  if (!providers.value.length) { openProvider(); return }
  modelProviderId.value = provider?.id ?? (providers.value.length === 1 ? providers.value[0].id : null)
  modelEditId.value = row?.id || null
  const options = row?.options || {}
  modelForm.value = {
    ...emptyModelForm(row?.model_type ?? (activeType.value === 'all' ? 'chat' : activeType.value)),
    name: row?.name || '',
    displayName: row && modelLabel(row) !== row.name ? modelLabel(row) : '',
    protocol: enterpriseModelProtocol(options.protocol),
    temperature: typeof options.temperature === 'number' ? options.temperature : null,
    reasoningEffort: typeof options.reasoning_effort === 'string' ? options.reasoning_effort : '',
    rerankApi: rerankApis.find(api => api.value === options.rerank_api)?.value ?? 'cohere',
  }
  modelDialog.value = true; error.value = ''
}
const modelInput = computed<EnterpriseModelInput>(() => {
  const form = modelForm.value
  const existing = selectedProvider.value?.models.find(row => row.id === modelEditId.value)
  const options: Record<string, unknown> = { protocol: form.protocol, reasoning_effort: form.reasoningEffort }
  const temperature = form.temperature ?? existing?.options.temperature
  if (typeof temperature === 'number') options.temperature = temperature
  if (form.type === 'rerank') options.rerank_api = form.rerankApi
  const displayName = form.displayName.trim()
  return { name: form.name.trim(), model_type: form.type, options,
    ...(displayName || modelEditId.value ? { display_name: displayName } : {}) }
})
const draftTestInput = computed(() => {
  const { name, model_type, options } = modelInput.value
  return JSON.stringify([modelDialog.value, selectedProvider.value?.id, name, model_type, options])
})
watch(draftTestInput, () => {
  draftRequest++
  testingDraft.value = false
  draftConnection.value = null
}, { flush: 'sync' })

async function testModelDraft() {
  const provider = selectedProvider.value, input = modelInput.value
  if (!modelDialog.value || !provider || !input.name || !tenant.value || !canManage.value || testingDraft.value || busy.value) return
  const current = epoch, request = ++draftRequest, scope = tenant.value, user = String(auth.user?.id || '')
  testingDraft.value = true
  draftConnection.value = null
  try {
    const result = await testEnterpriseModelDraft(scope, provider, input)
    if (request === draftRequest && currentScope(current, scope, user)) draftConnection.value = result
  } catch {
    if (request === draftRequest && currentScope(current, scope, user)) {
      draftConnection.value = { ok: false, message: t('adminModels.testFailed') }
    }
  } finally {
    if (request === draftRequest && currentScope(current, scope, user)) testingDraft.value = false
  }
}

async function saveModel() {
  const providerId = selectedProvider.value?.id, input = modelInput.value
  if (!tenant.value || !canManage.value || !ready.value || !modelDialog.value || !providerId || busy.value) return
  if (!input.name) { error.value = t('adminModels.modelRequired'); return }
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), profileId = modelEditId.value
  busy.value = true; error.value = ''
  try {
    await saveEnterpriseModel(scope, providerId, input, profileId || undefined)
    if (!currentScope(current, scope, user)) return
    if (!profileId) {
      if (activeType.value !== 'all') activeType.value = input.model_type
      modelQuery.value = ''
    }
    clearForms(); void MessagePlugin.success(t(profileId ? 'adminModels.modelVersionSaved' : 'adminModels.modelSaved'))
    await load(true)
  } catch { if (currentScope(current, scope, user)) error.value = t('adminModels.saveFailed') }
  finally { if (currentScope(current, scope, user)) busy.value = false }
}
async function copyModel(provider: EnterpriseModelProvider, model: EnterpriseModelProfile) {
  if (!tenant.value || !canManage.value || !ready.value || busy.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || '')
  busy.value = true; error.value = ''
  try {
    await copyEnterpriseModel(scope, provider.id, model.id, t('modelSettings.copySuffix').trim())
    if (!currentScope(current, scope, user)) return
    modelQuery.value = ''
    void MessagePlugin.success(t('modelSettings.toasts.copied'))
    await load(true)
  } catch { if (currentScope(current, scope, user)) error.value = t('modelSettings.toasts.copyFailed') }
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
  const name = kind === 'provider' ? provider.name : model ? modelLabel(model) : ''
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
  <section class="model-settings">
    <header class="model-section-header">
      <div class="model-section-header__top">
        <div class="model-title">
          <h2>{{ t('consoleLayout.modelManagement') }}</h2>
          <t-popup v-if="canManage" trigger="click" placement="bottom-left" show-arrow>
            <button type="button" class="model-title-help" :aria-label="t('adminModels.description')">
              <t-icon name="help-circle" size="16px" aria-hidden="true" />
            </button>
            <template #content>
              <div class="model-hints">
                <p>{{ t('adminModels.scopeHint') }}</p>
                <p>{{ t('adminModels.testHint') }}</p>
              </div>
            </template>
          </t-popup>
        </div>
        <div v-if="canManage && activeTab !== 'usage'" class="model-header-actions">
          <t-button variant="outline" size="small" :loading="loading" :disabled="busy" @click="load()">
            {{ t('connectionUi.refresh') }}
          </t-button>
          <template v-if="activeTab === 'models' && providers.length">
            <ModelActions :label="t('model.editor.providerLabel')" :disabled="!ready || busy" :actions="providerActions" />
            <t-button variant="outline" size="small" :disabled="!ready || busy" @click="openProvider()">
              {{ t('adminModels.addProvider') }}
            </t-button>
            <t-button theme="primary" size="small" :disabled="!ready || busy" @click="openModel()">
              <template #icon><t-icon name="add" aria-hidden="true" /></template>
              {{ t('adminModels.addModel') }}
            </t-button>
          </template>
        </div>
      </div>
      <p class="section-description">{{ t('adminModels.description') }}</p>
    </header>

    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error && !providerDialog && !modelDialog && activeTab !== 'usage'" theme="error" :message="error" />
      <t-tabs v-model="activeTab" class="model-sections">
        <t-tab-panel value="models" :label="t('consoleLayout.modelManagement')" />
        <t-tab-panel value="defaults" :label="t('adminModels.defaultsTitle')" />
        <t-tab-panel value="usage" :label="t('adminUsage.title')" />
      </t-tabs>
      <UsagePage v-if="activeTab === 'usage'" />
      <section v-else-if="activeTab === 'defaults'" class="defaults-panel">
        <h3>{{ t('adminModels.defaultsTitle') }}</h3>
        <p>{{ t('adminModels.defaultsHint') }}</p>
        <div class="defaults-grid">
          <label v-for="type in types" :key="type">
            {{ t('adminModels.types.' + type) }}
            <t-select :value="defaultsDraft[type] || ''" :options="defaultOptions[type] || []"
              :placeholder="t('adminModels.noDefault')" clearable filterable
              :disabled="busy || !ready || !(defaultOptions[type]?.length)"
              @change="(value: unknown) => saveDefault(type, value)" />
          </label>
        </div>
      </section>
      <template v-else>
        <div class="model-tabbar">
          <t-tabs v-model="activeType" class="model-type-tabs">
            <t-tab-panel v-for="tab in typeTabs" :key="tab.value" :value="tab.value">
              <template #label>
                <span class="model-type-tab">
                  <t-icon :name="tab.icon" size="16px" aria-hidden="true" />
                  <span>{{ tab.label }}</span>
                  <span class="model-tab-count">{{ tab.count }}</span>
                </span>
              </template>
            </t-tab-panel>
          </t-tabs>
          <t-input v-model="modelQuery" class="model-search" clearable
            :placeholder="t('menu.search')" :aria-label="t('menu.search')">
            <template #prefix-icon><t-icon name="search" aria-hidden="true" /></template>
          </t-input>
        </div>

        <t-loading :loading="loading" size="small" class="model-list">
          <template v-if="ready">
            <div v-if="query && !filteredModels.length" class="empty-state">
              <t-empty :description="t('common.noResult')" />
              <t-button variant="outline" @click="modelQuery = ''">{{ t('common.clear') }}</t-button>
            </div>
            <template v-else>
              <p v-if="!providers.length" class="model-empty-hint">{{ t('adminModels.noProviders') }}</p>
              <div class="model-grid">
                <article v-for="{ provider, model } in filteredModels" :key="model.id" class="model-card"
                  :class="'model-card--' + model.model_type">
                  <div class="model-card__badge" aria-hidden="true">
                    <t-icon :name="typeIcons[model.model_type]" size="16px" />
                  </div>
                  <div class="model-card__body">
                    <h3 class="model-card__title">
                      <button type="button" class="model-card__edit" :title="modelLabel(model)" :disabled="busy"
                        @click="openModel(provider, model)">{{ modelLabel(model) }}</button>
                    </h3>
                    <p class="model-card__subtitle">
                      <span class="model-card__vendor" :title="provider.name">{{ provider.name }}</span>
                      <span>{{ t('adminModels.types.' + model.model_type) }} · {{ t('adminModels.modelVersion', { version: model.version }) }}</span>
                    </p>
                    <p v-if="connections[model.id]" class="connection-result" role="status"
                      :class="{ 'is-success': connections[model.id].ok }">{{ connections[model.id].message }}</p>
                  </div>
                  <div class="model-card__actions">
                    <t-button variant="text" shape="square" size="small" :loading="testingId === model.id"
                      :disabled="busy || !!testingId" :aria-label="t('adminModels.test')"
                      :aria-description="t('adminModels.testHint')" :title="t('adminModels.testHint')" @click="testModel(provider, model)">
                      <template #icon><t-icon name="play-circle" aria-hidden="true" /></template>
                    </t-button>
                    <ModelActions :label="t('common.expand')" :disabled="busy" icon-only :actions="[
                      { label: t('common.copy'), key: 'copy', run: () => copyModel(provider, model) },
                      { label: t('adminModels.editProvider'), key: 'edit', run: () => openProvider(provider) },
                      { label: t('adminModels.disable'), key: 'disable', danger: true, run: () => confirmDisable('model', provider, model) },
                    ]" />
                  </div>
                </article>
                <button type="button" class="model-card model-card--add" :disabled="busy" @click="openModel()">
                  <span class="model-card--add__icon" aria-hidden="true"><t-icon name="add" /></span>
                  <span>{{ t(providers.length ? 'adminModels.addModel' : 'adminModels.addProvider') }}</span>
                </button>
              </div>
            </template>
          </template>
        </t-loading>
      </template>
    </template>
    <ModelProviderEditor :visible="providerDialog" :provider="editingProvider" :busy="busy" :error="providerError"
      @save="saveProvider" @close="closeProvider" />
    <EditorDialog :visible="modelDialog" :header="t(modelEditId ? 'adminModels.editModelTitle' : 'adminModels.addModelTitle')" width="min(600px, calc(100vw - 24px))" :confirm-btn="{ content: t('adminModels.save'), loading: busy, disabled: busy || !modelProviderId }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" :close-btn="!busy" :close-on-overlay-click="!busy" @confirm="saveModel" @close="!busy && (modelDialog = false)">
      <div class="editor-form">
        <t-alert v-if="error" theme="error" :message="error" />
        <label for="enterprise-model-provider">{{ t('model.editor.providerLabel') }}
          <t-select v-model="modelProviderId" :input-props="{ id: 'enterprise-model-provider' }"
            :options="providerOptions" :placeholder="t('model.editor.providerPlaceholder')" :disabled="!!modelEditId" filterable />
        </label>
        <label>{{ t('adminModels.modelName') }}<t-input v-model="modelForm.name" maxlength="160" /></label>
        <label>{{ t('model.editor.displayNameLabel') }}<t-input v-model="modelForm.displayName" maxlength="160" :placeholder="modelForm.name" /></label>
        <label>{{ t('adminModels.modelType') }}<t-select v-model="modelForm.type" :options="typeOptions" :disabled="!!modelEditId" /></label>
        <label v-if="modelForm.type === 'chat' || modelForm.type === 'embedding'">{{ t('adminModels.protocol') }}<t-select v-model="modelForm.protocol" :options="[{value:'openai_chat_completions',label:t('adminModels.protocols.openai_chat_completions')},{value:'openai_responses',label:t('adminModels.protocols.openai_responses')},...(modelForm.type === 'chat' ? [{value:'anthropic_messages',label:t('adminModels.protocols.anthropic_messages')}] : [])]" /></label>
        <label v-if="modelForm.type === 'rerank'">{{ t('adminModels.protocol') }}<t-select v-model="modelForm.rerankApi" :options="rerankApis" /></label>
        <template v-if="modelForm.type === 'chat'">
          <label>{{ t('adminModels.temperature') }}<t-input-number v-model="modelForm.temperature" :min="0" :max="2" :step="0.1" :decimal-places="1" /></label>
          <label>{{ t('adminModels.reasoningEffort') }}<t-select v-model="modelForm.reasoningEffort" clearable :options="['none','minimal','low','medium','high','xhigh','max'].map(value => ({value,label:value}))" /></label>
        </template>
        <p class="field-hint">{{ t(modelEditId ? 'adminModels.versionHint' : 'adminModels.modelOptionsHint') }}</p>
        <div v-if="['chat', 'embedding', 'rerank'].includes(modelForm.type)">
          <t-button variant="outline" :loading="testingDraft" :disabled="busy || testingDraft || !selectedProvider || !modelInput.name"
            :aria-description="t('adminModels.testHint')" @click="testModelDraft">{{ t('adminModels.test') }}</t-button>
          <p class="field-hint">{{ t('adminModels.testHint') }}</p>
          <p v-if="draftConnection" class="connection-result" :class="{ 'is-success': draftConnection.ok }"
            role="status">{{ draftConnection.message }}</p>
        </div>
      </div>
    </EditorDialog>
  </section>
</template>

<style scoped lang="less">
@import './ModelsPage.reference.less';

.defaults-panel {
  margin-top: 20px;
  padding: 20px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-lg);
}
.defaults-panel h3 { margin: 0; font-size: var(--app-text-lg); }
.defaults-panel p, .field-hint { color: var(--td-text-color-secondary); }
.defaults-panel p { margin: 6px 0 0; }
.defaults-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  gap: 16px;
  margin-top: 16px;
}
.defaults-grid label, .editor-form label { display: grid; min-width: 0; gap: 8px; }
.editor-form { display: grid; gap: 16px; max-height: min(68vh, 720px); overflow-y: auto; padding: 2px; }
.field-hint { margin: 0; line-height: 1.5; }
</style>
