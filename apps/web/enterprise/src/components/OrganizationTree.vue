<script setup lang="ts">
/** 管理端组织树展示：仅发送节点选择，不读取或修改业务数据。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'
import { organizationRows } from '../views/organization/organizationTree'
const props = defineProps<{ nodes: OrganizationNode[]; selectedId: string; disabled?: boolean; showAll?: boolean }>()
const emit = defineEmits<{ (event: 'select', id: string): void }>()
const { t } = useI18n(), rows = computed(() => organizationRows(props.nodes))
</script>
<template>
  <nav class="organization-tree" :aria-label="t('enterpriseLayout.organizationTree')">
    <h3>{{ t('enterpriseLayout.organizationTree') }}</h3>
    <button v-if="showAll" type="button" :class="{ selected: !selectedId }" :aria-current="!selectedId ? 'true' : undefined" :disabled="disabled" @click="emit('select', '')"><t-icon name="usergroup" /><span>{{ t('enterpriseLayout.allUsers') }}</span></button>
    <button v-for="row in rows" :key="row.node.id" type="button" :class="{ selected: selectedId === row.node.id }" :aria-current="selectedId === row.node.id ? 'true' : undefined" :style="{ paddingLeft: `${12 + Math.min(row.depth, 12) * 14}px` }" :title="row.path" :disabled="disabled" @click="emit('select', row.node.id)"><t-icon :name="row.node.parent_id === null ? 'view-organization' : 'folder'" /><span>{{ row.node.name }}</span><small>{{ row.node.member_count }}</small><t-tag v-if="row.node.status === 'disabled'" theme="warning" size="small">{{ t('adminOrganization.status.disabled') }}</t-tag></button>
  </nav>
</template>
<style scoped>
.organization-tree { min-width: 0; height: 100%; box-sizing: border-box; overflow: auto; padding: 16px 12px; border-right: 1px solid var(--td-component-stroke); background: var(--td-bg-color-container); }
h3 { font-size: var(--app-text-base); margin: 0 8px 16px; color: var(--td-text-color-secondary); font-weight: 500; }
button { width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px 12px; border: 0; border-radius: var(--app-radius-md); background: transparent; color: var(--td-text-color-primary); font: inherit; text-align: left; cursor: pointer; }
button span { flex: 1; min-width: 0; overflow-wrap: anywhere; } small { color: var(--td-text-color-secondary); }
button:hover { background: var(--td-bg-color-container-hover); } button.selected { color: var(--td-brand-color); background: var(--td-brand-color-light); }
button:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; } button:disabled { cursor: default; opacity: .65; }
@media(max-width: 720px) { .organization-tree { max-height: 220px; border-right: 0; border-bottom: 1px solid var(--td-component-stroke); } }
</style>
