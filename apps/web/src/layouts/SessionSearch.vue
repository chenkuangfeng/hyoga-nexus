<script setup lang="ts">
/**
 * Session search palette (WeKnora's search entry). It filters the sessions already loaded for the
 * current space by title; no backend search is involved. Up/Down move the selection, Enter opens,
 * Escape closes (the dialog handles Escape).
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Conversation } from '../types/chat'

const props = defineProps<{ modelValue: boolean; sessions: Conversation[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; open: [id: string] }>()
const { t } = useI18n()
const query = ref(''), cursor = ref(0), input = ref<HTMLInputElement>()

const matches = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return props.sessions.filter(session => !needle || (session.title || '').toLowerCase().includes(needle))
})

// The dialog body is rendered after the open transition starts, so focus is moved on its `opened` event.
watch(() => props.modelValue, open => {
  if (open) { query.value = ''; cursor.value = 0 }
})
function focusInput() { input.value?.focus() }
watch(query, () => { cursor.value = 0 })

function close() { emit('update:modelValue', false) }
function open(id: string) { close(); emit('open', id) }
function move(step: number) {
  if (!matches.value.length) return
  cursor.value = (cursor.value + step + matches.value.length) % matches.value.length
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') { event.preventDefault(); move(1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1) }
  else if (event.key === 'Enter') { const target = matches.value[cursor.value]; if (target) { event.preventDefault(); open(target.id) } }
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="t('shell.search')" width="min(520px, 94vw)" append-to-body @update:model-value="(value: boolean) => emit('update:modelValue', value)" @opened="focusInput">
    <label class="visually-hidden" for="session-search-input">{{ t('shell.searchPlaceholder') }}</label>
    <input id="session-search-input" ref="input" v-model="query" class="search-input" type="search" role="combobox" aria-controls="session-search-list" :aria-expanded="matches.length > 0" :aria-activedescendant="matches[cursor] ? `session-search-${matches[cursor].id}` : undefined" :placeholder="t('shell.searchPlaceholder')" @keydown="onKey">
    <ul v-if="matches.length" id="session-search-list" class="search-list" role="listbox">
      <li v-for="(session, index) in matches" :id="`session-search-${session.id}`" :key="session.id" role="option" :aria-selected="index === cursor" class="search-option" :class="{ active: index === cursor }" @mouseenter="cursor = index" @click="open(session.id)">
        {{ session.title || t('common.unnamed') }}
      </li>
    </ul>
    <p v-else class="muted">{{ t('shell.searchEmpty') }}</p>
    <p class="muted hint">{{ t('shell.searchHint') }}</p>
  </el-dialog>
</template>

<style scoped>
.search-input { width: 100%; min-height: 40px; padding: 8px 12px; box-sizing: border-box; border: 1px solid var(--border); border-radius: 8px; font: inherit; }
.search-input:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.search-list { list-style: none; margin: 12px 0 0; padding: 0; max-height: 50vh; overflow-y: auto; display: grid; gap: 2px; }
.search-option { padding: 8px 10px; border-radius: 6px; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search-option.active { background: var(--selected); }
.muted { color: var(--muted-text); font-size: 13px; }
.hint { margin-top: 12px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
