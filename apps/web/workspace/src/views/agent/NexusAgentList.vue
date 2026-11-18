<script setup lang="ts">
import { useAssistantDataChange } from '@nexus-web/core/utils/assistantDataChange'
/** 员工智能体目录只查看和使用；不载入创建、编辑、复制、归档或渠道配置。 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listNexusAgents, type NexusAgent } from '@nexus-web/core/api/nexus-agents'
import ResourceDirectoryCard from '@nexus-web/core/components/ResourceDirectoryCard.vue'
const auth = useAuthStore(), router = useRouter(), { t } = useI18n()
const agents = ref<NexusAgent[]>([]), loading = ref(false), error = ref(''), keyword = ref(''), selected = ref<NexusAgent | null>(null)
let generation = 0
const filtered = computed(() => agents.value.filter(row => `${row.name} ${row.description || ''}`.toLowerCase().includes(keyword.value.toLowerCase())))
async function load() {
  const current = ++generation, tenant = String(auth.effectiveTenantId || '')
  agents.value = []; selected.value = null; error.value = ''; loading.value = false
  if (!tenant) return
  loading.value = true
  try { const rows = await listNexusAgents(tenant); if (current === generation) agents.value = rows }
  catch { if (current === generation) error.value = t('nexusAgent.loadFailed') }
  finally { if (current === generation) loading.value = false }
}
watch(() => `${auth.effectiveTenantId}:${auth.user?.id}:${auth.currentTenantRole}`, load, { immediate: true })
onBeforeUnmount(() => generation++)
useAssistantDataChange(() => { void load() }, { areas: ['agent'] })
function useAgent(agent: NexusAgent) {
  if (!agent.published_version_id || agent.status !== 'published') { MessagePlugin.warning(t('nexusAgent.notPublished')); return }
  void router.push({ path: '/platform/creatChat', query: { agent: agent.published_version_id } })
}
</script>
<template>
  <section class="resource-directory">
    <header><div><h2>{{ t('menu.agents') }}</h2><p>{{ t('agent.subtitle') }}</p></div><t-input v-model="keyword" clearable :placeholder="t('nexusAgent.searchPlaceholder')" :aria-label="t('nexusAgent.searchPlaceholder')"><template #prefix-icon><t-icon name="search" /></template></t-input></header>
    <t-alert v-if="error" theme="error" :message="error"><template #operation><t-button variant="text" @click="load">{{ t('common.retry') }}</t-button></template></t-alert>
    <t-loading :loading="loading"><div class="resource-grid">
      <ResourceDirectoryCard v-for="agent in filtered" :key="agent.id" :title="agent.name" :description="agent.description" icon="app" interactive @open="selected = agent">
        <t-button variant="text" @click="selected = agent">{{ t('consoleLayout.viewAgent') }}</t-button><t-button theme="primary" variant="text" :disabled="!agent.published_version_id || agent.status !== 'published'" @click="useAgent(agent)">{{ t('consoleLayout.useAgent') }}</t-button>
      </ResourceDirectoryCard>
    </div><t-empty v-if="!loading && !error && !filtered.length" :description="t('nexusAgent.empty')" /></t-loading>
    <t-dialog :visible="!!selected" :header="selected?.name" :footer="false" @close="selected = null"><p class="agent-description">{{ selected?.description || t('agent.noDescription') }}</p><t-button v-if="selected" :disabled="!selected.published_version_id || selected.status !== 'published'" @click="useAgent(selected)">{{ t('consoleLayout.useAgent') }}</t-button></t-dialog>
  </section>
</template>
<style scoped>
.resource-directory { padding: 24px; overflow: auto; min-width: 0; }
header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
header :deep(.t-input__wrap) { width: min(100%, 280px); }
h2 { margin: 0; font-size: var(--app-text-4xl); } header p { color: var(--td-text-color-secondary); }
.resource-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(min(100%,300px),1fr)); gap: 20px; }
.agent-description { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
