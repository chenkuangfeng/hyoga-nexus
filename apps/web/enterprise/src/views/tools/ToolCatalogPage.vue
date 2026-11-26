<script setup lang="ts">
/** 企业内置工具目录；停用影响新建/编辑绑定，已发布智能体版本保留原绑定。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { disableBuiltinResource, getAgentToolCatalog, restoreBuiltinResource, type AgentToolCatalog, type AgentToolEntry } from '@nexus-web/core/api/nexus-agents'
import { toolDisplayName, toolDisplayDescription } from '@nexus-web/core/utils/toolPresentation'
import { useEnterpriseContext } from '../../stores/context'

const { t, te } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('tools:manage'))
const catalog = ref<AgentToolCatalog | null>(null), loading = ref(false), busy = ref(''), error = ref(''), ready = ref(false)
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const sections = computed(() => {
  const tools = catalog.value?.tools ?? [], order = catalog.value?.groups ?? []
  const keys = [...new Set([...order, ...tools.map((tool) => tool.group)])]
  return keys.map(key => {
    const members = tools.filter(tool => tool.group === key)
    const manageable = members.filter(tool => tool.builtin)
    const selected = manageable.filter(tool => !tool.disabled).length
    return { key, tools: members, manageable, selected, partial: selected > 0 && selected < manageable.length,
      enabled: selected > 0 }
  }).filter(group => group.tools.length)
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
function toolLabel(tool: AgentToolEntry) { return toolDisplayName(tool.name, t, te) }
function toolDescription(tool: AgentToolEntry) { return toolDisplayDescription(tool, t, te) }

/** Stop on partial failure or scope changes and always refresh server facts before clearing feedback. */
async function change(tools: AgentToolEntry[], disable: boolean, marker: string, request: number,
  scope: string, user: string, revision: number) {
  if (!current(request, scope, user, revision) || busy.value) return
  busy.value = marker; error.value = ''
  let failed = false
  try {
    for (const tool of tools) {
      if (!current(request, scope, user, revision)) return
      if (disable) await disableBuiltinResource(scope, 'tool', tool.name, true)
      else await restoreBuiltinResource(scope, 'tool', tool.name, true)
    }
    if (current(request, scope, user, revision)) MessagePlugin.success(t('toolUi.groupUpdated'))
  } catch { failed = true }
  finally {
    if (current(request, scope, user, revision)) {
      const next = epoch + 1
      await load()
      if (failed && ready.value && current(next, scope, user, revision)) error.value = t('toolUi.batchFailed')
    }
  }
}

function toggleTools(tools: AgentToolEntry[], enabled: boolean, marker: string, label: string) {
  if (!canManage.value || !ready.value || busy.value) return
  const candidates = tools.filter(tool => tool.builtin && Boolean(tool.disabled) === enabled)
  if (!candidates.length) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  if (enabled) { void change(candidates, false, marker, request, scope, user, revision); return }
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminToolCatalog.disableTitle'),
    body: t(tools.length > 1 ? 'toolUi.groupDisableConfirm' : 'adminToolCatalog.disableConfirm', { name: label }), theme: 'warning',
    onConfirm: () => { if (confirmation !== dialog) return; dialog.hide(); confirmation = undefined; void change(candidates, true, marker, request, scope, user, revision) },
    onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
const props = defineProps<{ embedded?: boolean }>()
</script>

<template>
  <section class="tool-catalog-page">
    <header class="section-header"><div v-if="!props.embedded"><h2>{{ t('adminToolCatalog.title') }}</h2><p>{{ t('adminToolCatalog.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="!!busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert theme="info" :message="t('adminToolCatalog.scopeHint')" />
      <p class="tool-switch-description">{{ t('toolUi.description') }}</p>
      <t-loading :loading="loading">
        <section v-for="section in sections" :key="section.key" class="tool-group">
          <header class="tool-group-header">
            <h3>{{ groupLabel(section.key) }} <span>{{ t('toolUi.selected', { selected: section.selected, count: section.manageable.length }) }}</span></h3>
            <t-tag v-if="section.partial" size="small" theme="warning">{{ t('toolUi.partial') }}</t-tag>
            <t-switch :value="section.enabled" :disabled="!ready || !!busy || !section.manageable.length"
              role="switch" :aria-checked="section.enabled" :tabindex="!ready || !!busy || !section.manageable.length ? -1 : 0"
              @keydown.space.prevent="toggleTools(section.manageable, !section.enabled, `group:${section.key}`, groupLabel(section.key))"
              @keydown.enter.prevent="toggleTools(section.manageable, !section.enabled, `group:${section.key}`, groupLabel(section.key))"
              :loading="busy === `group:${section.key}`" :aria-label="`${groupLabel(section.key)} · ${t('toolUi.master')}`"
              @change="(value: boolean) => toggleTools(section.manageable, value, `group:${section.key}`, groupLabel(section.key))" />
          </header>
          <article v-for="tool in section.tools" :key="tool.name" class="tool-row" :class="{ disabled: tool.disabled }">
            <div class="tool-heading"><strong>{{ toolLabel(tool) }}</strong><t-tag variant="light" theme="warning">{{ riskLabel(tool) }}</t-tag><t-tag v-if="tool.requires_approval" variant="light" theme="primary">{{ t('nexusAgent.requiresApproval') }}</t-tag><t-tag v-if="tool.read_only" variant="light">{{ t('nexusAgent.readOnly') }}</t-tag><t-tag v-if="tool.disabled" variant="light" theme="danger">{{ t('adminToolCatalog.off') }}</t-tag><span class="spacer" />
              <t-switch v-if="tool.builtin" :value="!tool.disabled" :loading="busy === tool.name"
                role="switch" :aria-checked="!tool.disabled" :tabindex="!ready || !!busy ? -1 : 0"
                @keydown.space.prevent="toggleTools([tool], !!tool.disabled, tool.name, toolLabel(tool))"
                @keydown.enter.prevent="toggleTools([tool], !!tool.disabled, tool.name, toolLabel(tool))"
                :disabled="!ready || !!busy" :aria-label="toolLabel(tool)"
                @change="(value: boolean) => toggleTools([tool], value, tool.name, toolLabel(tool))" />
            </div>
            <p>{{ toolDescription(tool) || t('adminToolCatalog.noDescription') }}</p>
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
.tool-group-header { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.tool-group-header > .t-switch { margin-left: auto; }
.tool-switch-description { color: var(--td-text-color-secondary); }
.tool-row { .provider-card(); display: block; }
.tool-catalog-page { min-width: 0; }
.tool-group { margin-top: 20px; }
.tool-group h3 { display: flex; align-items: baseline; gap: 8px; margin: 0 0 8px; font-size: var(--app-text-md); }
.tool-group h3 span, .tool-row p, .tool-row small { color: var(--td-text-color-secondary); }
.tool-group h3 span, .tool-row small { font-size: var(--app-text-xs); font-weight: normal; }
.tool-row { padding: 14px 16px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); margin-bottom: 8px; }
.tool-row.disabled { opacity: .72; }
.tool-heading { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.tool-heading strong { overflow-wrap: anywhere; font-family: inherit; }
.spacer { flex: 1; }
.tool-row p { margin: 8px 0 4px; line-height: 1.5; overflow-wrap: anywhere; }
.empty { padding: 24px; color: var(--td-text-color-secondary); text-align: center; }
</style>
