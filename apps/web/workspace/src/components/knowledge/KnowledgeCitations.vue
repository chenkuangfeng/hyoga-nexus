<script setup lang="ts">
/**
 * Sources of a knowledge-backed answer (openspec 2026-11-06-knowledge-base K1.8).
 *
 * Lists the documents behind the `[ID:n]` handles the answer cites. Only handles the server resolved against
 * the Run's evidence are listed; a handle the model invented has no entry here (and the Run recorded a
 * `knowledge.citation_invalid` event).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { KnowledgeCitation } from '@nexus-web/core/api/native-run-types'

const props = defineProps<{ citations: KnowledgeCitation[] }>()
const { t } = useI18n()
const router = useRouter()

const rows = computed(() => props.citations.map(item => ({
  key: `${item.handle}`,
  handle: item.handle,
  title: item.filename || item.chunk_id,
  where: [item.page ? t('knowledgeCitation.page', { page: item.page }) : '', ...(item.section || [])]
    .filter(Boolean).join(' · '),
  kbId: item.kb_id,
})))

function open(kbId?: string) {
  if (kbId) void router.push({ name: 'knowledgeBaseDetail', params: { kbId } })
}
</script>

<template>
  <div v-if="rows.length" class="knowledge-citations" data-testid="knowledge-citations">
    <span class="knowledge-citations__label">{{ t('knowledgeCitation.title') }}</span>
    <button v-for="row in rows" :key="row.key" type="button" class="knowledge-citations__item"
      :disabled="!row.kbId" @click="open(row.kbId)">
      <span class="knowledge-citations__handle">[{{ row.handle }}]</span>
      <span class="knowledge-citations__name">{{ row.title }}</span>
      <span v-if="row.where" class="knowledge-citations__where">{{ row.where }}</span>
    </button>
  </div>
</template>

<style scoped>
.knowledge-citations { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 6px 0 0; }
.knowledge-citations__label { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.knowledge-citations__item {
  display: inline-flex; gap: 6px; align-items: center; max-width: 100%; padding: 2px 8px; cursor: pointer;
  border: 1px solid var(--td-component-border); border-radius: var(--app-radius-pill); background: var(--td-bg-color-container);
  color: var(--td-text-color-primary); font-size: var(--app-text-xs);
}
.knowledge-citations__item:disabled { cursor: default; }
.knowledge-citations__handle { color: var(--td-brand-color); }
.knowledge-citations__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.knowledge-citations__where { color: var(--td-text-color-secondary); }
</style>
