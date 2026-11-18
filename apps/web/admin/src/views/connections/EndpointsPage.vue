<script setup lang="ts">
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
/** 企业 MCP 只读工具端点管理；令牌仅在签发后的当前页面内存中短暂保存。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { copyWithToast } from '@nexus-web/core/utils/clipboard'
import { getApiBaseUrl } from '@nexus-web/core/utils/api-base'
import {
  createEndpoint, deleteEndpoint, ENDPOINT_TOOLS, listEndpointKnowledge, listEndpoints,
  revokeEndpointToken, rotateEndpointToken, updateEndpoint,
  type Endpoint, type EndpointInput, type KnowledgeChoice,
} from '@nexus-web/core/api/enterprise-connections'
import { useAdminContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('tools:manage'))
const endpoints = ref<Endpoint[]>([]), bases = ref<KnowledgeChoice[]>([])
const loading = ref(false), busy = ref(false), ready = ref(false), error = ref('')
const editorOpen = ref(false), editingId = ref(''), freshToken = ref(''), issuedEndpoint = ref<Endpoint | null>(null)
const form = reactive<EndpointInput>({ name: '', description: '', tool_allowlist: [], kb_ids: [] })
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const toolOptions = ENDPOINT_TOOLS.map(name => ({ value: name, label: name }))
const knowledgeOptions = computed(() => bases.value.map(base => ({ value: base.id, label: base.name })))
const rules = computed(() => ({ name: [
  { required: true, message: t('connectionUi.nameRequired'), type: 'error' as const },
  { pattern: /^[a-z0-9-]{1,64}$/, message: t('connectionUi.endpointNameHint'), type: 'error' as const },
] }))
const publicApiBase = computed(() => {
  const base = getApiBaseUrl().trim().replace(/\/+$/, '')
  const path = `${base}/api/v1`, origin = typeof window === 'undefined' ? '' : window.location.origin
  return origin && origin !== 'null' ? new URL(path, origin).href : path
})
function endpointUrl(row: Endpoint) {
  const base = publicApiBase.value.replace(/\/+$/, '').replace(/\/api\/v1$/, '')
  return `${base}/mcp/${encodeURIComponent(row.id)}`
}
const tokenSnippet = computed(() => {
  if (!issuedEndpoint.value || !freshToken.value) return ''
  const slug = issuedEndpoint.value.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  const key = slug ? `nexus-${slug}` : `nexus-${issuedEndpoint.value.id.replace(/[^a-z0-9]/gi, '').slice(0, 8).toLowerCase()}`
  return JSON.stringify({ mcpServers: { [key]: { url: endpointUrl(issuedEndpoint.value), headers: { Authorization: `Bearer ${freshToken.value}` } } } }, null, 2)
})
function current(currentEpoch: number, scope: string, user: string, revision: number) {
  return currentEpoch === epoch && scope === tenant.value && user === String(auth.user?.id || '') && revision === context.revision && canManage.value
}
function clearToken() { freshToken.value = ''; issuedEndpoint.value = null }
function closeEditor() {
  editorOpen.value = false; editingId.value = ''
  Object.assign(form, { name: '', description: '', tool_allowlist: [], kb_ids: [] })
}
function invalidate() {
  epoch++; confirmation?.hide(); confirmation = undefined
  endpoints.value = []; bases.value = []; ready.value = false; loading.value = false; busy.value = false; error.value = ''
  clearToken(); closeEditor()
}
async function load() {
  invalidate()
  if (!canManage.value || !tenant.value) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  loading.value = true
  try {
    const [rows, knowledge] = await Promise.all([listEndpoints(scope, true), listEndpointKnowledge(scope, true)])
    if (!current(request, scope, user, revision)) return
    endpoints.value = rows; bases.value = knowledge; ready.value = true
  } catch { if (current(request, scope, user, revision)) error.value = t('connectionUi.failed') }
  finally { if (current(request, scope, user, revision)) loading.value = false }
}
function openEditor(row?: Endpoint) {
  if (!canManage.value || !ready.value || busy.value || (row && !endpoints.value.some(item => item.id === row.id))) return
  editingId.value = row?.id || ''
  Object.assign(form, { name: row?.name || '', description: row?.description || '', tool_allowlist: [...(row?.tool_allowlist || [])], kb_ids: [...(row?.kb_ids || [])] })
  editorOpen.value = true; error.value = ''
}
async function save({ validateResult }: { validateResult: unknown }) {
  if (validateResult !== true || !ready.value || !canManage.value || busy.value) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision, id = editingId.value
  const input = { name: form.name.trim(), description: form.description, tool_allowlist: [...form.tool_allowlist], kb_ids: [...form.kb_ids] }
  busy.value = true; error.value = ''
  try {
    if (id) {
      const updated = await updateEndpoint(scope, id, input, true)
      if (!current(request, scope, user, revision)) return
      endpoints.value = endpoints.value.map(row => row.id === id ? updated : row); closeEditor()
      void MessagePlugin.success(t('adminConnections.saved'))
    } else {
      const result = await createEndpoint(scope, input, true)
      if (!current(request, scope, user, revision)) return
      endpoints.value = [result.endpoint, ...endpoints.value]; closeEditor()
      issuedEndpoint.value = result.endpoint; freshToken.value = result.token
    }
  } catch { if (current(request, scope, user, revision)) error.value = t('connectionUi.failed') }
  finally { if (current(request, scope, user, revision)) busy.value = false }
}
function confirmAction(row: Endpoint, operation: 'rotate' | 'revoke' | 'delete' | 'toggle') {
  if (!ready.value || !canManage.value || busy.value || confirmation || !endpoints.value.some(item => item.id === row.id)) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  const dialog = DialogPlugin.confirm({
    header: t(`connectionUi.endpointActions.${operation}`), body: t(`connectionUi.endpointConfirm.${operation}`),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (!current(request, scope, user, revision) || busy.value) return
      busy.value = true; error.value = ''
      try {
        if (operation === 'rotate') {
          const result = await rotateEndpointToken(scope, row.id, true)
          if (!current(request, scope, user, revision)) return
          clearToken(); issuedEndpoint.value = result.endpoint; freshToken.value = result.token
        } else if (operation === 'revoke') {
          await revokeEndpointToken(scope, row.id, true)
          if (!current(request, scope, user, revision)) return
          if (issuedEndpoint.value?.id === row.id) clearToken()
          void MessagePlugin.success(t('adminConnections.tokenRevoked'))
        } else if (operation === 'delete') {
          await deleteEndpoint(scope, row.id, true)
          if (!current(request, scope, user, revision)) return
          endpoints.value = endpoints.value.filter(item => item.id !== row.id)
          if (issuedEndpoint.value?.id === row.id) clearToken()
          void MessagePlugin.success(t('adminConnections.deleted'))
        } else {
          const updated = await updateEndpoint(scope, row.id, { enabled: !row.enabled }, true)
          if (!current(request, scope, user, revision)) return
          endpoints.value = endpoints.value.map(item => item.id === row.id ? updated : item)
        }
      } catch { if (current(request, scope, user, revision)) error.value = t('connectionUi.failed') }
      finally { if (current(request, scope, user, revision)) busy.value = false }
    },
    onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
watch([tenant, () => auth.user?.id, () => context.revision, canManage], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { invalidate() })
</script>

<template>
  <section class="endpoints-page">
    <header class="section-header"><div><h2>{{ t('consoleLayout.mcpPublish') }}</h2><p>{{ t('adminConnections.description') }}</p></div><div class="actions"><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button><t-button v-if="canManage" theme="primary" :disabled="!ready || busy" @click="openEditor()"><t-icon name="add" />{{ t('connectionUi.create') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminConnections.scopeHint')" />
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading">
        <div v-if="ready && !endpoints.length" class="empty-state"><t-icon name="link" size="40px" /><p>{{ t('connectionUi.noEndpoints') }}</p><t-button theme="primary" @click="openEditor()">{{ t('connectionUi.create') }}</t-button></div>
        <div v-else-if="ready" class="channel-grid">
          <article v-for="row in endpoints" :key="row.id" class="channel-card channel-card--clickable" role="button" tabindex="0" @click="!busy && openEditor(row)" @keydown.enter.self.prevent="!busy && openEditor(row)" @keydown.space.self.prevent="!busy && openEditor(row)">
            <div class="channel-card__badge"><t-icon name="tools" size="22px" /></div><div class="channel-card__body"><div class="channel-card__header"><h3 class="channel-card__title">{{ row.name }}</h3><t-tag v-if="!row.enabled" theme="warning">{{ t('connectionUi.status.disabled') }}</t-tag></div><span class="channel-card__agent-name">{{ t('adminConnections.allowedTools', { count: row.tool_allowlist.length }) }} · {{ row.kb_ids.length ? t('adminConnections.selectedKnowledge', { count: row.kb_ids.length }) : t('connectionUi.knowledgeScope') }}</span></div>
            <div class="channel-card__actions" @click.stop @keydown.stop><t-dropdown :options="[{content:t('common.edit'),value:'edit'},{content:t(row.enabled?'common.off':'common.on'),value:'toggle'},{content:t('connectionUi.endpointActions.rotate'),value:'rotate'},{content:t('connectionUi.endpointActions.revoke'),value:'revoke'},{content:t('connectionUi.endpointActions.delete'),value:'delete'}]" :disabled="busy" @click="(option: { value?: string | number }) => { if(option.value === 'edit') openEditor(row); if(option.value === 'toggle' || option.value === 'rotate' || option.value === 'revoke' || option.value === 'delete') confirmAction(row, option.value) }"><t-button variant="text" shape="square" :aria-label="t('common.expand')"><t-icon name="ellipsis" /></t-button></t-dropdown><t-button variant="text" shape="square" :aria-label="t('common.copy')" @click="copyWithToast(endpointUrl(row),'common.copied')"><t-icon name="copy" /></t-button></div>
          </article>
          <button type="button" class="channel-card channel-card--add" :disabled="busy" @click="openEditor()"><span class="channel-card__badge"><t-icon name="add" /></span><span class="channel-card__body">{{ t('connectionUi.create') }}</span></button>
        </div>
      </t-loading>
    </template>
    <EditorDialog :visible="editorOpen" :header="t(editingId ? 'adminConnections.editTitle' : 'adminConnections.createTitle')" :footer="false" :close-btn="!busy" :close-on-overlay-click="!busy" @close="!busy && closeEditor()">
      <t-form :data="form" :rules="rules" :disabled="busy" layout="vertical" @submit="save">
        <t-form-item name="name" :label="t('connectionUi.name')"><t-input v-model="form.name" :maxlength="64" /></t-form-item>
        <t-form-item :label="t('connectionUi.description')"><t-textarea v-model="form.description" :maxlength="4000" /></t-form-item>
        <t-form-item :label="t('connectionUi.tools')"><t-select v-model="form.tool_allowlist" :options="toolOptions" multiple filterable /></t-form-item>
        <t-form-item :label="t('connectionUi.knowledge')"><t-select v-model="form.kb_ids" :options="knowledgeOptions" multiple filterable /></t-form-item>
        <p class="field-hint">{{ t('connectionUi.knowledgeScope') }}</p><t-button type="submit" theme="primary" :loading="busy">{{ t('common.save') }}</t-button>
      </t-form>
    </EditorDialog>
    <EditorDialog :visible="!!freshToken" :header="t('connectionUi.tokenTitle')" :footer="false" :close-on-overlay-click="false" @close="clearToken">
      <p>{{ t('connectionUi.tokenOnce') }}</p><pre class="token-snippet">{{ tokenSnippet }}</pre><div class="actions"><t-button theme="primary" @click="copyWithToast(tokenSnippet, 'common.copied')">{{ t('common.copy') }}</t-button><t-button variant="outline" @click="clearToken">{{ t('common.close') }}</t-button></div>
    </EditorDialog>
  </section>
</template>

<style scoped lang="less">
@import '@nexus-web/core/styles/channel-panel-list.less';
.endpoints-page { min-width: 0; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.endpoint-list { display: grid; gap: 16px; margin-top: 20px; }
.endpoint-card { min-width: 0; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.endpoint-card > header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
h3 { margin: 0; overflow-wrap: anywhere; font-size: var(--app-text-lg); }
.endpoint-card p { color: var(--td-text-color-secondary); line-height: 1.5; }
.endpoint-card code { overflow-wrap: anywhere; }
.scope-summary { margin-bottom: 12px; }
.token-snippet { max-height: min(60vh, 600px); overflow: auto; padding: 14px; border-radius: var(--app-radius-md); background: var(--td-bg-color-container-hover); white-space: pre-wrap; overflow-wrap: anywhere; }
.field-hint { color: var(--td-text-color-secondary); line-height: 1.5; }
.empty-state { display: grid; justify-items: center; gap: 12px; padding: 56px 16px; color: var(--td-text-color-secondary); }
@media (max-width: 640px) { .endpoint-card > header { align-items: stretch; flex-direction: column; } }
</style>
