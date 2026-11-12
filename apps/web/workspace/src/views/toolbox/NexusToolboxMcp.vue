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

    <t-loading :loading="loading" size="small">
      <p v-if="!loading && !services.length" class="tbm-empty">{{ $t('toolbox.mcp.empty') }}</p>

      <article v-for="service in services" :key="service.id" :class="['tbm-row', { 'tbm-off': !service.enabled }]">
        <div class="tbm-main">
          <span class="tbm-name">{{ service.name }}</span>
          <span class="tbm-badge tbm-badge--muted">{{ $t(`toolbox.mcp.transports.${service.transport}`) }}</span>
          <span :class="['tbm-badge', service.enabled ? 'tbm-badge--on' : 'tbm-badge--muted']">
            {{ $t(service.enabled ? 'common.on' : 'common.off') }}
          </span>
          <span class="tbm-spacer" />
          <t-switch v-if="isAdmin" :value="service.enabled" size="small" :loading="togglingId === service.id"
            :aria-label="$t('toolbox.mcp.toggleEnabled', { name: service.name })"
            @change="(value: unknown) => setEnabled(service, value === true)" />
          <template v-if="isAdmin">
            <t-link theme="primary" size="small" :disabled="discoveringId === service.id" @click="discover(service)">
              {{ discoveringId === service.id ? $t('toolbox.mcp.discovering') : $t('toolbox.mcp.discover') }}
            </t-link>
            <t-link theme="primary" size="small" @click="toggleTools(service)">
              {{ openTools === service.id ? $t('toolbox.mcp.hideTools') : $t('toolbox.mcp.showTools') }}
            </t-link>
            <t-link theme="primary" size="small" @click="openEdit(service)">{{ $t('common.edit') }}</t-link>
            <t-popconfirm :content="$t('toolbox.mcp.deleteConfirm', { name: service.name })"
              @confirm="remove(service)">
              <t-link theme="danger" size="small">{{ $t('common.delete') }}</t-link>
            </t-popconfirm>
          </template>
        </div>
        <p class="tbm-target">{{ serviceTarget(service) }}</p>
        <p v-if="service.description" class="tbm-desc">{{ service.description }}</p>

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
            </div>
          </t-loading>
        </div>
      </article>
    </t-loading>

    <NexusMcpServiceDialog v-model:visible="dialogVisible" :tenant-id="tenantId" :service="editing"
      @saved="onSaved" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  deleteMcpService, discoverMcpService, listMcpServiceTools, listMcpServices, setEnabledMcpTools,
  updateMcpService, type McpService, type McpServiceTool,
} from '@nexus-web/core/api/nexus-mcp'
import { getMyApiPermissions } from '@nexus-web/core/api/nexus-agents'
import NexusMcpServiceDialog from './NexusMcpServiceDialog.vue'
import { enabledToolNames, serviceTarget } from './toolboxMcp'

const props = defineProps<{ tenantId: string }>()
const emit = defineEmits<{ (event: 'count', value: number): void }>()
const { t, te } = useI18n()

const services = ref<McpService[]>([])
const loading = ref(false)
const error = ref('')
const isAdmin = ref(false)

const dialogVisible = ref(false)
const editing = ref<McpService | null>(null)
const discoveringId = ref('')
const togglingId = ref('')

const openTools = ref('')
const tools = ref<McpServiceTool[]>([])
const toolsLoading = ref(false)
const savingTools = ref(false)

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
  loading.value = true
  error.value = ''
  try {
    services.value = await listMcpServices(props.tenantId)
    emit('count', services.value.length)
  } catch (cause) {
    error.value = failure(cause, 'toolbox.mcp.loadFailed')
  } finally {
    loading.value = false
  }
}

async function loadPermissions() {
  try {
    isAdmin.value = (await getMyApiPermissions(props.tenantId)).includes('tools:manage')
  } catch {
    // A refused permission lookup just means no editing affordances; server calls stay authoritative.
    isAdmin.value = false
  }
}

async function loadTools(serviceId: string) {
  toolsLoading.value = true
  error.value = ''
  try {
    // A stale response for a service the user already collapsed must not replace the current list.
    const rows = await listMcpServiceTools(props.tenantId, serviceId)
    if (openTools.value === serviceId) tools.value = rows
  } catch (cause) {
    error.value = failure(cause, 'toolbox.mcp.loadFailed')
  } finally {
    toolsLoading.value = false
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
  MessagePlugin.success(t(editing.value ? 'toolbox.mcp.saved' : 'toolbox.mcp.created'))
  await load()
  // A connection-parameter change invalidates the cached catalog; close the now-stale tool panel.
  if (openTools.value === saved.id) {
    openTools.value = ''
    tools.value = []
  }
}

async function discover(service: McpService) {
  if (discoveringId.value) return
  discoveringId.value = service.id
  error.value = ''
  try {
    const result = await discoverMcpService(props.tenantId, service.id)
    MessagePlugin.success(t('toolbox.mcp.discovered', { count: result.tools.length }))
    if (openTools.value === service.id) await loadTools(service.id)
  } catch (cause) {
    error.value = failure(cause, 'toolbox.mcp.discoverFailed')
  } finally {
    discoveringId.value = ''
  }
}

async function setEnabled(service: McpService, enabled: boolean) {
  if (togglingId.value || enabled === service.enabled) return
  togglingId.value = service.id
  error.value = ''
  try {
    const saved = await updateMcpService(props.tenantId, service.id, { enabled })
    services.value = services.value.map((row) => row.id === saved.id ? saved : row)
  } catch (cause) {
    error.value = failure(cause, 'toolbox.mcp.actionFailed')
  } finally {
    togglingId.value = ''
  }
}

/** Replace the whitelist with the checkbox state; the server re-checks every name against the catalog. */
async function setToolEnabled(service: McpService, tool: McpServiceTool, enabled: boolean) {
  if (savingTools.value || enabled === tool.enabled) return
  const previous = tools.value
  tools.value = tools.value.map((row) => row.tool_name === tool.tool_name ? { ...row, enabled } : row)
  savingTools.value = true
  error.value = ''
  try {
    await setEnabledMcpTools(props.tenantId, service.id, enabledToolNames(tools.value))
  } catch (cause) {
    tools.value = previous
    error.value = failure(cause, 'toolbox.mcp.actionFailed')
  } finally {
    savingTools.value = false
  }
}

async function remove(service: McpService) {
  error.value = ''
  try {
    await deleteMcpService(props.tenantId, service.id)
    MessagePlugin.success(t('toolbox.mcp.deleted'))
    if (openTools.value === service.id) {
      openTools.value = ''
      tools.value = []
    }
    await load()
  } catch (cause) {
    error.value = failure(cause, 'toolbox.mcp.actionFailed')
  }
}

onMounted(() => { void loadPermissions() })
watch(() => props.tenantId, () => {
  openTools.value = ''
  tools.value = []
  editing.value = null
  void loadPermissions()
  void load()
}, { immediate: true })
</script>

<style scoped>
.tbm-alert { margin-bottom: 8px; }
.tbm-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
.tbm-hint { margin: 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.tbm-empty { margin: 0; color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
.tbm-row { padding: 10px 0; border-bottom: 1px solid var(--td-component-stroke); }
.tbm-off .tbm-name { color: var(--td-text-color-secondary); }
.tbm-main { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
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
@media (max-width: 768px) {
  .tbm-head { flex-direction: column; align-items: stretch; }
}
</style>
