<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <main class="not-found">
    <t-result theme="default" :title="t('navigationErrors.notFoundTitle')" :description="t('navigationErrors.notFoundDescription')">
      <template #extra>
        <t-link href="/" theme="primary">{{ t('navigationErrors.backWorkspace') }}</t-link>
      </template>
    </t-result>
  </main>
</template>

<style scoped>
.not-found {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
}
</style>
