<script setup lang="ts">
/**
 * Placeholder for pages outside the current implementation phase.
 *
 * The sidebar and routes keep WeKnora's entries so the menu is complete, but the copied pages call
 * WeKnora's backend contracts. Until a phase implements the page against the Nexus API, the route
 * renders this notice instead of issuing requests.
 */
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

const { t } = useI18n()
const route = useRoute()
</script>

<template>
  <section class="planned-page" :aria-label="t('planned.title')">
    <h1>{{ t('planned.title') }}</h1>
    <p>{{ t('planned.body') }}</p>
    <p class="planned-path"><code>{{ route.fullPath }}</code></p>
  </section>
</template>

<style scoped>
.planned-page { max-width: 640px; margin: 48px auto; padding: 24px; line-height: 1.6; }
.planned-page h1 { font-size: var(--app-text-3xl); margin: 0 0 12px; }
.planned-page p { margin: 0 0 8px; color: var(--td-text-color-secondary); }
.planned-path code { font-size: var(--app-text-sm); }
</style>
