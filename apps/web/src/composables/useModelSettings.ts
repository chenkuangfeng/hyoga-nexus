import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../api/chat'
import { modelSettingsApi as settingsApi } from '../api/modelSettings'
import type { Workspace } from '../types/chat'
import type { ModelProvider, ModelSettings, SettingsScope } from '../types/modelSettings'

/** Own settings state, dialogs and mutually exclusive writes for one mounted page.
 * Workspace queries are aborted on replacement/unmount; late results cannot replace current data.
 * Mutations surface sanitized API errors. Key inputs clear on submit completion or unmount and
 * are never persisted to browser storage. Scope checks remain authoritative on the server.
 */
export function useModelSettings() {
  const workspaces = ref<Workspace[]>([]), workspace = ref(''), loading = ref(false), busy = ref(false), error = ref(''), feedback = ref('')
  const data = ref<ModelSettings>({ providers: [], defaults: {}, can_manage_workspace: false })
  const providerDialog = ref(false), modelDialog = ref(false), editingProvider = ref(''), editingModel = ref(''), modelProvider = ref('')
  const form = reactive({ name: '', base_url: '', scope: 'personal' as SettingsScope, api_key: '' })
  const modelProtocol = ref('openai_chat_completions'), modelStream = ref(true), modelTextTools = ref(false), reasoningEffort = ref(''), temperature = ref<number | undefined>(undefined)
  const modelName = ref(''), agentName = ref(''), instructions = ref('You are a helpful assistant.'), agentModel = ref('')
  let controller: AbortController | undefined, disposed = false
  const models = computed(() => data.value.providers.flatMap(provider => provider.models.map(model => ({ ...model, label: `${provider.name} / ${model.name}`, scope: provider.scope }))))
  async function load() {
    if (disposed) return
    controller?.abort(); controller = new AbortController(); const signal = controller.signal
    if (!workspace.value) { data.value.providers = []; return }
    loading.value = true; error.value = ''; data.value = { providers: [], defaults: {}, can_manage_workspace: false }
    try {
      const result = await settingsApi.list(workspace.value, signal)
      if (!signal.aborted && !disposed) { data.value = result; agentModel.value = result.defaults.personal || result.defaults.workspace || '' }
    } catch (e) { if (!signal.aborted && !disposed) error.value = e instanceof Error ? e.message : '加载失败' }
    finally { if (!signal.aborted && !disposed) loading.value = false }
  }
  async function perform(action: () => Promise<void>, message = '') {
    if (busy.value || disposed) return
    busy.value = true; error.value = ''; feedback.value = ''
    try { await action(); if (!disposed && message) feedback.value = message }
    catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '操作未完成' }
    finally { if (!disposed) busy.value = false }
  }
  function editProvider(provider?: ModelProvider) {
    editingProvider.value = provider?.id || ''
    Object.assign(form, { name: provider?.name || '', base_url: provider?.base_url || '', scope: provider?.scope || 'personal', api_key: '' })
    providerDialog.value = true
  }
  function editModel(provider: string, id = '', name = '') { modelProvider.value = provider; editingModel.value = id; modelName.value = name; const options = data.value.providers.find(p => p.id === provider)?.models.find(m => m.id === id)?.options || {}; modelProtocol.value = typeof options.protocol === 'string' ? options.protocol : 'openai_chat_completions'; modelStream.value = options.stream !== false; modelTextTools.value = options.text_tools === true; reasoningEffort.value = typeof options.reasoning_effort === 'string' ? options.reasoning_effort : ''; temperature.value = typeof options.temperature === 'number' ? options.temperature : undefined; modelDialog.value = true }
  const saveProvider = () => perform(async () => {
    const value = { name: form.name.trim(), base_url: form.base_url.trim(), scope: form.scope, ...(form.api_key ? { api_key: form.api_key } : {}) }
    try { await settingsApi.saveProvider(workspace.value, value, editingProvider.value || undefined); providerDialog.value = false; await load() }
    finally { form.api_key = '' }
  }, '供应商已保存')
  const saveModel = () => perform(async () => { await settingsApi.saveModel(workspace.value, modelProvider.value, modelName.value.trim(), editingModel.value || undefined, { protocol: modelProtocol.value, stream: modelStream.value, text_tools: modelTextTools.value, ...(reasoningEffort.value ? { reasoning_effort: reasoningEffort.value } : {}), ...(temperature.value !== undefined ? { temperature: temperature.value } : {}) }); modelDialog.value = false; await load() }, '模型已保存')
  const setDefault = (scope: SettingsScope, version: string | null) => perform(async () => { await settingsApi.setDefault(workspace.value, scope, version); await load() }, '默认模型已更新')
  async function confirmRemove(provider: ModelProvider, model?: { id: string; name: string }) {
    try { await ElMessageBox.confirm(`停用“${model?.name || provider.name}”后，相关默认设置将清除，已有会话使用它时将无法继续调用。历史记录会保留。`, '确认停用', { confirmButtonText: '停用', cancelButtonText: '取消', type: 'warning' }) } catch { return }
    await perform(async () => { if (model) await settingsApi.removeModel(workspace.value, provider.id, model.id); else await settingsApi.removeProvider(workspace.value, provider.id); await load() }, '已停用')
  }
  const test = (provider: string, model: string) => perform(async () => { const result = await settingsApi.test(workspace.value, provider, model); if (!result.ok) throw new Error(result.message); feedback.value = result.message })
  const createAgent = () => perform(async () => { await settingsApi.createAgent(workspace.value, agentName.value.trim(), instructions.value, agentModel.value); agentName.value = '' }, '智能体已发布，可以返回对话工作台新建会话')
  async function initialize() {
    loading.value = true
    try { const rows = await api.workspaces(); if (!disposed) { workspaces.value = rows; workspace.value = rows[0]?.id || ''; await load() } }
    catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '空间加载失败' }
    finally { if (!disposed) loading.value = false }
  }
  onMounted(initialize)
  onBeforeUnmount(() => { disposed = true; controller?.abort(); form.api_key = '' })
  return { workspaces, workspace, loading, busy, error, feedback, data, models, providerDialog, modelDialog, form,
    editingProvider, modelName, modelProtocol, modelStream, modelTextTools, reasoningEffort, temperature, agentName, instructions, agentModel, load, initialize, editProvider, editModel, saveProvider, saveModel, setDefault, confirmRemove, test, createAgent }
}
