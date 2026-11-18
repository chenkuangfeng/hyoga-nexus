<template>
  <!--
    Toolbox "MCP" tab (openspec 2026-11-08-mcp, decision 5, tasks 4.1–4.2). The minimum useful
    flow from WeKnora: list services, switch one off, discover its tools, and enable individual
    tools. Administrators additionally create/edit/delete services. Authorization is decided by
    the server; hiding buttons only keeps members out of dead ends.
  -->
  <div class="tbm">
    <t-alert v-if="error" theme="error" :message="error" class="tbm-alert" />

    <div class="tbm-head">
      <p class="tbm-hint">{{ $t(isAdmin ? 'toolbox.mcp.hintAdmin' : 'toolbox.mcp.hintMember') }}</p>
      <t-button v-if="isAdmin" theme="primary" variant="outline" size="small" @click="openCreate">
        <template #icon><t-icon name="add" size="16px" /></template>
        {{ $t('toolbox.mcp.add') }}
      </t-button>
    </div>

    <t-input v-model="query" class="list-search" clearable :placeholder="$t('menu.search')" :aria-label="$t('menu.search')"><template #prefix-icon><t-icon name="search" /></template></t-input>
    <t-loading :loading="loading" size="small">
      <p v-if="!loading && !filteredServices.length" class="tbm-empty">{{ $t('toolbox.mcp.empty') }}</p>

      <div class="services-grid"><article v-for="service in filteredServices" :key="service.id" :class="['service-card', { 'tbm-off': !service.enabled }]">
        <div class="service-card__main"><div class="service-card__body">
          <div class="service-card__header">
            <span class="service-card__badge" aria-hidden="true"><t-icon name="tools" size="14px" /></span>
            <h3 class="service-card__title" :title="service.name">{{ service.name }}</h3>
            <div v-if="isAdmin" class="service-card__actions">
              <t-button variant="text" shape="square" size="small" :aria-label="$t('common.edit')" @click="openEdit(service)"><t-icon name="edit" /></t-button>
              <t-popconfirm :content="$t('toolbox.mcp.deleteConfirm', { name: service.name })" @confirm="remove(service)"><t-button variant="text" theme="danger" shape="square" size="small" :aria-label="$t('common.delete')"><t-icon name="delete" /></t-button></t-popconfirm>
            </div>
          </div>
          <p class="service-card__subtitle tbm-target">{{ serviceTarget(service) }}</p>
          <p v-if="service.description" class="service-card__desc tbm-desc">{{ service.description }}</p>
        </div></div>
        <div class="service-card__footer tbm-controls">
          <span class="tbm-badge tbm-badge--muted">{{ $t(`toolbox.mcp.transports.${service.transport}`) }}</span>
          <span :class="['tbm-badge', service.enabled ? 'tbm-badge--on' : 'tbm-badge--muted']">{{ $t(service.enabled ? 'common.on' : 'common.off') }}</span>
          <t-switch v-if="isAdmin" :value="service.enabled" size="small" :loading="togglingId === service.id" :aria-label="$t('toolbox.mcp.toggleEnabled', { name: service.name })" @change="(value: unknown) => setEnabled(service, value === true)" />
          <template v-if="isAdmin">
            <t-link theme="primary" size="small" :disabled="discoveringId === service.id" @click="discover(service)">{{ discoveringId === service.id ? $t('toolbox.mcp.discovering') : $t('toolbox.mcp.discover') }}</t-link>
            <t-link theme="primary" size="small" @click="toggleTools(service)">{{ openTools === service.id ? $t('toolbox.mcp.hideTools') : $t('toolbox.mcp.showTools') }}</t-link>
          </template>
        </div>

        <div v-if="openTools === service.id" class="tbm-tools">
          <t-loading :loading="toolsLoading" size="small">
            <p v-if="!toolsLoading && !tools.length" class="tbm-tools-empty">
              {{ $t(isAdmin ? 'toolbox.mcp.toolsEmptyAdmin' : 'toolbox.mcp.toolsEmptyMember') }}
            </p>
            <div v-for="tool in tools" :key="tool.tool_name" :class="['tbm-tool', { 'tbm-tool--off': !tool.enabled }]">
              <div class="tbm-tool-head">
                <t-checkbox :checked="tool.enabled" :disabled="!isAdmin || savingTools"
                  @change="(value: unknown) => setToolEnabled(service, tool, value === true)">
                  <span class="tbm-tool-name">{{ tool.tool_name }}</span>
                </t-checkbox>
                <span class="tbm-badge tbm-badge--muted">{{ $t(`toolbox.mcp.risk.${tool.effective_risk}`) }}</span>
                <span v-if="tool.require_approval" class="tbm-badge">{{ $t('toolbox.mcp.requiresApproval') }}</span>
                <span v-if="tool.pending_downgrade" class="tbm-badge">{{ $t('toolbox.mcp.pendingDowngrade') }}</span>
                <span v-if="tool.catalog_status === 'error'" class="tbm-badge">
                  {{ $t('toolbox.mcp.catalogError') }}
                </span>
              </div>
              <p v-if="tool.description" class="tbm-tool-desc">{{ tool.description }}</p>
              <div v-if="isAdmin" class="tbm-policy-controls">
                <label><span>{{ $t('toolbox.mcp.riskPolicy') }}</span><t-select :value="tool.explicit_risk || ''" :options="riskOptions" :disabled="!!policyBusyId" size="small" @change="(value: unknown) => setRisk(service, tool, value)" /></label>
                <label class="tbm-approval-control"><t-switch :value="tool.require_approval" size="small" :disabled="!!policyBusyId" :loading="policyBusyId === `${service.id}:${tool.tool_name}`" @change="(value: unknown) => setApproval(service, tool, value === true)" /><span>{{ $t('toolbox.mcp.approvalPolicy') }}</span></label>
              </div>
            </div>
          </t-loading>
        </div>
      </article></div>
    </t-loading>

    <NexusMcpServiceDialog v-model:visible="dialogVisible" :tenant-id="tenantId" :service="editing"
      @saved="onSaved" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import {
  deleteMcpService, discoverMcpService, listMcpServiceTools, listMcpServices, setEnabledMcpTools, setMcpToolPolicy,
  updateMcpService, type McpService, type McpServiceTool,
} from '@nexus-web/core/api/nexus-mcp'
import { getMyApiPermissions } from '@nexus-web/core/api/nexus-agents'
import NexusMcpServiceDialog from './NexusMcpServiceDialog.vue'
import { enabledToolNames, serviceTarget } from './toolboxMcp'

const props = defineProps<{ tenantId: string; canManage?: boolean }>()
const emit = defineEmits<{ (event: 'count', value: number): void }>()
const { t, te } = useI18n()

const services = ref<McpService[]>([])
const query = ref('')
const filteredServices = computed(() => services.value.filter(service => `${service.name} ${service.description || ''}`.toLowerCase().includes(query.value.toLowerCase())))
const loading = ref(false)
const error = ref('')
const isAdmin = ref(props.canManage === true)

const dialogVisible = ref(false)
const editing = ref<McpService | null>(null)
const discoveringId = ref('')
const togglingId = ref('')

const openTools = ref('')
const tools = ref<McpServiceTool[]>([])
const toolsLoading = ref(false)
const savingTools = ref(false)
const policyBusyId = ref('')
let generation = 0
const riskOptions = computed(() => [
  { value: '', label: t('toolbox.mcp.riskAutomatic') },
  ...(['read', 'write', 'destructive'] as const).map(value => ({ value, label: t(`toolbox.mcp.risk.${value}`) })),
])

/** Translate a stable backend error code when the bundle knows it; otherwise show the raw message. */
function failure(cause: unknown, fallbackKey: string): string {
  const record = (cause && typeof cause === 'object' ? cause : {}) as Record<string, unknown>
  const message = typeof record.message === 'string' ? record.message : ''
  if (message) {
    const key = `toolbox.mcp.errors.${message}`
    if (te(key)) return t(key)
    return message
  }
  return t(fallbackKey)
}

async function load() {
  const current = generation
  loading.value = true
  error.value = ''
  try {
    const rows = await listMcpServices(props.tenantId)
    if (current !== generation) return
    services.value = rows
    emit('count', services.value.length)
  } catch (cause) {
    if (current === generation) error.value = failure(cause, 'toolbox.mcp.loadFailed')
  } finally {
    if (current === generation) loading.value = false
  }
}

async function loadPermissions(current: number) {
  try {
    const permissions = await getMyApiPermissions(props.tenantId)
    if (current === generation) isAdmin.value = permissions.includes('tools:manage')
  } catch {
    // A refused permission lookup just means no editing affordances; server calls stay authoritative.
    if (current === generation) isAdmin.value = false
  }
}

async function loadTools(serviceId: string) {
  const current = generation
  toolsLoading.value = true
  error.value = ''
  try {
    // A stale response for a service the user already collapsed must not replace the current list.
    const rows = await listMcpServiceTools(props.tenantId, serviceId)
    if (current === generation && openTools.value === serviceId) tools.value = rows
  } catch (cause) {
    if (current === generation) error.value = failure(cause, 'toolbox.mcp.loadFailed')
  } finally {
    if (current === generation) toolsLoading.value = false
  }
}

function toggleTools(service: McpService) {
  if (openTools.value === service.id) {
    openTools.value = ''
    tools.value = []
    return
  }
  openTools.value = service.id
  tools.value = []
  void loadTools(service.id)
}

function openCreate() {
  editing.value = null
  dialogVisible.value = true
}

function openEdit(service: McpService) {
  editing.value = service
  dialogVisible.value = true
}

async function onSaved(saved: McpService) {
  const current = generation
  MessagePlugin.success(t(editing.value ? 'toolbox.mcp.saved' : 'toolbox.mcp.created'))
  await load()
  if (current !== generation) return
  // A connection-parameter change invalidates the cached catalog; close the now-stale tool panel.
  if (openTools.value === saved.id) {
    openTools.value = ''
    tools.value = []
  }
}

async function discover(service: McpService) {
  if (discoveringId.value) return
  const current = generation
  discoveringId.value = service.id
  error.value = ''
  try {
    const result = await discoverMcpService(props.tenantId, service.id)
    if (current !== generation) return
    MessagePlugin.success(t('toolbox.mcp.discovered', { count: result.tools.length }))
    if (openTools.value === service.id) await loadTools(service.id)
  } catch (cause) {
    if (current === generation) error.value = failure(cause, 'toolbox.mcp.discoverFailed')
  } finally {
    if (current === generation) discoveringId.value = ''
  }
}

async function setEnabled(service: McpService, enabled: boolean) {
  if (togglingId.value || enabled === service.enabled) return
  const current = generation
  togglingId.value = service.id
  error.value = ''
  try {
    const saved = await updateMcpService(props.tenantId, service.id, { enabled })
    if (current !== generation) return
    services.value = services.value.map((row) => row.id === saved.id ? saved : row)
  } catch (cause) {
    if (current === generation) error.value = failure(cause, 'toolbox.mcp.actionFailed')
  } finally {
    if (current === generation) togglingId.value = ''
  }
}

/** Replace the whitelist with the checkbox state; the server re-checks every name against the catalog. */
async function setToolEnabled(service: McpService, tool: McpServiceTool, enabled: boolean) {
  if (savingTools.value || enabled === tool.enabled) return
  const current = generation, previous = tools.value
  tools.value = tools.value.map((row) => row.tool_name === tool.tool_name ? { ...row, enabled } : row)
  savingTools.value = true
  error.value = ''
  try {
    await setEnabledMcpTools(props.tenantId, service.id, enabledToolNames(tools.value))
    if (current !== generation) return
  } catch (cause) {
    if (current !== generation) return
    tools.value = previous
    error.value = failure(cause, 'toolbox.mcp.actionFailed')
  } finally {
    if (current === generation) savingTools.value = false
  }
}

function setRisk(service: McpService, tool: McpServiceTool, value: unknown) {
  if (value !== '' && value !== 'read' && value !== 'write' && value !== 'destructive') return
  const next = value === '' ? null : value
  if (next === tool.explicit_risk) return
  const declaredRisk = tool.observed_risk || (tool.read_only_hint ? 'read' : 'write')
  const rank = { read: 0, write: 1, destructive: 2 } as const
  const downgrade = rank[next || declaredRisk] < rank[tool.effective_risk]
  if (!downgrade) { void savePolicy(service, tool, next, tool.require_approval); return }
  const dialog = DialogPlugin.confirm({
    header: t('toolbox.mcp.riskPolicy'), body: t('toolbox.mcp.riskDowngradeConfirm'),
    onConfirm: () => { dialog.hide(); void savePolicy(service, tool, next, tool.require_approval, true) },
    onClose: () => dialog.hide(),
  })
}

function setApproval(service: McpService, tool: McpServiceTool, enabled: boolean) {
  if (enabled !== tool.require_approval) void savePolicy(service, tool, tool.explicit_risk, enabled)
}

async function savePolicy(service: McpService, tool: McpServiceTool, risk: McpServiceTool['explicit_risk'], approval: boolean, confirmDowngrade = false) {
  if (policyBusyId.value) return
  const current = generation, key = `${service.id}:${tool.tool_name}`
  policyBusyId.value = key; error.value = ''
  try {
    const result = await setMcpToolPolicy(props.tenantId, service.id, tool.tool_name, {
      explicit_risk: risk, require_approval: approval, confirm_downgrade: confirmDowngrade,
    })
    if (current !== generation) return
    tools.value = tools.value.map(row => row.tool_name === tool.tool_name ? {
      ...row, explicit_risk: risk, effective_risk: result.effective_risk,
      require_approval: result.require_approval, pending_downgrade: result.pending_downgrade,
    } : row)
  } catch (cause) {
    if (current === generation) error.value = failure(cause, 'toolbox.mcp.actionFailed')
  } finally { if (current === generation) policyBusyId.value = '' }
}

async function remove(service: McpService) {
  const current = generation
  error.value = ''
  try {
    await deleteMcpService(props.tenantId, service.id)
    if (current !== generation) return
    MessagePlugin.success(t('toolbox.mcp.deleted'))
    if (openTools.value === service.id) {
      openTools.value = ''
      tools.value = []
    }
    await load()
  } catch (cause) {
    if (current === generation) error.value = failure(cause, 'toolbox.mcp.actionFailed')
  }
}

watch([() => props.tenantId, () => props.canManage], async () => {
  const current = ++generation
  services.value = []; tools.value = []; openTools.value = ''; error.value = ''; loading.value = false
  openTools.value = ''
  tools.value = []
  editing.value = null
  dialogVisible.value = false
  if (props.canManage === undefined) await loadPermissions(current)
  else isAdmin.value = props.canManage
  if (current === generation) void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; dialogVisible.value = false })
</script>

<style scoped lang="less">
@import './NexusToolboxMcp.reference.less';
.tbm-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--td-component-stroke); }
.tbm-alert { margin-bottom: 8px; }
.tbm-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
.tbm-hint { margin: 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.tbm-empty { margin: 0; color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
.tbm-row { padding: 10px 0; border-bottom: 1px solid var(--td-component-stroke); }
.tbm-off .tbm-name { color: var(--td-text-color-secondary); }
.tbm-main { flex-wrap: wrap; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tbm-name { font-weight: 600; }
.tbm-spacer { flex: 1; }
.tbm-badge { padding: 0 6px; font-size: var(--app-text-xs); border: 1px solid var(--td-warning-color); color: var(--td-warning-color); border-radius: var(--td-radius-small); }
.tbm-badge--muted { border-color: var(--td-component-border); color: var(--td-text-color-secondary); }
.tbm-badge--on { border-color: var(--td-success-color); color: var(--td-success-color); }
.tbm-target { margin: 4px 0 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); font-family: var(--app-font-family-mono); word-break: break-all; }
.tbm-desc { margin: 4px 0 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.tbm-tools { margin-top: 8px; padding: 8px 0 0 16px; border-left: 2px solid var(--td-component-stroke); }
.tbm-tools-empty { margin: 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); }
.tbm-tool { padding: 4px 0; }
.tbm-tool--off .tbm-tool-name { color: var(--td-text-color-secondary); }
.tbm-tool-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tbm-tool-name { font-family: var(--app-font-family-mono); }
.tbm-tool-desc { margin: 2px 0 0 24px; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.tbm-policy-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 6px 0 2px 24px; }
.tbm-policy-controls label { display: inline-flex; align-items: center; gap: 8px; color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.tbm-policy-controls label:first-child :deep(.t-select) { width: 132px; }
.tbm-approval-control { min-height: 32px; }
@media (max-width: 768px) {
  .tbm-head { flex-direction: column; align-items: stretch; }
}
</style>
