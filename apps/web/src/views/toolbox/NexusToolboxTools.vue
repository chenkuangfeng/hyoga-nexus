<template>
  <!--
    Toolbox "Tools" tab (openspec 2026-11-08-toolbox): the builtin tool catalog by group, with each tool's risk and whether
    this space offers it. Administrators switch builtin tools off and on for the space; nothing here changes how a tool works.
  -->
  <div class="tbt">
    <t-alert v-if="error" theme="error" :message="error" class="tbt-alert" />
    <t-loading :loading="loading" size="small">
      <section v-for="section in sections" :key="section.key" class="tbt-group">
        <h3 class="tbt-title">{{ groupLabel(section.key) }} <span class="tbt-count">{{ section.tools.length }}</span></h3>
        <div v-for="tool in section.tools" :key="tool.name" :class="['tbt-row', { 'tbt-off': toolState(tool) !== 'available' }]">
          <div class="tbt-main">
            <span class="tbt-name">{{ tool.name }}</span>
            <span v-if="tool.builtin" class="tbt-badge tbt-badge--muted">{{ $t('nexusAgent.builtin') }}</span>
            <span class="tbt-badge tbt-badge--muted">{{ riskLabel(tool) }}</span>
            <span v-if="tool.requires_approval" class="tbt-badge">{{ $t('nexusAgent.requiresApproval') }}</span>
            <span v-if="tool.read_only" class="tbt-badge tbt-badge--muted">{{ $t('nexusAgent.readOnly') }}</span>
            <span v-if="toolState(tool) === 'disabled'" class="tbt-badge">{{ $t('nexusAgent.disabledHere') }}</span>
            <span v-else-if="toolState(tool) === 'notEnabled'" class="tbt-badge">{{ $t('nexusAgent.notEnabled') }}</span>
            <span class="tbt-spacer" />
            <template v-if="isAdmin">
              <t-link v-if="toolAction(tool) === 'restore'" theme="primary" size="small" @click="act(() => restoreBuiltinResource(tenantId, 'tool', tool.name))">
                {{ $t('nexusAgent.restore') }}
              </t-link>
              <t-popconfirm v-else-if="toolAction(tool) === 'disable'" :content="$t('nexusAgent.disableHint')"
                @confirm="act(() => disableBuiltinResource(tenantId, 'tool', tool.name))">
                <t-link theme="default" size="small">{{ $t('nexusAgent.disableHere') }}</t-link>
              </t-popconfirm>
              <t-link v-else-if="toolAction(tool) === 'enable'" theme="primary" size="small" @click="act(() => enableTenantTool(tenantId, tool.name))">
                {{ $t('nexusAgent.enable') }}
              </t-link>
            </template>
          </div>
          <p class="tbt-desc">{{ tool.description }}</p>
        </div>
      </section>
      <p v-if="!loading && !sections.length" class="tbt-empty">{{ $t('toolbox.tools.empty') }}</p>
    </t-loading>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  disableBuiltinResource, enableTenantTool, getAgentToolCatalog, restoreBuiltinResource,
  type AgentToolCatalog, type AgentToolEntry,
} from '@/api/nexus-agents'
import { groupTools, toolAction, toolState } from './toolboxTools'

const props = defineProps<{ tenantId: string }>()
const emit = defineEmits<{ (event: 'count', value: number): void }>()
const { t, te } = useI18n()

const loading = ref(false)
const error = ref('')
const catalog = ref<AgentToolCatalog | null>(null)
const isAdmin = computed(() => !!catalog.value?.can_enable_tools)
const sections = computed(() => groupTools(catalog.value?.tools ?? [], catalog.value?.groups ?? []))

const groupLabel = (key: string) => te(`nexusAgent.toolGroups.${key}`) ? t(`nexusAgent.toolGroups.${key}`) : key
const riskLabel = (tool: AgentToolEntry) => t(`nexusAgent.risk.${tool.risk ?? tool.risk_level}`)

async function load() {
  loading.value = true
  error.value = ''
  try {
    catalog.value = await getAgentToolCatalog(props.tenantId)
    emit('count', catalog.value.tools.length)
  } catch (cause) {
    const record = (cause && typeof cause === 'object' ? cause : {}) as Record<string, unknown>
    error.value = typeof record.message === 'string' && record.message ? record.message : t('nexusAgent.loadFailed')
  } finally {
    loading.value = false
  }
}

async function act(change: () => Promise<void>) {
  error.value = ''
  try {
    await change()
  } catch (cause) {
    const record = (cause && typeof cause === 'object' ? cause : {}) as Record<string, unknown>
    error.value = typeof record.message === 'string' && record.message ? record.message : t('nexusAgent.switchFailed')
  }
  await load()
}

watch(() => props.tenantId, () => { void load() }, { immediate: true })
</script>

<style scoped>
.tbt-alert { margin-bottom: 8px; }
.tbt-group { margin-bottom: 16px; }
.tbt-title { margin: 0 0 6px; font-size: var(--app-text-md); display: flex; align-items: center; gap: 8px; }
.tbt-count { font-size: var(--app-text-xs); color: var(--td-text-color-secondary); font-weight: normal; }
.tbt-row { padding: 8px 0; border-bottom: 1px solid var(--td-component-stroke); }
.tbt-off .tbt-name { color: var(--td-text-color-secondary); }
.tbt-main { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tbt-name { font-weight: 600; font-family: var(--app-font-family-mono); }
.tbt-spacer { flex: 1; }
.tbt-badge { padding: 0 6px; font-size: var(--app-text-xs); border: 1px solid var(--td-warning-color); color: var(--td-warning-color); border-radius: var(--td-radius-small); }
.tbt-badge--muted { border-color: var(--td-component-border); color: var(--td-text-color-secondary); }
.tbt-desc { margin: 4px 0 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.tbt-empty { margin: 0; color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
</style>
