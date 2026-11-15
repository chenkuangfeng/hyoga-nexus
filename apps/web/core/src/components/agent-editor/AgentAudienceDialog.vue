<script setup lang="ts">
/** 智能体部门/成员受众编辑；无目录权限时保留原记录，不按空列表覆盖。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import { getAgentAudience, setAgentAudience, type AgentAudience, type AgentAudienceItem } from '@nexus-web/core/api/enterprise-agent-audience'
import { listEnterpriseMembers, type EnterpriseMember } from '@nexus-web/core/api/enterprise-members'
import { listOrganizationUnits, type OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'

const props = defineProps<{ visible: boolean; tenantId: string; agentId: string; agentName: string; scopeKey: string; canManage: boolean; canReadMembers: boolean; canReadOrganization: boolean }>()
const emit = defineEmits<{ 'update:visible': [value: boolean]; saved: [audience: AgentAudience] }>()
const { t } = useI18n()
const loading = ref(false), saving = ref(false), audienceReady = ref(false), error = ref('')
const membersReady = ref(false), membersError = ref(''), unitsReady = ref(false), unitsError = ref('')
const members = ref<EnterpriseMember[]>([]), units = ref<OrganizationNode[]>([]), original = ref<AgentAudienceItem[]>([])
const selectedUsers = ref<string[]>([]), selectedUnits = ref<string[]>([]), includeDescendants = ref<Record<string, boolean>>({})
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const canSave = computed(() => props.visible && props.canManage && audienceReady.value && !loading.value && !saving.value && (membersReady.value || unitsReady.value))
const memberOptions = computed(() => {
  const options: Array<{ value: string; label: string; disabled?: boolean }> = members.value.map(row => ({ value: row.user_id, label: [row.display_name || row.username || row.email || row.user_id, row.email].filter((value, index, all) => value && all.indexOf(value) === index).join(' · ') }))
  for (const row of original.value) if (row.kind === 'user' && !options.some(option => option.value === row.id)) options.push({ value: row.id, label: row.id, disabled: !selectedUsers.value.includes(row.id) })
  return options
})
const unitPaths = computed(() => {
  const byId = new Map(units.value.map(row => [row.id, row])), result = new Map<string, string>()
  for (const unit of units.value) { const names: string[] = [], seen = new Set<string>(); let current: OrganizationNode | undefined = unit
    while (current && !seen.has(current.id)) { seen.add(current.id); names.push(current.name); current = current.parent_id ? byId.get(current.parent_id) : undefined }
    result.set(unit.id, names.reverse().join(' / '))
  }
  return result
})
const unitOptions = computed(() => {
  const ids = new Set(units.value.filter(row => row.status === 'active').map(row => row.id))
  for (const row of original.value) if (row.kind === 'org_unit') ids.add(row.id)
  return [...ids].map(id => ({ value: id, label: unitPaths.value.get(id) || id, disabled: !selectedUnits.value.includes(id) && !units.value.some(row => row.id === id && row.status === 'active') }))
})
const selectedUnitRows = computed(() => selectedUnits.value.map(id => ({ id, label: unitPaths.value.get(id) || id })))
function reset() {
  epoch++; confirmation?.hide(); confirmation = undefined; loading.value = false; saving.value = false; audienceReady.value = false; error.value = ''
  membersReady.value = false; membersError.value = ''; unitsReady.value = false; unitsError.value = ''; members.value = []; units.value = []; original.value = []; selectedUsers.value = []; selectedUnits.value = []; includeDescendants.value = {}
}
async function load() {
  reset(); const request = epoch, tenant = props.tenantId, agent = props.agentId, scope = props.scopeKey
  if (!props.visible || !tenant || !agent || !props.canManage) return
  loading.value = true
  const result = await Promise.allSettled([
    getAgentAudience(tenant, agent),
    props.canReadMembers ? listEnterpriseMembers(tenant) : Promise.resolve(null),
    props.canReadOrganization ? listOrganizationUnits(tenant) : Promise.resolve(null),
  ])
  if (request !== epoch || tenant !== props.tenantId || agent !== props.agentId || scope !== props.scopeKey || !props.visible) return
  if (result[0].status === 'fulfilled') {
    original.value = result[0].value.items; selectedUsers.value = original.value.filter(item => item.kind === 'user').map(item => item.id); selectedUnits.value = original.value.filter(item => item.kind === 'org_unit').map(item => item.id)
    includeDescendants.value = Object.fromEntries(original.value.filter(item => item.kind === 'org_unit').map(item => [item.id, item.include_descendants])); audienceReady.value = true
  } else error.value = t('agentAudience.loadFailed')
  if (result[1].status === 'fulfilled' && result[1].value) { members.value = result[1].value; membersReady.value = true } else if (result[1].status === 'rejected') membersError.value = t('agentAudience.membersFailed')
  if (result[2].status === 'fulfilled' && result[2].value) { units.value = result[2].value; unitsReady.value = true } else if (result[2].status === 'rejected') unitsError.value = t('agentAudience.departmentsFailed')
  if (!props.canReadMembers) membersError.value = t('agentAudience.membersDenied')
  if (!props.canReadOrganization) unitsError.value = t('agentAudience.departmentsDenied')
  loading.value = false
}
function close() { if (!saving.value) emit('update:visible', false) }
function save() {
  if (!canSave.value || confirmation) return
  const items: AgentAudienceItem[] = [
    ...selectedUsers.value.map(id => ({ kind: 'user' as const, id, include_descendants: original.value.find(row => row.kind === 'user' && row.id === id)?.include_descendants ?? false })),
    ...selectedUnits.value.map(id => ({ kind: 'org_unit' as const, id, include_descendants: Boolean(includeDescendants.value[id]) })),
  ]
  const request = epoch, tenant = props.tenantId, agent = props.agentId, scope = props.scopeKey
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('agentAudience.confirmTitle'), body: t('agentAudience.confirm', { agent: props.agentName }),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (request !== epoch || tenant !== props.tenantId || agent !== props.agentId || scope !== props.scopeKey || !props.visible || !props.canManage || saving.value) return
      saving.value = true; error.value = ''
      try { const result = await setAgentAudience(tenant, agent, items); if (request !== epoch || tenant !== props.tenantId || agent !== props.agentId || scope !== props.scopeKey || !props.visible) return; emit('saved', result); emit('update:visible', false) }
      catch { if (request === epoch) error.value = t('agentAudience.saveFailed') }
      finally { if (request === epoch) saving.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
watch(() => [props.visible, props.tenantId, props.agentId, props.scopeKey, props.canManage, props.canReadMembers, props.canReadOrganization] as const, ([visible]) => { if (visible) void load(); else reset() }, { immediate: true, flush: 'sync' })
watch(selectedUnits, ids => { for (const id of ids) if (includeDescendants.value[id] === undefined) includeDescendants.value[id] = true }, { deep: true })
onBeforeUnmount(reset)
</script>

<template>
  <t-dialog :visible="visible" :header="t('agentAudience.title')" width="min(760px, calc(100vw - 24px))" :confirm-btn="{ content: t('agentAudience.save'), disabled: !canSave, loading: saving }" :cancel-btn="{ content: t('common.cancel'), disabled: saving }" :close-on-overlay-click="!saving" :close-on-esc-keydown="!saving" :close-btn="!saving" @confirm="save" @close="close">
    <p class="hint">{{ t('agentAudience.description', { agent: agentName }) }}</p>
    <t-alert theme="info" :message="t('agentAudience.scopeHint')" />
    <t-alert v-if="error" theme="error" :message="error"><template #operation><t-button variant="text" @click="load">{{ t('connectionUi.refresh') }}</t-button></template></t-alert>
    <t-loading :loading="loading">
      <section class="scope-group"><h3>{{ t('agentAudience.departments') }}</h3><p>{{ unitsError || t('agentAudience.departmentHint') }}</p>
        <t-select v-model="selectedUnits" multiple clearable filterable :disabled="!props.canManage || !unitsReady || loading || saving" :options="unitOptions" :placeholder="t('agentAudience.chooseDepartments')" />
        <p v-if="unitsReady && !unitOptions.length">{{ t('agentAudience.noDepartments') }}</p><div v-for="row in selectedUnitRows" :key="row.id" class="unit-row"><span>{{ row.label }}</span><t-checkbox v-model="includeDescendants[row.id]" :disabled="!unitsReady || saving">{{ t('agentAudience.includeDescendants') }}</t-checkbox></div>
      </section>
      <section class="scope-group"><h3>{{ t('agentAudience.members') }}</h3><p>{{ membersError || t('agentAudience.memberHint') }}</p>
        <t-select v-model="selectedUsers" multiple clearable filterable :disabled="!props.canManage || !membersReady || loading || saving" :options="memberOptions" :placeholder="t('agentAudience.chooseMembers')" />
        <p v-if="membersReady && !memberOptions.length">{{ t('agentAudience.noMembers') }}</p>
      </section>
    </t-loading>
  </t-dialog>
</template>

<style scoped>
.hint, .scope-group p { color: var(--td-text-color-secondary); line-height: 1.6; }
.scope-group { margin-top: 24px; }
.scope-group h3 { margin: 0 0 8px; font-size: var(--app-text-lg); }
.unit-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
</style>
