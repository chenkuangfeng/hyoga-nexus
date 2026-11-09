<template>
  <!--
    Editable header/env rows for the MCP service dialog (openspec 2026-11-08-mcp, task 4.1).
    "引用凭据" turns a value into a stored credential reference; the id is sent as
    `{"$credential_ref": "<id>"}` and the secret itself never travels through this form.
  -->
  <div class="kv">
    <div v-for="(row, index) in modelValue" :key="index" class="kv-row">
      <t-input v-model="row.key" class="kv-key" :placeholder="$t('toolbox.mcp.keyPlaceholder')"
        :aria-label="$t('toolbox.mcp.keyPlaceholder')" />
      <t-input v-model="row.value" class="kv-value"
        :placeholder="row.reference ? $t('toolbox.mcp.referencePlaceholder') : $t('toolbox.mcp.valuePlaceholder')"
        :aria-label="row.reference ? $t('toolbox.mcp.referencePlaceholder') : $t('toolbox.mcp.valuePlaceholder')" />
      <t-checkbox :checked="row.reference" @change="(checked: boolean) => setReference(row, checked)">
        {{ $t('toolbox.mcp.reference') }}
      </t-checkbox>
      <t-button variant="text" theme="danger" size="small" class="kv-remove"
        :aria-label="$t('toolbox.mcp.removeRow')" :title="$t('toolbox.mcp.removeRow')" @click="remove(index)">
        <t-icon name="delete" size="14px" />
      </t-button>
    </div>
    <t-button variant="text" theme="primary" size="small" class="kv-add" @click="add">
      <template #icon><t-icon name="add" size="14px" /></template>
      {{ $t('toolbox.mcp.addRow') }}
    </t-button>
  </div>
</template>

<script setup lang="ts">
import type { McpKeyValueRow } from './toolboxMcp'

const props = defineProps<{ modelValue: McpKeyValueRow[] }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: McpKeyValueRow[]): void }>()

function update(next: McpKeyValueRow[]) {
  emit('update:modelValue', next)
}

/** Clearing the value when switching modes keeps a secret from being mistaken for a reference id. */
function setReference(row: McpKeyValueRow, reference: boolean) {
  update(props.modelValue.map((item) => item === row ? { ...item, reference, value: '' } : item))
}

function add() {
  update([...props.modelValue, { key: '', value: '', reference: false }])
}

function remove(index: number) {
  update(props.modelValue.filter((_, itemIndex) => itemIndex !== index))
}
</script>

<style scoped>
.kv-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.kv-key { width: 160px; }
.kv-value { flex: 1; min-width: 160px; }
.kv-remove { flex-shrink: 0; }
.kv-add { padding-left: 0; }
</style>
