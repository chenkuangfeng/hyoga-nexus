<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SandboxConfiguration } from '@nexus-web/core/api/nexus-sandboxes'
import type { ConfigField } from './sandboxConfigFields'
const props = defineProps<{ field: ConfigField; values: SandboxConfiguration; disabled: boolean }>()
const emit = defineEmits<{ change: [key: string, value: string | number | boolean | string[]] }>()
const { t } = useI18n()
const label = computed(() => t(`sandboxConfig.fields.${props.field.key}`))
const text = computed(() => String(props.values[props.field.key] ?? ''))
const number = computed(() => Number(props.values[props.field.key] ?? props.field.min ?? 0))
const checked = computed(() => props.values[props.field.key] === true)
const tags = computed(() => {
  const value = props.values[props.field.key]
  return Array.isArray(value) ? value : []
})
function toggle() { if (!props.disabled) emit('change', props.field.key, !checked.value) }
</script>
<template>
  <t-form-item :label="label" :required-mark="field.required">
    <label v-if="field.input === 'text'" class="sandbox-control">
      <span class="sandbox-control__label">{{ label }}</span>
      <t-input :value="text" :name="field.key" :disabled="disabled" @change="emit('change', field.key, $event)" />
    </label>
    <t-input-number v-else-if="field.input === 'number'" :value="number" :min="field.min" :max="field.max"
      :step="field.step || 1" :aria-label="label" :disabled="disabled" @change="emit('change', field.key, Number($event))" />
    <t-switch v-else-if="field.input === 'switch'" :value="checked" role="switch" :aria-label="label"
      :aria-checked="checked" :disabled="disabled" :tabindex="disabled ? -1 : 0"
      @change="emit('change', field.key, Boolean($event))" @keydown.space.prevent="toggle" @keydown.enter.prevent="toggle" />
    <t-select v-else-if="field.input === 'network'" :value="text" :aria-label="label" :disabled="disabled"
      :options="[{ value: 'none', label: t('sandboxConfig.networkNone') }, { value: 'bridge', label: t('sandboxConfig.networkBridge') }]"
      @change="emit('change', field.key, String($event))" />
    <t-tag-input v-else :value="tags" :aria-label="label" :disabled="disabled"
      @change="emit('change', field.key, $event.map(String))" />
  </t-form-item>
</template>
<style scoped>
.sandbox-control { display: block; width: 100%; }
.sandbox-control__label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>
