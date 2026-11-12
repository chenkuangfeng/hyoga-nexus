<script setup lang="ts">
/**
 * "待实现" / "未验证" badge for a knowledge feature (openspec 2026-11-06-knowledge-base K0, decision 5).
 *
 * Renders nothing for an implemented, verified feature. Pages place it next to any entry, option or form
 * section that maps to a catalog item; the disabled state of the control itself comes from
 * `useKnowledgeCapabilitiesStore().available(group, key)`.
 */
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CapabilityGroup } from '@nexus-web/core/api/nexus-knowledge'
import { useKnowledgeCapabilitiesStore } from '@/stores/knowledgeCapabilities'

const props = defineProps<{ group: CapabilityGroup, capability: string }>()
const { t } = useI18n()
const store = useKnowledgeCapabilitiesStore()
onMounted(() => { void store.ensureLoaded() })

const state = computed(() => store.state(props.group, props.capability))
const text = computed(() => {
  const value = state.value
  if (value.kind === 'planned') return value.stage ? t('planned.badgeStage', { stage: value.stage }) : t('planned.badge')
  return value.kind === 'unverified' ? t('planned.unverified') : ''
})
const tip = computed(() => state.value.kind === 'planned' ? t('planned.plannedTip') : t('planned.unverifiedTip'))
</script>

<template>
  <t-tooltip v-if="text" :content="tip">
    <span class="capability-badge" :class="`capability-badge--${state.kind}`">{{ text }}</span>
  </t-tooltip>
</template>

<style scoped>
.capability-badge {
  display: inline-flex; align-items: center; margin-left: 6px; padding: 0 6px; height: 18px;
  border-radius: var(--app-radius-pill); font-size: var(--app-text-xs); line-height: 18px; white-space: nowrap;
  vertical-align: middle;
}
.capability-badge--planned { color: var(--td-warning-color); background: var(--td-warning-color-1); }
.capability-badge--unverified { color: var(--td-brand-color); background: var(--td-brand-color-1); }
</style>
