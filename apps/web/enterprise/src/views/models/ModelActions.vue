<script setup lang="ts">
/** 模型和服务商共用操作弹层，按钮可顺序聚焦并通过 Esc 返回触发按钮。 */
import { ref, useId } from 'vue'

defineProps<{
  label: string
  disabled: boolean
  iconOnly?: boolean
  actions: { key: string; label: string; run: () => void; danger?: boolean }[]
}>()

const menuId = useId()
const root = ref<HTMLElement>()
const visible = ref(false)
const attach = () => root.value ?? document.body

function close() {
  if (!visible.value) return
  visible.value = false
  root.value?.querySelector('button')?.focus()
}

function onEscape(event: KeyboardEvent) {
  if (!visible.value) return
  event.stopPropagation()
  close()
}
</script>

<template>
  <div ref="root" @keydown.esc="onEscape">
    <t-popup v-model:visible="visible" :attach="attach" trigger="click"
      placement="bottom-right" :disabled="disabled" destroy-on-close>
      <t-button :variant="iconOnly ? 'text' : 'outline'" :shape="iconOnly ? 'square' : 'rectangle'" size="small"
        :disabled="disabled" :aria-label="label" :aria-expanded="visible" :aria-controls="visible ? menuId : undefined">
        <template #icon><t-icon v-if="iconOnly" name="ellipsis" aria-hidden="true" /></template>
        <span v-if="!iconOnly">{{ label }}</span>
        <t-icon v-if="!iconOnly" name="chevron-down" aria-hidden="true" />
      </t-button>
      <template #content>
        <div :id="menuId" class="model-actions-panel">
          <t-button v-for="action in actions" :key="action.key" :theme="action.danger ? 'danger' : 'default'"
            variant="text" @click="close(); action.run()">{{ action.label }}</t-button>
        </div>
      </template>
    </t-popup>
  </div>
</template>

<style scoped>
.model-actions-panel {
  display: grid;
  max-width: min(280px, calc(100vw - 64px));
  max-height: 280px;
  overflow: auto;
}

.model-actions-panel :deep(.t-button) {
  justify-content: flex-start;
  height: auto;
  min-height: 32px;
  padding-block: 4px;
  white-space: normal;
  text-align: start;
  overflow-wrap: anywhere;
}
</style>
