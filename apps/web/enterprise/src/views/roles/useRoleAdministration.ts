/** 角色目录、授权表单和成员分配编排。服务端权限为最终授权依据，代次防止旧响应写入新企业。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useEnterpriseContext } from '../../stores/context'
import { assignDepartmentRole, listEnterpriseRoles, getRoleCatalog, getRoleActorPermissions, createEnterpriseRole, updateEnterpriseRole, listRoleAssignments, setMemberRoleAssignment, type EnterpriseRole, type PermissionSet, type RoleAssignment } from '@nexus-web/core/api/enterprise-roles'
import { listOrganizationUnits, type OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'
import { organizationRows } from '../organization/organizationTree'
import { listEnterpriseMembers, type EnterpriseMember } from '@nexus-web/core/api/enterprise-members'

export function useRoleAdministration() {
  const auth = useAuthStore(), context = useEnterpriseContext(), router = useRouter(), { t, te } = useI18n()
  const roles = ref<EnterpriseRole[]>([]), catalog = ref<PermissionSet | null>(null), actor = ref<PermissionSet | null>(null)
  const members = ref<EnterpriseMember[]>([]), assignments = ref<RoleAssignment[]>([])
  const ready = ref(false), membersReady = ref(false), loading = ref(false), busy = ref(false)
  const error = ref(''), membersError = ref(''), success = ref(''), search = ref('')
  const editor = ref(false), selected = ref<EnterpriseRole | null>(null)
  const form = reactive({ name: '', menus: [] as string[], apis: [] as string[] })
  const selectedMember = ref(''), selectedRole = ref('')
  const departments = ref<OrganizationNode[]>([]), departmentsReady = ref(false), departmentError = ref('')
  const selectedDepartment = ref(''), departmentRole = ref('')
  let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
  const canManage = computed(() => context.can('roles:manage'))
  const canManageMembers = computed(() => canManage.value && context.can('members:manage'))
  const canManageDepartments = computed(() => canManageMembers.value && context.can('org:manage'))
  const departmentChoices = computed(() => organizationRows(departments.value).map(row => ({ value: row.node.id, label: row.path, disabled: row.node.status !== 'active' })))
  const canAssignDepartment = computed(() => ready.value && departmentsReady.value && canManageDepartments.value && !busy.value && !loading.value && departments.value.some(row => row.id === selectedDepartment.value && row.status === 'active') && assignableRoles.value.some(row => row.id === departmentRole.value))
  const filteredRoles = computed(() => roles.value.filter(row => row.name.toLowerCase().includes(search.value.trim().toLowerCase())))
  const withinActor = (grants: PermissionSet) => !!actor.value && grants.menus.every(key => actor.value!.menus.includes(key)) && grants.apis.every(key => actor.value!.apis.includes(key))
  const valid = computed(() => ready.value && canManage.value && !selected.value?.builtin && !!form.name.trim() && form.name.trim().length <= 64 && form.menus.length <= 32 && form.apis.length <= 64 && withinActor(form) && form.menus.every(key => catalog.value?.menus.includes(key)) && form.apis.every(key => catalog.value?.apis.includes(key)))
  const assignableRoles = computed(() => roles.value.filter(withinActor))
  const memberChoices = computed(() => members.value.filter(row => row.role !== 'owner').map(row => ({ value: row.user_id, label: memberName(row) })))
  const knownMember = (id: string) => members.value.find(row => row.user_id === id)
  const assignmentRows = computed(() => assignments.value.map(row => ({ ...row, member: knownMember(row.user_id), role: roles.value.find(role => role.id === row.role_id) })).filter(row => row.member && row.role))
  const canAssign = computed(() => ready.value && membersReady.value && canManageMembers.value && !busy.value && !!knownMember(selectedMember.value) && knownMember(selectedMember.value)?.role !== 'owner' && assignableRoles.value.some(row => row.id === selectedRole.value) && !assignments.value.some(row => row.user_id === selectedMember.value && row.role_id === selectedRole.value))
  function memberName(row: EnterpriseMember) { return row.display_name || row.username || row.email || t('adminMembers.unnamedMember') }
  function permissionLabel(kind: 'menus' | 'apis', key: string) { const path = `adminRoles.${kind}.${key.replaceAll(':', '_')}`; return te(path) ? t(path) : key }
  function message(reason: unknown) { return reason && typeof reason === 'object' && 'message' in reason && typeof reason.message === 'string' && !reason.message.endsWith('_response_invalid') ? reason.message : t('adminConsole.failed') }
  function closeEditor() { if (!busy.value) { confirmation?.hide(); confirmation = undefined; editor.value = false; selected.value = null; form.name = ''; form.menus = []; form.apis = [] } }
  function invalidate() {
    departments.value = []; departmentsReady.value = false; departmentError.value = ''; selectedDepartment.value = ''; departmentRole.value = ''
    epoch++; confirmation?.hide(); confirmation = undefined
    ready.value = false; membersReady.value = false; roles.value = []; actor.value = null; catalog.value = null; members.value = []; assignments.value = []
    editor.value = false; selected.value = null; form.name = ''; form.menus = []; form.apis = []; selectedMember.value = ''; selectedRole.value = ''
    loading.value = false; busy.value = false; error.value = ''; membersError.value = ''; success.value = ''
  }
  /** 三项核心数据完整读取后才可编辑；成员区独立反馈失败。 */
  async function load() {
    invalidate()
    if (!canManage.value || !auth.effectiveTenantId) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    loading.value = true
    const results = await Promise.allSettled([listEnterpriseRoles(tenant), getRoleCatalog(tenant), getRoleActorPermissions(tenant)])
    if (current !== epoch) return
    if (results[0].status === 'fulfilled' && results[1].status === 'fulfilled' && results[2].status === 'fulfilled') {
      roles.value = results[0].value; catalog.value = results[1].value; actor.value = results[2].value; ready.value = true
    } else { error.value = t('adminConsole.failed'); loading.value = false; return }
    if (canManageMembers.value) {
      const people = await Promise.allSettled([listEnterpriseMembers(tenant), listRoleAssignments(tenant)])
      if (current !== epoch) return
      if (people[0].status === 'fulfilled' && people[1].status === 'fulfilled') { members.value = people[0].value; assignments.value = people[1].value; membersReady.value = true }
      else membersError.value = t('adminConsole.failed')
    }
    if (canManageDepartments.value) {
      try { const rows = await listOrganizationUnits(tenant); if (current !== epoch) return; departments.value = rows; departmentsReady.value = true }
      catch (reason) { if (current === epoch) departmentError.value = message(reason) }
    }
    if (current === epoch) loading.value = false
  }
  function openEditor(row?: EnterpriseRole) {
    if (!canManage.value || !ready.value || busy.value || loading.value || (row && !roles.value.includes(row))) return
    selected.value = row || null; form.name = row?.name || ''; form.menus = [...(row?.menus || [])]; form.apis = [...(row?.apis || [])]; editor.value = true
  }
  /** 写入成功后身份与权限重读失败使用独立反馈，不能将已完成的写入报告为失败。 */
  async function reconcile(tenant: string, user: string | undefined, resultMessage = t('adminRoles.saved')) {
    context.invalidate()
    const revision = context.revision
    const sameIdentity = () => auth.user?.id === user && String(auth.effectiveTenantId) === tenant
    try {
      const valid = await auth.refreshFromAuthMe()
      // 权限清空会由父外壳卸载本页；刷新必须继续，但后续导航/切换产生的代次应终止旧流程。
      if (!sameIdentity() || context.revision !== revision) return
      if (!valid) { auth.logout(); await router.replace('/login'); return }
      const pending = context.load(), loadingRevision = context.revision
      await pending
      if (!sameIdentity() || context.revision !== loadingRevision) return
      if (context.failed) void MessagePlugin.error(t('adminRoles.refreshFailed'))
      else void MessagePlugin.success(resultMessage)
    } catch { if (sameIdentity() && context.revision === revision) void MessagePlugin.error(t('adminRoles.refreshFailed')) }
  }
  function confirmWrite(body: string, operation: (tenant: string) => Promise<unknown>, resultMessage?: () => string) {
    if (!canManage.value || !ready.value || busy.value || loading.value || confirmation) return
    const current = epoch, tenant = String(auth.effectiveTenantId), user = auth.user?.id
    const dialog = DialogPlugin.confirm({ header: t('adminRoles.confirm'), body,
      onConfirm: async () => {
        if (confirmation !== dialog) return
        dialog.hide(); confirmation = undefined
        if (current !== epoch || !canManage.value || busy.value) return
        busy.value = true; error.value = ''; success.value = ''
        try { await operation(tenant) }
        catch (reason) { if (current === epoch) { error.value = message(reason); busy.value = false }; return }
        if (current !== epoch || auth.user?.id !== user || String(auth.effectiveTenantId) !== tenant) return
        await reconcile(tenant, user, resultMessage?.())
      }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
    })
    confirmation = dialog
  }
  function save() {
    if (!editor.value || !valid.value) return
    const id = selected.value?.id, input = { menus: [...form.menus], apis: [...form.apis] }, name = form.name.trim()
    confirmWrite(t('adminRoles.saveConfirm', { name }), tenant => id ? updateEnterpriseRole(tenant, id, input) : createEnterpriseRole(tenant, { name, ...input }))
  }
  function assign() {
    if (!canAssign.value) return
    const user = selectedMember.value, role = selectedRole.value
    confirmWrite(t('adminRoles.assignConfirm', { name: memberName(knownMember(user)!), role: roles.value.find(row => row.id === role)!.name }), tenant => setMemberRoleAssignment(tenant, user, role, true))
  }
  function assignDepartment() {
    if (!canAssignDepartment.value) return
    const unit = selectedDepartment.value, role = departmentRole.value
    const path = departmentChoices.value.find(row => row.value === unit)!.label
    const name = assignableRoles.value.find(row => row.id === role)!.name
    let result = { assigned: [] as string[], skipped: [] as string[] }
    confirmWrite(t('adminRoles.departmentConfirm', { path, role: name }), async tenant => { result = await assignDepartmentRole(tenant, unit, role) }, () => t('adminRoles.departmentResult', { assigned: result.assigned.length, skipped: result.skipped.length }))
  }
  function revoke(user: string, role: string) {
    const member = knownMember(user), row = roles.value.find(item => item.id === role)
    if (!canManageMembers.value || !membersReady.value || !member || !row || !assignments.value.some(item => item.user_id === user && item.role_id === role)) return
    confirmWrite(t('adminRoles.revokeConfirm', { name: memberName(member), role: row.name }), tenant => setMemberRoleAssignment(tenant, user, role, false))
  }
  watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.ready, () => context.revision, canManage, canManageMembers, canManageDepartments], () => { void load() }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(invalidate)
  return { reconcile, departmentsReady, departmentError, departmentChoices, selectedDepartment, departmentRole, canManageDepartments, canAssignDepartment, assignDepartment, roles, catalog, actor, ready, membersReady, loading, busy, error, membersError, success, search, editor, selected, form, selectedMember, selectedRole, canManage, canManageMembers, filteredRoles, valid, assignableRoles, memberChoices, assignmentRows, canAssign, memberName, permissionLabel, closeEditor, load, openEditor, save, assign, revoke }
}
