<template>
  <div class="watchdog-banner" role="alert" aria-live="assertive" data-testid="watchdog-banner">
    <div class="watchdog-banner__header">
      <t-icon name="error-circle" class="watchdog-banner__icon" aria-hidden="true" />
      <div class="watchdog-banner__text">
        <div class="watchdog-banner__title">{{ $t('nativeRuns.watchdog.title') }}</div>
        <p class="watchdog-banner__body">{{ $t('nativeRuns.watchdog.body') }}</p>
      </div>
    </div>

    <div class="watchdog-banner__actions">
      <t-button size="small" variant="outline" :disabled="busy" data-testid="watchdog-continue"
        @click="emit('acknowledge')">
        {{ $t('nativeRuns.watchdog.continue') }}
      </t-button>
      <t-button size="small" variant="outline" :disabled="busy || !canHint" data-testid="watchdog-hint-toggle"
        :aria-expanded="hintOpen ? 'true' : 'false'" @click="hintOpen = !hintOpen">
        {{ $t('nativeRuns.watchdog.hint') }}
      </t-button>
      <t-button size="small" theme="danger" variant="outline" :disabled="busy" data-testid="watchdog-cancel"
        @click="emit('cancel')">
        {{ $t('nativeRuns.watchdog.cancel') }}
      </t-button>
    </div>

    <form v-if="hintOpen && canHint" class="watchdog-banner__hint" @submit.prevent="submitHint">
      <t-input v-model="hintText" :placeholder="$t('nativeRuns.hintPlaceholder')" :maxlength="8000"
        :disabled="busy" size="medium" data-testid="watchdog-hint-input" />
      <t-button type="submit" theme="primary" size="medium" :disabled="busy || !hintText.trim()"
        data-testid="watchdog-hint-send">
        {{ $t('nativeRuns.send') }}
      </t-button>
    </form>
  </div>
</template>

<script setup lang="ts">
/**
 * Shown while the server reports `attention_required` for a Run. It only offers actions; it does not
 * decide anything itself. The parent performs each action and refreshes the Run from the server.
 */
import { ref } from 'vue'

defineProps<{
  /** Corrections can be sent only while the Run is running. */
  canHint: boolean
  /** Disables every action while a request is in flight. */
  busy: boolean
}>()

const emit = defineEmits<{
  acknowledge: []
  cancel: []
  hint: [content: string]
}>()

const hintOpen = ref(false)
const hintText = ref('')

function submitHint() {
  const content = hintText.value.trim()
  if (!content) return
  emit('hint', content)
  hintText.value = ''
  hintOpen.value = false
}
</script>

<style lang="less" scoped>
.watchdog-banner {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-radius: var(--app-radius-md);
  border: 1px solid var(--td-warning-color-4);
  background: var(--td-warning-color-1);
  color: var(--td-text-color-primary);
}

.watchdog-banner__header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.watchdog-banner__icon {
  font-size: var(--app-text-3xl);
  color: var(--td-warning-color);
  flex-shrink: 0;
  margin-top: 2px;
}

.watchdog-banner__title {
  font-weight: 600;
}

.watchdog-banner__body {
  margin: 4px 0 0;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}

.watchdog-banner__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.watchdog-banner__hint {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;

  :deep(.t-input) {
    flex: 1 1 240px;
  }
}
</style>
