import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { workspace } from '../stores/workspace'
import { modelSettingsApi as settingsApi } from '../api/modelSettings'
import { MODEL_TYPES, type ConfiguredModel, type ModelProvider, type ModelSettings, type ModelType, type SettingsScope, type TestResult } from '../types/modelSettings'
import { presetsFor } from '../data/modelPresets'
import { i18n } from '../i18n'

/** Sentinel for "create a new provider while adding this model" in the model drawer. */
export const NEW_PROVIDER = '__new__'
/** Type tab filter: every model, or one capability type. */
export type TypeFilter = 'all' | ModelType
/** One model card: the configured model together with the provider that serves it. */
export interface ModelCard { provider: ModelProvider; model: ConfiguredModel; label: string; scope: SettingsScope }

/** Own settings state, dialogs and mutually exclusive writes for one mounted page.
 * Tenant queries are aborted on replacement/unmount; late results cannot replace current data.
 * Mutations surface sanitized API errors. Key inputs clear on submit completion or unmount and
 * are never persisted to browser storage. Scope checks remain authoritative on the server.
 *
 * Models are typed: each card carries its capability type, defaults are kept per type, and only
 * chat models can be picked for new agents. Non-chat types can be configured now and are used once
 * the knowledge-base stage lands.
 */
export function useModelSettings() {
  const tenants = computed(() => workspace.tenants), tenant = computed(() => workspace.tenantId)
  const loading = ref(false), busy = ref(false), error = ref(''), feedback = ref('')
  const data = ref<ModelSettings>({ providers: [], defaults: {}, can_manage_tenant: false })
  const activeType = ref<TypeFilter>('all')
  const providerDialog = ref(false), editingProvider = ref('')
  const form = reactive({ name: '', base_url: '', scope: 'personal' as SettingsScope, api_key: '' })
  const drawerOpen = ref(false), drawerTest = ref<TestResult | null>(null), drawerTesting = ref(false)
  const drawer = reactive({
    modelId: '', providerId: NEW_PROVIDER, type: 'chat' as ModelType, name: '',
    newName: '', newBaseUrl: '', newScope: 'personal' as SettingsScope, api_key: '',
    protocol: 'openai_chat_completions', stream: true, text_tools: false,
    temperature: undefined as number | undefined, reasoning_effort: '',
  })
  const agentName = ref(''), instructions = ref('You are a helpful assistant.'), agentModel = ref('')
  let controller: AbortController | undefined, disposed = false

  const models = computed<ModelCard[]>(() => data.value.providers.flatMap(provider => provider.models.map(model => ({ provider, model, label: `${provider.name} / ${model.name}`, scope: provider.scope }))))
  const cards = computed(() => activeType.value === 'all' ? models.value : models.value.filter(card => card.model.model_type === activeType.value))
  const typeCounts = computed(() => {
    const counts: Record<TypeFilter, number> = { all: models.value.length, chat: 0, embedding: 0, rerank: 0, vision: 0, speech: 0 }
    for (const card of models.value) counts[card.model.model_type] += 1
    return counts
  })
  /** Only chat models can power an agent in this stage. */
  const chatModels = computed(() => models.value.filter(card => card.model.model_type === 'chat'))
  /** Models that may fill a default slot of this type and scope: a space default cannot use a personal model. */
  const candidatesFor = (scope: SettingsScope, type: ModelType) => models.value.filter(card => card.model.model_type === type && (scope === 'personal' || card.scope === 'tenant'))
  const defaultFor = (scope: SettingsScope, type: ModelType) => data.value.defaults[scope]?.[type] || ''
  const canManage = (provider: ModelProvider) => provider.scope === 'personal' || data.value.can_manage_tenant
  /** Providers the caller may attach a new model to. */
  const manageableProviders = computed(() => data.value.providers.filter(canManage))
  const presets = computed(() => presetsFor(drawer.type))

  async function load() {
    if (disposed) return
    controller?.abort(); controller = new AbortController(); const signal = controller.signal
    if (!tenant.value) { data.value.providers = []; return }
    loading.value = true; error.value = ''; data.value = { providers: [], defaults: {}, can_manage_tenant: false }
    try {
      const result = await settingsApi.list(tenant.value, signal)
      if (!signal.aborted && !disposed) { data.value = result; agentModel.value = defaultFor('personal', 'chat') || defaultFor('tenant', 'chat') || '' }
    } catch (e) { if (!signal.aborted && !disposed) error.value = e instanceof Error ? e.message : i18n.global.t('common.loadFailed') }
    finally { if (!signal.aborted && !disposed) loading.value = false }
  }
  async function perform(action: () => Promise<void>, message = '') {
    if (busy.value || disposed) return
    busy.value = true; error.value = ''; feedback.value = ''
    try { await action(); if (!disposed && message) feedback.value = message }
    catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : i18n.global.t('common.opFailed') }
    finally { if (!disposed) busy.value = false }
  }
  function editProvider(provider?: ModelProvider) {
    editingProvider.value = provider?.id || ''
    Object.assign(form, { name: provider?.name || '', base_url: provider?.base_url || '', scope: provider?.scope || 'personal', api_key: '' })
    providerDialog.value = true
  }
  const saveProvider = () => perform(async () => {
    const value = { name: form.name.trim(), base_url: form.base_url.trim(), scope: form.scope, ...(form.api_key ? { api_key: form.api_key } : {}) }
    try { await settingsApi.saveProvider(tenant.value, value, editingProvider.value || undefined); providerDialog.value = false; await load() }
    finally { form.api_key = '' }
  }, i18n.global.t('modelSettings.providerSaved'))

  /** Open the model drawer for a new model (optionally of a given type) or to edit an existing card. */
  function openDrawer(card?: ModelCard, type?: ModelType) {
    drawerTest.value = null
    drawer.api_key = ''
    if (card) {
      const options = card.model.options || {}
      Object.assign(drawer, {
        modelId: card.model.id, providerId: card.provider.id, type: card.model.model_type, name: card.model.name,
        newName: '', newBaseUrl: '', newScope: 'personal',
        protocol: typeof options.protocol === 'string' ? options.protocol : 'openai_chat_completions',
        stream: options.stream !== false, text_tools: options.text_tools === true,
        reasoning_effort: typeof options.reasoning_effort === 'string' ? options.reasoning_effort : '',
        temperature: typeof options.temperature === 'number' ? options.temperature : undefined,
      })
    } else {
      const first = manageableProviders.value[0]
      Object.assign(drawer, {
        modelId: '', providerId: first ? first.id : NEW_PROVIDER, type: type || (activeType.value === 'all' ? 'chat' : activeType.value),
        name: '', newName: '', newBaseUrl: '', newScope: 'personal',
        protocol: 'openai_chat_completions', stream: true, text_tools: false, reasoning_effort: '', temperature: undefined,
      })
    }
    drawerOpen.value = true
  }
  /** Options sent with a model. Non-chat types carry only the default protocol. */
  function drawerOptions(): Record<string, unknown> {
    if (drawer.type !== 'chat') return { protocol: 'openai_chat_completions' }
    return {
      protocol: drawer.protocol, stream: drawer.stream, text_tools: drawer.text_tools,
      ...(drawer.reasoning_effort ? { reasoning_effort: drawer.reasoning_effort } : {}),
      ...(drawer.temperature !== undefined ? { temperature: drawer.temperature } : {}),
    }
  }
  function applyPreset(name: string) { drawer.name = name; drawerTest.value = null }
  const saveDrawer = () => perform(async () => {
    try {
      let providerId = drawer.providerId
      if (!drawer.modelId && providerId === NEW_PROVIDER) {
        const created = await settingsApi.saveProvider(tenant.value, { name: drawer.newName.trim() || i18n.global.t('modelPage.customProvider'), base_url: drawer.newBaseUrl.trim(), scope: drawer.newScope, api_key: drawer.api_key })
        // Keep the new provider selected so a failed model save can be retried without creating it again.
        providerId = created.id; drawer.providerId = created.id; drawer.api_key = ''
      }
      await settingsApi.saveModel(tenant.value, providerId, drawer.name.trim(), drawer.modelId || undefined, drawerOptions(), drawer.type)
      drawerOpen.value = false
      await load()
    } finally { drawer.api_key = '' }
  }, i18n.global.t('modelSettings.modelSaved'))
  /** Test the drawer's current configuration without saving it. */
  async function testDraft() {
    if (drawerTesting.value || disposed) return
    drawerTesting.value = true; drawerTest.value = null
    try {
      const provider = drawer.providerId === NEW_PROVIDER ? undefined : data.value.providers.find(item => item.id === drawer.providerId)
      const body = provider
        ? { scope: provider.scope, base_url: provider.base_url, provider_id: provider.id, api_key: drawer.api_key || undefined }
        : { scope: drawer.newScope, base_url: drawer.newBaseUrl.trim(), api_key: drawer.api_key || undefined }
      drawerTest.value = await settingsApi.testDraft(tenant.value, { ...body, model_name: drawer.name.trim(), model_type: drawer.type, options: drawerOptions() })
    } catch (e) {
      drawerTest.value = { ok: false, message: e instanceof Error ? e.message : i18n.global.t('common.opFailed') }
    } finally { drawer.api_key = ''; drawerTesting.value = false }
  }
  const setDefault = (scope: SettingsScope, type: ModelType, version: string | null) => perform(async () => { await settingsApi.setDefault(tenant.value, scope, type, version); await load() }, i18n.global.t('modelSettings.defaultUpdated'))
  async function confirmRemove(provider: ModelProvider, model?: { id: string; name: string }) {
    try { await ElMessageBox.confirm(i18n.global.t('modelSettings.disableConfirm', { name: model?.name || provider.name }), i18n.global.t('modelSettings.disableTitle'), { confirmButtonText: i18n.global.t('modelSettings.disableButton'), cancelButtonText: i18n.global.t('common.cancel'), type: 'warning' }) } catch { return }
    await perform(async () => { if (model) await settingsApi.removeModel(tenant.value, provider.id, model.id); else await settingsApi.removeProvider(tenant.value, provider.id); await load() }, i18n.global.t('modelSettings.disabled'))
  }
  const test = (provider: string, model: string) => perform(async () => { const result = await settingsApi.test(tenant.value, provider, model); if (!result.ok) throw new Error(testMessage(result)); feedback.value = testMessage(result) })
  const createAgent = () => perform(async () => { await settingsApi.createAgent(tenant.value, agentName.value.trim(), instructions.value, agentModel.value); agentName.value = '' }, i18n.global.t('modelSettings.agentPublished'))
  // The space comes from the shell's selector; a change reloads this page's data.
  async function initialize() {
    loading.value = true
    try { if (!disposed) await load() }
    catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : i18n.global.t('common.spaceLoadFailed') }
    finally { if (!disposed) loading.value = false }
  }
  /** Known backend codes map to translated text; anything else shows the server's sanitized message. */
  function testMessage(result: TestResult): string {
    return result.code === 'unsupported_for_type' ? i18n.global.t('modelPage.testUnsupported') : result.message
  }
  onMounted(initialize)
  watch(() => workspace.tenantId, () => { if (!disposed) void initialize() })
  onBeforeUnmount(() => { disposed = true; controller?.abort(); form.api_key = ''; drawer.api_key = '' })
  return { tenants, tenant, loading, busy, error, feedback, data, models, cards, typeCounts, chatModels, activeType,
    candidatesFor, defaultFor, canManage, manageableProviders, presets, testMessage,
    providerDialog, editingProvider, form, drawerOpen, drawerTest, drawerTesting, drawer, agentName, instructions, agentModel,
    MODEL_TYPES, load, initialize, editProvider, saveProvider, openDrawer, applyPreset, saveDrawer, testDraft, setDefault, confirmRemove, test, createAgent }
}
