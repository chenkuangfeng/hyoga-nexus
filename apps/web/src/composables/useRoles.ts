import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/chat'
import { workspace } from '../stores/workspace'
import { roleApi } from '../api/roles'
import type { Agent } from '../types/chat'
import { AGENT_PERMISSIONS, type AgentPermission, type AgentGrantRow, type PermissionCatalog, type Permissions,
  type RoleAssignment, type TenantMember, type TenantRole } from '../types/roles'

/** State for the tenant role page: roles, member assignments and agent grants.
 * Every request is scoped to the selected tenant; late responses from a previous tenant are dropped.
 * Management actions are only offered when the caller holds roles:manage; the server still decides.
 */
export function useRoles() {
  const tenants = computed(() => workspace.tenants), tenant = computed(() => workspace.tenantId)
  const loading = ref(false), busy = ref(false)
  const error = ref(''), feedback = ref('')
  const catalog = ref<PermissionCatalog>({ menus: [], apis: [] })
  const mine = ref<Permissions>({ menus: [], apis: [] })
  const roles = ref<TenantRole[]>([]), members = ref<TenantMember[]>([]), assignments = ref<RoleAssignment[]>([])
  const agents = ref<Agent[]>([]), grants = ref<AgentGrantRow[]>([])
  const canManage = computed(() => mine.value.apis.includes('roles:manage'))
  const roleDialog = ref(false), editingRoleId = ref('')
  const roleForm = reactive({ name: '', menus: [] as string[], apis: [] as string[] })
  const grantRoleId = ref(''), grantAgentId = ref(''), grantPermissions = ref<AgentPermission[]>([])
  const agentPermissions = AGENT_PERMISSIONS
  let controller: AbortController | undefined, disposed = false

  const memberRows = computed(() => members.value.filter(item => item.status === 'active'))
  /** Owner and admin memberships already hold full access, so role assignment is not offered for them. */
  const assignableMembers = computed(() => memberRows.value.filter(item => item.role === 'member'))
  const rolesOf = (userId: string) => assignments.value.filter(item => item.user_id === userId).map(item => item.role_id)

  async function load() {
    if (disposed) return
    controller?.abort(); controller = new AbortController(); const signal = controller.signal
    loading.value = true; error.value = ''
    if (!tenant.value) { loading.value = false; roles.value = []; members.value = []; return }
    try {
      const [cat, perms] = await Promise.all([roleApi.catalog(tenant.value, signal), roleApi.myPermissions(tenant.value, signal)])
      if (signal.aborted || disposed) return
      catalog.value = cat; mine.value = perms
      if (!perms.apis.includes('roles:manage')) { roles.value = []; members.value = []; assignments.value = []; grants.value = []; agents.value = []; return }
      const [roleRows, memberRows, assignRows, grantRows, agentRows] = await Promise.all([
        roleApi.roles(tenant.value, signal), roleApi.members(tenant.value, signal), roleApi.assignments(tenant.value, signal),
        roleApi.agentGrants(tenant.value, signal), api.agents(tenant.value, signal),
      ])
      if (signal.aborted || disposed) return
      roles.value = roleRows; members.value = memberRows; assignments.value = assignRows; grants.value = grantRows; agents.value = agentRows
    } catch (e) { if (!signal.aborted && !disposed) error.value = e instanceof Error ? e.message : '加载失败' }
    finally { if (!signal.aborted && !disposed) loading.value = false }
  }

  async function perform(action: () => Promise<void>, message: string) {
    if (busy.value || disposed) return
    busy.value = true; error.value = ''; feedback.value = ''
    try { await action(); if (!disposed) feedback.value = message }
    catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '操作未完成' }
    finally { if (!disposed) busy.value = false }
  }

  function openRole(role?: TenantRole) {
    editingRoleId.value = role?.id || ''
    Object.assign(roleForm, { name: role?.name || '', menus: [...(role?.menus || [])], apis: [...(role?.apis || [])] })
    roleDialog.value = true
  }
  const saveRole = () => perform(async () => {
    const menus = [...roleForm.menus], apis = [...roleForm.apis]
    if (editingRoleId.value) await roleApi.updateRole(tenant.value, editingRoleId.value, menus, apis)
    else await roleApi.createRole(tenant.value, roleForm.name.trim(), menus, apis)
    roleDialog.value = false; await load()
  }, '角色已保存')

  /** Replace one member's role set by diffing against the current assignments. */
  const setMemberRoles = (userId: string, selected: string[]) => perform(async () => {
    const current = rolesOf(userId)
    for (const roleId of selected.filter(id => !current.includes(id))) await roleApi.assign(tenant.value, userId, roleId)
    for (const roleId of current.filter(id => !selected.includes(id))) await roleApi.unassign(tenant.value, userId, roleId)
    await load()
  }, '成员角色已更新')

  const currentGrant = computed(() => grants.value.filter(row => row.role_id === grantRoleId.value && row.agent_id === grantAgentId.value).map(row => row.permission))
  watch([grantRoleId, grantAgentId, grants], () => { grantPermissions.value = [...currentGrant.value] })
  const saveGrant = () => perform(async () => {
    await roleApi.setAgentGrants(tenant.value, grantRoleId.value, grantAgentId.value, [...grantPermissions.value])
    await load()
  }, '智能体权限已保存')

  /** Create a password account in the selected tenant. The caller clears its password input after this settles. */
  const createAccount = (username: string, displayName: string, password: string, role: 'admin' | 'member') => perform(async () => {
    await roleApi.createAccount(tenant.value, username.trim(), displayName.trim(), password, role)
    await load()
  }, '账号已创建，请把账号与初始密码交给成员并提醒其修改')

  // The space comes from the shell's selector; a change reloads this page's data.
  async function initialize() {
    loading.value = true
    try { if (!disposed) await load() }
    catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '空间加载失败' }
    finally { if (!disposed) loading.value = false }
  }
  onMounted(initialize)
  watch(() => workspace.tenantId, () => { if (!disposed) void initialize() })
  onBeforeUnmount(() => { disposed = true; controller?.abort() })
  return { tenants, tenant, loading, busy, error, feedback, catalog, mine, canManage, roles, members, assignments, agents,
    grants, roleDialog, editingRoleId, roleForm, grantRoleId, grantAgentId, grantPermissions, agentPermissions,
    memberRows, assignableMembers, rolesOf, load, initialize, openRole, saveRole, setMemberRoles, saveGrant, createAccount }
}
