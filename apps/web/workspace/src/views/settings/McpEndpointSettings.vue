<script setup lang="ts">
/** MCP 连接保持后端现有企业作用域；tools:manage 管理，普通成员只读，不扩大签发权限。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { createEndpoint, deleteEndpoint, ENDPOINT_TOOLS, fetchConnectionPermissions, listEndpointKnowledge, listEndpoints, revokeEndpointToken, rotateEndpointToken, updateEndpoint, type Endpoint, type EndpointInput, type KnowledgeChoice } from '@nexus-web/core/api/enterprise-connections'
import { useApiBaseUrlDisplay } from '@/composables/useApiBaseUrlDisplay'
import { copyWithToast } from '@/utils/clipboard'
import { buildHttpClientSnippet, buildMcpEndpointUrl } from '@/utils/mcpEndpointSnippets'

const props = withDefaults(defineProps<{ active?: boolean }>(), { active: true })
const { t } = useI18n()
const auth = useAuthStore()
const { apiBaseUrlDisplay } = useApiBaseUrlDisplay()
const tenantId = computed(() => String(auth.effectiveTenantId || ''))
const endpoints = ref<Endpoint[]>([]), bases = ref<KnowledgeChoice[]>([])
const loading = ref(false), busy = ref(false), canManage = ref(false), ready = ref(false)
const error = ref(''), editorOpen = ref(false), editingId = ref('')
const freshToken = ref(''), issuedEndpoint = ref<Endpoint | null>(null)
const form = reactive<EndpointInput>({ name: '', description: '', tool_allowlist: [], kb_ids: [] })
let epoch = 0
const kbOptions = computed(() => bases.value.map(base => ({ value: base.id, label: base.name })))
const toolOptions = ENDPOINT_TOOLS.map(name => ({ value: name, label: name }))
const rules = computed(() => ({ name: [{ required: true, message: t('connectionUi.nameRequired'), type: 'error' }, { pattern: /^[a-z0-9-]{1,64}$/, message: t('connectionUi.endpointNameHint'), type: 'error' }] }))
function url(row: Endpoint): string { return buildMcpEndpointUrl(apiBaseUrlDisplay.value, `/mcp/${encodeURIComponent(row.id)}`) }
const snippet = computed(() => issuedEndpoint.value ? buildHttpClientSnippet(issuedEndpoint.value.name, url(issuedEndpoint.value), freshToken.value, issuedEndpoint.value.id) : '')
function message(reason: unknown): string { return reason instanceof Error && reason.message !== 'connection_response_invalid' ? reason.message : t('connectionUi.failed') }
function clearToken() { freshToken.value = ''; issuedEndpoint.value = null }
function closeEditor() { editorOpen.value = false; editingId.value = ''; Object.assign(form, { name: '', description: '', tool_allowlist: [], kb_ids: [] }) }
async function reload() {
  const current = ++epoch
  clearToken(); closeEditor(); endpoints.value = []; bases.value = []; canManage.value = false; ready.value = false; error.value = ''; loading.value = false; busy.value = false
  if (!props.active || !tenantId.value) return
  const tenant = tenantId.value
  loading.value = true
  try {
    const rows = await listEndpoints(tenant)
    if (current !== epoch) return
    endpoints.value = rows
    const [permissions, knowledge] = await Promise.all([fetchConnectionPermissions(tenant), listEndpointKnowledge(tenant)])
    if (current !== epoch) return
    canManage.value = permissions.includes('tools:manage'); bases.value = knowledge; ready.value = true
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) loading.value = false }
}
function openEditor(row?: Endpoint) {
  if (!canManage.value || !ready.value || busy.value || (row && !endpoints.value.some(item => item.id === row.id))) return
  editingId.value = row?.id || ''
  Object.assign(form, { name: row?.name || '', description: row?.description || '', tool_allowlist: [...(row?.tool_allowlist || [])], kb_ids: [...(row?.kb_ids || [])] })
  editorOpen.value = true
}
async function save({ validateResult }: { validateResult: unknown }) {
  if (validateResult !== true || !ready.value || !canManage.value || busy.value) return
  const current = epoch, tenant = tenantId.value, id = editingId.value
  const input = { name: form.name.trim(), description: form.description, tool_allowlist: [...form.tool_allowlist], kb_ids: [...form.kb_ids] }
  busy.value = true; error.value = ''
  try {
    if (id) {
      const row = await updateEndpoint(tenant, id, input)
      if (current === epoch) { endpoints.value = endpoints.value.map(item => item.id === row.id ? row : item); closeEditor() }
    } else {
      const result = await createEndpoint(tenant, input)
      if (current === epoch) { endpoints.value.unshift(result.endpoint); closeEditor(); issuedEndpoint.value = result.endpoint; freshToken.value = result.token }
    }
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) busy.value = false }
}
function act(row: Endpoint, operation: 'rotate' | 'revoke' | 'delete' | 'toggle') {
  if (!ready.value || !canManage.value || busy.value || !endpoints.value.some(item => item.id === row.id)) return
  const current = epoch, tenant = tenantId.value
  const dialog = DialogPlugin.confirm({
    header: t(`connectionUi.endpointActions.${operation}`), body: t(`connectionUi.endpointConfirm.${operation}`),
    onConfirm: async () => {
      if (current !== epoch || busy.value) { dialog.hide(); return }
      busy.value = true; error.value = ''; dialog.hide()
      try {
        if (operation === 'rotate') {
          const result = await rotateEndpointToken(tenant, row.id)
          if (current === epoch) { issuedEndpoint.value = result.endpoint; freshToken.value = result.token }
        } else if (operation === 'revoke') { await revokeEndpointToken(tenant, row.id) }
        else if (operation === 'delete') { await deleteEndpoint(tenant, row.id); if (current === epoch) endpoints.value = endpoints.value.filter(item => item.id !== row.id) }
        else { const updated = await updateEndpoint(tenant, row.id, { enabled: !row.enabled }); if (current === epoch) endpoints.value = endpoints.value.map(item => item.id === updated.id ? updated : item) }
      } catch (reason) { if (current === epoch) error.value = message(reason) }
      finally { if (current === epoch) busy.value = false }
    },
    onClose: () => dialog.hide(),
  })
}
watch([tenantId, () => props.active, () => auth.user?.id], () => { void reload() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { epoch++; clearToken(); closeEditor() })
</script>

<template>
  <section class="endpoint-settings">
    <h2>{{ t('connectionUi.endpoints') }}</h2>
    <p>{{ t('connectionUi.endpointScope') }}</p>
    <t-alert v-if="error" theme="error" :message="error" />
    <div class="endpoint-actions"><t-button variant="outline" :loading="loading" :disabled="busy" @click="reload">{{ t('connectionUi.refresh') }}</t-button><t-button v-if="canManage" theme="primary" :disabled="!ready || busy" @click="openEditor()">{{ t('connectionUi.create') }}</t-button></div>
    <t-loading :loading="loading">
      <p v-if="!loading && !endpoints.length">{{ t('connectionUi.noEndpoints') }}</p>
      <article v-for="row in endpoints" :key="row.id" class="endpoint-card">
        <h3>{{ row.name }} <t-tag v-if="!row.enabled" theme="warning">{{ t('connectionUi.status.disabled') }}</t-tag></h3>
        <p>{{ row.description }}</p><code>{{ url(row) }}</code><t-button variant="text" @click="copyWithToast(url(row))">{{ t('common.copy') }}</t-button>
        <div v-if="canManage" class="endpoint-actions">
          <t-button :disabled="busy || !ready" variant="outline" @click="openEditor(row)">{{ t('common.edit') }}</t-button>
          <t-button v-for="operation in (['toggle', 'rotate', 'revoke', 'delete'] as const)" :key="operation" :disabled="busy" variant="outline" @click="act(row, operation)">{{ t(`connectionUi.endpointActions.${operation}`) }}</t-button>
        </div>
      </article>
    </t-loading>
    <t-dialog :visible="editorOpen" :header="t('connectionUi.endpoints')" :footer="false" @close="closeEditor">
      <t-form :data="form" :rules="rules" :disabled="busy" layout="vertical" @submit="save">
        <t-form-item name="name" :label="t('connectionUi.name')"><t-input v-model="form.name" :maxlength="64" /></t-form-item>
        <t-form-item :label="t('connectionUi.description')"><t-textarea v-model="form.description" :maxlength="4000" /></t-form-item>
        <t-form-item :label="t('connectionUi.tools')"><t-select v-model="form.tool_allowlist" :options="toolOptions" multiple filterable /></t-form-item>
        <t-form-item :label="t('connectionUi.knowledge')"><t-select v-model="form.kb_ids" :options="kbOptions" multiple filterable /></t-form-item>
        <p>{{ t('connectionUi.knowledgeScope') }}</p>
        <t-button type="submit" theme="primary" :loading="busy">{{ t('common.save') }}</t-button>
      </t-form>
    </t-dialog>
    <t-dialog :visible="!!freshToken" :header="t('connectionUi.tokenTitle')" :footer="false" :close-on-overlay-click="false" @close="clearToken">
      <p>{{ t('connectionUi.tokenOnce') }}</p><pre class="endpoint-token">{{ snippet }}</pre>
      <t-button @click="copyWithToast(snippet)">{{ t('common.copy') }}</t-button>
      <t-button variant="outline" @click="clearToken">{{ t('common.close') }}</t-button>
    </t-dialog>
  </section>
</template>
<style scoped>
.endpoint-settings { display: grid; gap: 16px; }
.endpoint-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.endpoint-card { padding: 16px; border: 1px solid var(--td-component-border); border-radius: var(--td-radius-default); }
.endpoint-card code { overflow-wrap: anywhere; }
.endpoint-token { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 60vh; overflow: auto; }
h2,h3,p { margin: 8px 0; }
</style>
