<script setup lang="ts">
import { useAssistantDataChange } from '@nexus-web/core/utils/assistantDataChange'
/** 员工只浏览可读知识库并维护获授权内容；建库和资源配置由企业管理端承接。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listKnowledgeBases } from '@nexus-web/core/api/knowledge-base/index'
import ResourceDirectoryCard from '@nexus-web/core/components/ResourceDirectoryCard.vue'
interface Base { id: string; name: string; description: string; knowledge_count: number; can_edit: boolean }
const auth = useAuthStore(), router = useRouter(), { t } = useI18n()
const rows = ref<Base[]>([]), keyword = ref(''), loading = ref(false), error = ref('')
let generation = 0
const filtered = computed(() => rows.value.filter(row => `${row.name} ${row.description}`.toLowerCase().includes(keyword.value.toLowerCase())))
async function load() {
  const current = ++generation; rows.value = []; error.value = ''; loading.value = false
  if (!auth.effectiveTenantId) return
  loading.value = true
  try {
    const result = await listKnowledgeBases()
    if (!Array.isArray(result.data)) throw new Error('Unexpected knowledge directory response')
    const values: Base[] = result.data.map((value: unknown) => {
      if (!value || typeof value !== 'object' || !('id' in value) || typeof value.id !== 'string' || !('name' in value) || typeof value.name !== 'string') throw new Error('Unexpected knowledge base')
      return { id: value.id, name: value.name, description: 'description' in value && typeof value.description === 'string' ? value.description : '', knowledge_count: 'knowledge_count' in value && typeof value.knowledge_count === 'number' ? value.knowledge_count : 0, can_edit: 'can_edit' in value && value.can_edit === true }
    })
    if (current === generation) rows.value = values
  } catch { if (current === generation) error.value = t('knowledgeList.messages.loadFailed') }
  finally { if (current === generation) loading.value = false }
}
watch(() => `${auth.effectiveTenantId}:${auth.user?.id}:${auth.currentTenantRole}`, load, { immediate: true })
onBeforeUnmount(() => generation++)
useAssistantDataChange(() => { void load() }, { areas: ['knowledge_base'] })
</script>
<template>
  <section class="kb-directory"><header><div><h2>{{ t('menu.knowledgeBase') }}</h2><p>{{ t('knowledgeList.subtitle') }}</p></div><t-input v-model="keyword" clearable :placeholder="t('menu.search')" :aria-label="t('menu.search')"><template #prefix-icon><t-icon name="search" /></template></t-input></header>
    <t-alert v-if="error" theme="error" :message="error"><template #operation><t-button variant="text" @click="load">{{ t('common.retry') }}</t-button></template></t-alert>
    <t-loading :loading="loading"><div class="kb-grid"><ResourceDirectoryCard v-for="row in filtered" :key="row.id" :title="row.name" :description="row.description" interactive @open="router.push(`/platform/knowledge-bases/${encodeURIComponent(row.id)}`)"><span>{{ t('adminKnowledge.documents', { count: row.knowledge_count }) }}</span><t-button variant="text" @click="router.push(`/platform/knowledge-bases/${encodeURIComponent(row.id)}`)">{{ t('adminKnowledge.content.open') }}</t-button></ResourceDirectoryCard></div><t-empty v-if="!loading && !error && !filtered.length" :description="t('common.noResult')" /></t-loading>
  </section>
</template>
<style scoped>
.kb-directory { padding: 24px; overflow: auto; min-width: 0; }
header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
header :deep(.t-input__wrap) { width: min(100%,280px); } h2 { margin: 0; font-size: var(--app-text-4xl); } header p { color: var(--td-text-color-secondary); }
.kb-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(min(100%,300px),1fr)); gap: 20px; }
</style>
