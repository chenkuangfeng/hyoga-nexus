<script setup lang="ts">
/** 企业内置工具目录；停用影响新建/编辑绑定，已发布智能体版本保留原绑定。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { disableBuiltinResource, getAgentToolCatalog, restoreBuiltinResource, type AgentToolCatalog, type AgentToolEntry } from '@nexus-web/core/api/nexus-agents'
import { useAdminContext } from '../../stores/context'

const { t, te } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('tools:manage'))
const catalog = ref<AgentToolCatalog | null>(null), loading = ref(false), busy = ref(''), error = ref(''), ready = ref(false)
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const sections = computed(() => {
  const tools = catalog.value?.tools ?? [], order = catalog.value?.groups ?? []
  const keys = [...new Set([...order, ...tools.map((tool) => tool.group)])]
  return keys.map((key) => ({ key, tools: tools.filter((tool) => tool.group === key) })).filter((group) => group.tools.length)
})
function current(request: number, scope: string, user: string, revision: number) {
  return request === epoch && scope === tenant.value && user === String(auth.user?.id || '') && revision === context.revision && canManage.value
}
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; catalog.value = null; loading.value = false; busy.value = ''; error.value = ''; ready.value = false }
async function load() {
  invalidate()
  if (!canManage.value || !tenant.value) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  loading.value = true
  try { const result = await getAgentToolCatalog(scope, true); if (current(request, scope, user, revision)) { catalog.value = result; ready.value = true } }
  catch { if (current(request, scope, user, revision)) error.value = t('adminToolCatalog.loadFailed') }
  finally { if (current(request, scope, user, revision)) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
function groupLabel(group: string) { const key = `nexusAgent.toolGroups.${group}`; return te(key) ? t(key) : group }
function riskLabel(tool: AgentToolEntry) { return t(`nexusAgent.risk.${tool.risk ?? tool.risk_level}`) }
async function change(tool: AgentToolEntry, disable: boolean, request: number, scope: string, user: string, revision: number) {
  if (!current(request, scope, user, revision) || busy.value) return
  busy.value = tool.name; error.value = ''
  try {
    if (disable) await disableBuiltinResource(scope, 'tool', tool.name, true)
    else await restoreBuiltinResource(scope, 'tool', tool.name, true)
    if (!current(request, scope, user, revision)) return
    MessagePlugin.success(t(disable ? 'adminToolCatalog.disabled' : 'adminToolCatalog.restored'))
    await load()
  } catch { if (current(request, scope, user, revision)) error.value = t('adminToolCatalog.changeFailed') }
  finally { if (current(request, scope, user, revision)) busy.value = '' }
}
function confirmDisable(tool: AgentToolEntry) {
  if (!canManage.value || !ready.value || busy.value || !tool.builtin || tool.disabled) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminToolCatalog.disableTitle'), body: t('adminToolCatalog.disableConfirm', { name: tool.name }), theme: 'warning',
    onConfirm: () => { if (confirmation !== dialog) return; dialog.hide(); confirmation = undefined; void change(tool, true, request, scope, user, revision) },
    onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
function restore(tool: AgentToolEntry) { if (ready.value && !busy.value && tool.builtin && tool.disabled) void change(tool, false, epoch, tenant.value, String(auth.user?.id || ''), context.revision) }
</script>

<template>
  <section class="tool-catalog-page">
    <header class="section-header"><div><h2>{{ t('adminToolCatalog.title') }}</h2><p>{{ t('adminToolCatalog.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="!!busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert theme="info" :message="t('adminToolCatalog.scopeHint')" />
      <t-loading :loading="loading">
        <section v-for="section in sections" :key="section.key" class="tool-group">
          <h3>{{ groupLabel(section.key) }} <span>{{ section.tools.length }}</span></h3>
          <article v-for="tool in section.tools" :key="tool.name" class="tool-row" :class="{ disabled: tool.disabled }">
            <div class="tool-heading"><strong>{{ tool.name }}</strong><t-tag variant="light" theme="warning">{{ riskLabel(tool) }}</t-tag><t-tag v-if="tool.requires_approval" variant="light" theme="primary">{{ t('nexusAgent.requiresApproval') }}</t-tag><t-tag v-if="tool.read_only" variant="light">{{ t('nexusAgent.readOnly') }}</t-tag><t-tag v-if="tool.disabled" variant="light" theme="danger">{{ t('adminToolCatalog.off') }}</t-tag><span class="spacer" />
              <t-button v-if="tool.builtin && tool.disabled" size="small" variant="outline" :loading="busy === tool.name" :disabled="!!busy" @click="restore(tool)">{{ t('adminToolCatalog.restore') }}</t-button>
              <t-button v-else-if="tool.builtin" size="small" variant="text" theme="danger" :loading="busy === tool.name" :disabled="!!busy" @click="confirmDisable(tool)">{{ t('adminToolCatalog.disable') }}</t-button>
            </div>
            <p>{{ tool.description || t('adminToolCatalog.noDescription') }}</p>
            <small>{{ t('adminToolCatalog.effects', { value: tool.side_effects ? t('adminToolCatalog.hasEffects') : t('adminToolCatalog.noEffects') }) }}</small>
          </article>
        </section>
        <div v-if="ready && !sections.length" class="empty">{{ t('adminToolCatalog.empty') }}</div>
      </t-loading>
    </template>
  </section>
</template>

<style scoped lang="less">
@import (reference) '@nexus-web/core/styles/provider-card.less';
.tool-group { display: grid; grid-template-columns: repeat(auto-fill,minmax(min(100%,320px),1fr)); gap: 12px; }
.tool-group h3 { grid-column: 1 / -1; }
.tool-row { .provider-card(); display: block; }
.tool-catalog-page { min-width: 0; }
.tool-group { margin-top: 20px; }
.tool-group h3 { display: flex; align-items: baseline; gap: 8px; margin: 0 0 8px; font-size: var(--app-text-md); }
.tool-group h3 span, .tool-row p, .tool-row small { color: var(--td-text-color-secondary); }
.tool-group h3 span, .tool-row small { font-size: var(--app-text-xs); font-weight: normal; }
.tool-row { padding: 14px 16px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); margin-bottom: 8px; }
.tool-row.disabled { opacity: .72; }
.tool-heading { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.tool-heading strong { overflow-wrap: anywhere; font-family: var(--app-font-family-mono); }
.spacer { flex: 1; }
.tool-row p { margin: 8px 0 4px; line-height: 1.5; overflow-wrap: anywhere; }
.empty { padding: 24px; color: var(--td-text-color-secondary); text-align: center; }
</style>
