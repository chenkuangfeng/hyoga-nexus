<script setup lang="ts">
/** 卡片右上角的更多操作，选项及其权限由企业目录传入。 */
import { computed, h, ref, resolveComponent } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  actions: Array<{ value: string; label: string; icon: string; danger?: boolean }>
  disabled?: boolean
}>()
const emit = defineEmits<{ select: [value: string] }>()
const { t } = useI18n()
const icon = resolveComponent('t-icon')
const expanded = ref(false)
const options = computed(() => props.actions.map(action => ({
  value: action.value,
  content: action.label,
  prefixIcon: () => h(icon, { name: action.icon, size: '16px', 'aria-hidden': 'true' }),
  theme: action.danger ? 'error' as const : 'default' as const,
})))
function select({ value }: { value?: unknown }) {
  if (!props.disabled && typeof value === 'string') emit('select', value)
}
</script>

<template>
  <t-dropdown :options="options" :disabled="disabled" trigger="click" placement="bottom-right"
    :popup-props="{ destroyOnClose: true, onVisibleChange: (visible: boolean) => expanded = visible }" @click="select">
    <button type="button" class="card-more-button" :aria-label="t('common.expand')" aria-haspopup="true" :aria-expanded="expanded" :disabled="disabled">
      <t-icon name="ellipsis" size="16px" aria-hidden="true" />
    </button>
  </t-dropdown>
</template>

<style scoped>
.card-more-button {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-sm);
  color: var(--td-text-color-secondary);
  background: transparent;
  cursor: pointer;
}
.card-more-button:hover, .card-more-button[aria-expanded='true'] { background: var(--td-bg-color-secondarycontainer); }
.card-more-button:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 1px; }
.card-more-button:disabled { cursor: default; color: var(--td-text-color-disabled); }
</style>
