<script setup lang="ts">
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
/** 配置企业知识库的部门/成员读取受众；保留当前用户无权枚举的既有记录。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import { getKnowledgeBaseAudience, setKnowledgeBaseAudience, type EnterpriseKnowledgeBase, type KnowledgeBaseAudience, type KnowledgeBaseAudienceItem } from '@nexus-web/core/api/enterprise-knowledge'
import * as membersApi from '@nexus-web/core/api/enterprise-members'
import * as organizationsApi from '@nexus-web/core/api/enterprise-organizations'

const props = defineProps<{
  visible: boolean
  tenantId: string
  scopeKey: string
  knowledgeBase: EnterpriseKnowledgeBase
  canReadMembers: boolean
  canReadOrganization: boolean
}>()
const emit = defineEmits<{ 'update:visible': [value: boolean]; saved: [audience: KnowledgeBaseAudience] }>()
const { t } = useI18n()
const loading = ref(false), saving = ref(false), audienceReady = ref(false), audienceError = ref('')
const membersReady = ref(false), membersError = ref(''), unitsReady = ref(false), unitsError = ref('')
const members = ref<membersApi.EnterpriseMember[]>([]), units = ref<organizationsApi.OrganizationNode[]>([])
const original = ref<KnowledgeBaseAudienceItem[]>([]), selectedUsers = ref<string[]>([]), selectedUnits = ref<string[]>([])
const includeDescendants = ref<Record<string, boolean>>({})
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const canSave = computed(() => props.visible && audienceReady.value && !loading.value && !saving.value &&
  (membersReady.value || unitsReady.value) && (props.knowledgeBase.visibility !== 'scoped' || selectedUsers.value.length + selectedUnits.value.length > 0))
const memberOptions = computed(() => {
  const options: Array<{ value: string; label: string; disabled?: boolean }> = members.value.map(row => ({ value: row.user_id, label: [row.display_name || row.username || row.email || row.user_id, row.email].filter((value, index, all) => value && all.indexOf(value) === index).join(' · ') }))
  for (const entry of original.value) if (entry.kind === 'user' && !options.some(row => row.value === entry.id)) options.push({ value: entry.id, label: entry.id, disabled: !selectedUsers.value.includes(entry.id) })
  return options
})
const unitPaths = computed(() => {
  const byId = new Map<string, organizationsApi.OrganizationNode>(units.value.map(row => [row.id, row] as const)), result = new Map<string, string>()
  for (const unit of units.value) {
    const path: string[] = [], seen = new Set<string>()
    let current: organizationsApi.OrganizationNode | undefined = unit
    while (current && !seen.has(current.id)) { seen.add(current.id); path.push(current.name); current = current.parent_id ? byId.get(current.parent_id) : undefined }
    result.set(unit.id, path.reverse().join(' / '))
  }
  return result
})
const unitOptions = computed(() => {
  const values = new Set(units.value.filter(row => row.status === 'active').map(row => row.id))
  for (const entry of original.value) if (entry.kind === 'org_unit') values.add(entry.id)
  return [...values].map(value => ({ value, label: unitPaths.value.get(value) || value, disabled: !selectedUnits.value.includes(value) && !units.value.some(row => row.id === value && row.status === 'active') }))
})
const selectedUnitRows = computed(() => selectedUnits.value.map(id => ({ id, label: unitPaths.value.get(id) || id })))
function message(error: unknown): string {
  const detail = error instanceof Error ? error.message : error && typeof error === 'object' && 'message' in error && typeof error.message === 'string' ? error.message : ''
  return detail.includes('kb_in_use') ? t('adminKnowledge.audienceInUse') : t('adminKnowledge.audienceSaveFailed')
}
function reset() {
  epoch++; confirmation?.hide(); confirmation = undefined
  loading.value = false; saving.value = false; audienceReady.value = false; audienceError.value = ''
  membersReady.value = false; membersError.value = ''; unitsReady.value = false; unitsError.value = ''
  members.value = []; units.value = []; original.value = []; selectedUsers.value = []; selectedUnits.value = []; includeDescendants.value = {}
}
async function load() {
  reset()
  const current = epoch, tenant = props.tenantId, kb = props.knowledgeBase.id, scope = props.scopeKey
  if (!props.visible || !tenant || !kb) return
  loading.value = true
  const requests = await Promise.allSettled([
    getKnowledgeBaseAudience(tenant, kb),
    props.canReadMembers ? membersApi.listEnterpriseMembers(tenant) : Promise.resolve(null),
    props.canReadOrganization ? organizationsApi.listOrganizationUnits(tenant) : Promise.resolve(null),
  ])
  if (current !== epoch || tenant !== props.tenantId || kb !== props.knowledgeBase.id || scope !== props.scopeKey) return
  if (requests[0].status === 'fulfilled') {
    original.value = requests[0].value.items
    selectedUsers.value = original.value.filter(item => item.kind === 'user').map(item => item.id)
    selectedUnits.value = original.value.filter(item => item.kind === 'org_unit').map(item => item.id)
    includeDescendants.value = Object.fromEntries(original.value.filter(item => item.kind === 'org_unit').map(item => [item.id, item.include_descendants]))
    audienceReady.value = true
  } else audienceError.value = t('adminKnowledge.audienceLoadFailed')
  if (requests[1].status === 'fulfilled' && requests[1].value) { members.value = requests[1].value; membersReady.value = true }
  else if (requests[1].status === 'rejected') membersError.value = t('adminKnowledge.audienceMembersFailed')
  if (requests[2].status === 'fulfilled' && requests[2].value) { units.value = requests[2].value; unitsReady.value = true }
  else if (requests[2].status === 'rejected') unitsError.value = t('adminKnowledge.audienceDepartmentsFailed')
  loading.value = false
}
function close() { if (!saving.value) emit('update:visible', false) }
function save() {
  if (!canSave.value) return
  const items: KnowledgeBaseAudienceItem[] = [
    ...selectedUsers.value.map(id => ({ kind: 'user' as const, id, include_descendants: original.value.find(item => item.kind === 'user' && item.id === id)?.include_descendants ?? false })),
    ...selectedUnits.value.map(id => ({ kind: 'org_unit' as const, id, include_descendants: Boolean(includeDescendants.value[id]) })),
  ]
  const current = epoch, tenant = props.tenantId, kb = props.knowledgeBase.id, scope = props.scopeKey
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminKnowledge.audienceConfirmTitle'), body: t('adminKnowledge.audienceConfirm', { kb: props.knowledgeBase.name }),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (current !== epoch || tenant !== props.tenantId || kb !== props.knowledgeBase.id || scope !== props.scopeKey || !props.visible || saving.value) return
      saving.value = true; audienceError.value = ''
      try {
        const result = await setKnowledgeBaseAudience(tenant, kb, items)
        if (current !== epoch || tenant !== props.tenantId || kb !== props.knowledgeBase.id || scope !== props.scopeKey || !props.visible) return
        emit('saved', result); emit('update:visible', false)
      } catch (error) { if (current === epoch) audienceError.value = message(error) }
      finally { if (current === epoch) saving.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
watch(() => [props.visible, props.tenantId, props.scopeKey, props.knowledgeBase.id, props.canReadMembers, props.canReadOrganization] as const, ([visible]) => { if (visible) void load(); else reset() }, { immediate: true, flush: 'sync' })
watch(selectedUnits, ids => { for (const id of ids) if (includeDescendants.value[id] === undefined) includeDescendants.value[id] = true }, { deep: true })
onBeforeUnmount(reset)
</script>

<template>
  <EditorDialog :visible="visible" :header="t('adminKnowledge.audienceTitle')" width="min(760px, calc(100vw - 24px))" :confirm-btn="{ content: t('adminKnowledge.audienceSave'), disabled: !canSave, loading: saving }" :cancel-btn="{ content: t('common.cancel'), disabled: saving }" :close-on-overlay-click="!saving" :close-on-esc-keydown="!saving" :close-btn="!saving" @confirm="save" @close="close">
    <p class="hint">{{ t('adminKnowledge.audienceDescription', { kb: knowledgeBase.name }) }}</p>
    <t-alert v-if="knowledgeBase.visibility !== 'scoped'" theme="warning" :message="t('adminKnowledge.audienceInactive')" />
    <t-alert v-if="knowledgeBase.visibility === 'scoped' && selectedUsers.length + selectedUnits.length === 0" theme="warning" :message="t('adminKnowledge.audienceRequired')" />
    <t-alert v-if="audienceError" theme="error" :message="audienceError"><template #operation><t-button variant="text" @click="load">{{ t('connectionUi.refresh') }}</t-button></template></t-alert>
    <t-loading :loading="loading">
      <section class="scope-group">
        <h3>{{ t('adminKnowledge.audienceDepartments') }}</h3><p>{{ unitsError || (!canReadOrganization ? t('adminKnowledge.audienceDepartmentsDenied') : t('adminKnowledge.audienceDepartmentHint')) }}</p>
        <t-select v-model="selectedUnits" multiple clearable filterable :disabled="!unitsReady || loading || saving" :options="unitOptions" :placeholder="t('adminKnowledge.audienceChooseDepartments')" />
        <p v-if="unitsReady && !unitOptions.length">{{ t('adminKnowledge.audienceNoDepartments') }}</p>
        <div v-for="row in selectedUnitRows" :key="row.id" class="unit-option"><span>{{ row.label }}</span><t-checkbox v-model="includeDescendants[row.id]" :disabled="!unitsReady || saving">{{ t('adminKnowledge.includeDescendants') }}</t-checkbox></div>
      </section>
      <section class="scope-group">
        <h3>{{ t('adminKnowledge.audienceMembers') }}</h3><p>{{ membersError || (!canReadMembers ? t('adminKnowledge.audienceMembersDenied') : t('adminKnowledge.audienceMemberHint')) }}</p>
        <t-select v-model="selectedUsers" multiple clearable filterable :disabled="!membersReady || loading || saving" :options="memberOptions" :placeholder="t('adminKnowledge.audienceChooseMembers')" />
        <p v-if="membersReady && !memberOptions.length">{{ t('adminKnowledge.audienceNoMembers') }}</p>
      </section>
    </t-loading>
  </EditorDialog>
</template>

<style scoped>
.hint, .scope-group p { color: var(--td-text-color-secondary); line-height: 1.6; }
.scope-group { margin-top: 24px; }
.scope-group h3 { margin: 0 0 8px; font-size: var(--app-text-lg); }
.unit-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
</style>
