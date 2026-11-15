/** 企业组织管理控制器：权限、树与节点选择分别校验，旧请求及确认不能影响新作用域。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listEnterpriseMembers, type EnterpriseMember } from '@nexus-web/core/api/enterprise-members'
import { assignOrganizationMember, createOrganizationUnit, deleteOrganizationUnit, listOrganizationMembers, listOrganizationUnits, removeOrganizationMember, updateOrganizationUnit, type OrganizationEdit, type OrganizationMember, type OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'
import { useAdminContext } from '../../stores/context'
import { organizationRows, organizationSubtree } from './organizationTree'

type Translate = (key: string, values?: Record<string, unknown>) => string
/** 只请求服务端授权的企业/部门数据；成员候选读取失败时不把空列表作为已知成员集合。 */
export function useOrganizationAdministration(t: Translate) {
  const auth = useAuthStore(), context = useAdminContext()
  const units = ref<OrganizationNode[]>([]), selectedId = ref(''), members = ref<OrganizationMember[]>([]), candidates = ref<EnterpriseMember[]>([])
  const loading = ref(false), membersLoading = ref(false), busy = ref(false)
  const treeReady = ref(false), membersReady = ref(false), candidatesReady = ref(false)
  const error = ref(''), membersError = ref(''), candidatesError = ref(''), success = ref('')
  const editorOpen = ref(false), editorMode = ref<'root' | 'create' | 'edit'>('create'), editingId = ref('')
  const form = reactive({ name: '', parent_id: '' }), assignment = reactive({ user_id: '', is_primary: false })
  let epoch = 0, memberRequest = 0
  let confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
  const canManage = computed(() => context.can('org:manage'))
  const canReadCandidates = computed(() => context.can('members:manage'))
  const rows = computed(() => organizationRows(units.value))
  const selected = computed(() => units.value.find(row => row.id === selectedId.value) || null)
  const manual = computed(() => !!selected.value && !selected.value.sync_managed)
  const canAssign = computed(() => canManage.value && selected.value?.status === 'active' && membersReady.value && candidatesReady.value)
  const canDelete = computed(() => { const row = selected.value; return !!row && canManage.value && manual.value && row.parent_id !== null && row.member_count === 0 && membersReady.value && members.value.length === 0 && !units.value.some(item => item.parent_id === row.id) })
  const parentOptions = computed(() => {
    const edited = units.value.find(row => row.id === editingId.value)
    const blocked = edited ? organizationSubtree(units.value, edited.id) : new Set<string>()
    return rows.value.filter(row => !blocked.has(row.node.id) && (row.node.status === 'active' || row.node.id === edited?.parent_id)).map(row => ({ label: row.path, value: row.node.id, disabled: row.node.status !== 'active' }))
  })
  const candidateOptions = computed(() => { const present = new Set(members.value.map(row => row.user_id)); return candidates.value.filter(row => row.status === 'active' && !present.has(row.user_id)).map(row => ({ value: row.user_id, label: row.display_name ? `${row.display_name}${row.email ? ` · ${row.email}` : ''}` : row.username || row.email || t('adminMembers.unnamedMember') })) })
  function memberName(row: OrganizationMember): string { const info = candidates.value.find(item => item.user_id === row.user_id); return row.display_name || info?.display_name || info?.username || info?.email || t('adminMembers.unnamedMember') }
  function path(id: string): string { return rows.value.find(row => row.node.id === id)?.path || t('adminOrganization.noParent') }
  function message(reason: unknown): string { return reason instanceof Error && !['organization_response_invalid', 'members_response_invalid'].includes(reason.message) ? reason.message : t('adminConsole.failed') }
  function closeConfirmation() { confirmation?.hide(); confirmation = undefined }
  function clearEditor() { editorOpen.value = false; editingId.value = ''; Object.assign(form, { name: '', parent_id: '' }) }
  function closeEditor() { if (!busy.value) { closeConfirmation(); clearEditor() } }
  function invalidate() { epoch++; memberRequest++; closeConfirmation(); clearEditor(); units.value = []; selectedId.value = ''; members.value = []; candidates.value = []; treeReady.value = false; membersReady.value = false; candidatesReady.value = false; loading.value = false; membersLoading.value = false; busy.value = false; error.value = ''; membersError.value = ''; candidatesError.value = ''; success.value = ''; Object.assign(assignment, { user_id: '', is_primary: false }) }
  async function readMembers(unit: string) {
    const current = epoch, request = ++memberRequest, tenant = String(auth.effectiveTenantId)
    members.value = []; membersReady.value = false; membersError.value = ''; membersLoading.value = true
    try { const result = await listOrganizationMembers(tenant, unit); if (current === epoch && request === memberRequest && selectedId.value === unit) { members.value = result; membersReady.value = true } }
    catch (reason) { if (current === epoch && request === memberRequest && selectedId.value === unit) membersError.value = message(reason) }
    finally { if (current === epoch && request === memberRequest) membersLoading.value = false }
  }
  function selectUnit(id: string) {
    if (!canManage.value || !treeReady.value || loading.value || busy.value || !units.value.some(row => row.id === id)) return
    closeConfirmation(); clearEditor(); error.value = ''; success.value = ''; selectedId.value = id; Object.assign(assignment, { user_id: '', is_primary: false }); void readMembers(id)
  }
  async function load(preferred?: string | null) {
    invalidate()
    if (!canManage.value || !auth.effectiveTenantId) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    loading.value = true
    const result = await Promise.allSettled([listOrganizationUnits(tenant), canReadCandidates.value ? listEnterpriseMembers(tenant) : Promise.resolve(null)])
    if (current !== epoch) return
    if (result[0].status === 'fulfilled') { units.value = result[0].value; treeReady.value = true } else error.value = message(result[0].reason)
    if (result[1].status === 'fulfilled' && result[1].value !== null) { candidates.value = result[1].value; candidatesReady.value = true } else if (result[1].status === 'rejected') candidatesError.value = message(result[1].reason)
    loading.value = false
    if (treeReady.value && units.value.length) selectUnit(preferred && units.value.some(row => row.id === preferred) ? preferred : units.value.find(row => row.parent_id === null)!.id)
  }
  async function run(operation: (tenant: string) => Promise<string | null>) {
    if (!canManage.value || !treeReady.value || loading.value || busy.value) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    busy.value = true; error.value = ''; success.value = ''
    try { const preferred = await operation(tenant); if (current !== epoch) return; await load(preferred); if (epoch === current + 1) success.value = t('adminOrganization.saved') }
    catch (reason) { if (current === epoch) error.value = message(reason) }
    finally { if (current === epoch) busy.value = false }
  }
  function confirm(body: string, operation: (tenant: string) => Promise<string | null>) {
    if (!canManage.value || !treeReady.value || busy.value || loading.value || confirmation) return
    const current = epoch, selection = selectedId.value, request = memberRequest
    const dialog = DialogPlugin.confirm({ header: t('adminOrganization.confirm'), body,
      onConfirm: async () => { if (confirmation !== dialog) return; dialog.hide(); confirmation = undefined; if (current !== epoch || selection !== selectedId.value || request !== memberRequest) return; await run(operation) },
      onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
    })
    confirmation = dialog
  }
  function openCreate(parent: string | null) {
    if (!canManage.value || !treeReady.value || loading.value || busy.value || (parent === null ? units.value.length > 0 : !units.value.some(row => row.id === parent && row.status === 'active'))) return
    clearEditor(); editorMode.value = parent === null ? 'root' : 'create'; form.parent_id = parent || ''; editorOpen.value = true; error.value = ''
  }
  function openEdit() {
    if (!canManage.value || !treeReady.value || busy.value || !selected.value || !manual.value) return
    clearEditor(); editorMode.value = 'edit'; editingId.value = selected.value.id; form.name = selected.value.name; form.parent_id = selected.value.parent_id || ''; editorOpen.value = true; error.value = ''
  }
  async function save({ validateResult }: { validateResult: unknown }) {
    if (validateResult !== true || !editorOpen.value || !form.name.trim() || [...form.name.trim()].length > 160 || !canManage.value || !treeReady.value || loading.value || busy.value) return
    const name = form.name.trim(), parent = form.parent_id, edited = units.value.find(row => row.id === editingId.value)
    if (editorMode.value === 'root') { if (units.value.length) return; await run(async tenant => (await createOrganizationUnit(tenant, { name })).id); return }
    if (editorMode.value === 'edit') {
      if (!edited || edited.sync_managed) return
      const input: OrganizationEdit = {}
      if (name !== edited.name) input.name = name
      if (edited.parent_id !== null && parent !== edited.parent_id) {
        if (!units.value.some(row => row.id === parent && row.status === 'active') || organizationSubtree(units.value, edited.id).has(parent)) return
        input.parent_id = parent
      }
      if (!Object.keys(input).length) { clearEditor(); return }
      const operation = async (tenant: string) => { await updateOrganizationUnit(tenant, edited.id, input); return edited.id }
      if (input.parent_id) confirm(t('adminOrganization.moveConfirm', { name: edited.name, parent: path(parent) }), operation)
      else await run(operation)
      return
    }
    if (!units.value.some(row => row.id === parent && row.status === 'active')) return
    await run(async tenant => (await createOrganizationUnit(tenant, { name, parent_id: parent })).id)
  }
  function toggleStatus() {
    const row = selected.value
    if (!row || !manual.value) return
    const next = row.status === 'active' ? 'disabled' : 'active'
    confirm(t('adminOrganization.statusConfirm', { name: row.name, status: t(`adminOrganization.status.${next}`) }), async tenant => { await updateOrganizationUnit(tenant, row.id, { status: next }); return row.id })
  }
  function removeUnit() {
    const row = selected.value
    if (!row || !canDelete.value) return
    confirm(t('adminOrganization.deleteConfirm', { name: row.name }), async tenant => { await deleteOrganizationUnit(tenant, row.id); return row.parent_id })
  }
  async function assign() {
    const unit = selected.value, user = assignment.user_id, primary = assignment.is_primary
    if (!unit || !canAssign.value || !candidateOptions.value.some(row => row.value === user)) return
    await run(async tenant => { await assignOrganizationMember(tenant, unit.id, user, primary); return unit.id })
  }
  function setPrimary(row: OrganizationMember) {
    const unit = selected.value
    if (!unit || !canManage.value || unit.status !== 'active' || !membersReady.value || row.is_primary || !members.value.some(item => item.user_id === row.user_id)) return
    confirm(t('adminOrganization.primaryConfirm', { name: memberName(row), department: path(unit.id) }), async tenant => { await assignOrganizationMember(tenant, unit.id, row.user_id, true); return unit.id })
  }
  function removeMember(row: OrganizationMember) {
    const unit = selected.value
    if (!unit || !canManage.value || row.source === 'wecom' || !membersReady.value || !members.value.some(item => item.user_id === row.user_id)) return
    confirm(t(row.source === 'mixed' ? 'adminOrganization.removeManualConfirm' : 'adminOrganization.removeConfirm', { name: memberName(row), department: path(unit.id) }), async tenant => { await removeOrganizationMember(tenant, unit.id, row.user_id); return unit.id })
  }
  watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canManage, canReadCandidates], () => { void load() }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(invalidate)
  return { units, selectedId, selected, manual, rows, members, candidates, loading, membersLoading, busy, treeReady, membersReady, candidatesReady, error, membersError, candidatesError, success, canManage, canReadCandidates, canAssign, canDelete, parentOptions, candidateOptions, editorOpen, editorMode, editingId, form, assignment, memberName, path, load, selectUnit, openCreate, openEdit, closeEditor, save, toggleStatus, removeUnit, assign, setPrimary, removeMember }
}
