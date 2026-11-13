/** 成员与邀请的管理状态：按身份/企业/权限代次隔离，秘密不持久化，所有破坏性操作先确认。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { addEnterpriseMember, changeEnterpriseMemberRole, createEnterpriseInviteLink, listEnterpriseInvitations, listEnterpriseMembers, removeEnterpriseMember, revokeEnterpriseInvitation, type EnterpriseInvitation, type EnterpriseMember, type InviteRole, type MemberEmailInput, type MemberRole } from '@nexus-web/core/api/enterprise-members'
import { useAdminContext } from '../../stores/context'

type Translate = (key: string, values?: Record<string, unknown>) => string
/** 只对当前服务端允许的成员管理作用域发请求，路由卸载时一并作废请求与确认弹窗。 */
export function useMemberAdministration(t: Translate) {
  const auth = useAuthStore(), context = useAdminContext(), router = useRouter()
  const members = ref<EnterpriseMember[]>([]), invitations = ref<EnterpriseInvitation[]>([])
  const loading = ref(false), busy = ref(false), membersError = ref(''), invitationsError = ref(''), error = ref(''), success = ref('')
  const membersReady = ref(false), invitationsReady = ref(false)
  const tab = ref('members'), search = ref(''), memberPage = ref(1), invitePage = ref(1)
  const pageSize = 20
  const editorOpen = ref(false), createAccount = ref(false), linkOpen = ref(false)
  const form = reactive<{ email: string; role: InviteRole; username: string; password: string; display_name: string }>({ email: '', role: 'contributor', username: '', password: '', display_name: '' })
  const linkForm = reactive<{ role: InviteRole; days: number | undefined }>({ role: 'contributor', days: 7 })
  const canManage = computed(() => context.can('members:manage'))
  const ownerCount = computed(() => members.value.filter(row => row.role === 'owner').length)
  const filteredMembers = computed(() => { const query = search.value.trim().toLowerCase(); return members.value.filter(row => [row.email, row.username, row.display_name].some(value => (value || '').toLowerCase().includes(query))) })
  const memberRows = computed(() => filteredMembers.value.slice((memberPage.value - 1) * pageSize, memberPage.value * pageSize))
  const invitationRows = computed(() => invitations.value.slice((invitePage.value - 1) * pageSize, invitePage.value * pageSize))
  let epoch = 0
  let confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
  function message(reason: unknown): string { return reason instanceof Error && reason.message !== 'members_response_invalid' ? reason.message : t('adminConsole.failed') }
  function closeEditor() { editorOpen.value = false; Object.assign(form, { email: '', role: 'contributor', username: '', password: '', display_name: '' }); createAccount.value = false }
  function closeLink() { linkOpen.value = false; Object.assign(linkForm, { role: 'contributor', days: 7 }) }
  function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; closeEditor(); closeLink(); members.value = []; invitations.value = []; membersReady.value = false; invitationsReady.value = false; loading.value = false; busy.value = false; membersError.value = ''; invitationsError.value = ''; error.value = ''; success.value = '' }
  async function load() {
    invalidate()
    if (!canManage.value || !auth.effectiveTenantId) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    loading.value = true
    const results = await Promise.allSettled([listEnterpriseMembers(tenant), listEnterpriseInvitations(tenant)])
    if (current !== epoch) return
    if (results[0].status === 'fulfilled') { members.value = results[0].value; membersReady.value = true } else membersError.value = message(results[0].reason)
    if (results[1].status === 'fulfilled') { invitations.value = results[1].value; invitationsReady.value = true } else invitationsError.value = message(results[1].reason)
    loading.value = false
  }
  function memberName(row: EnterpriseMember): string { return row.display_name || row.username || row.email || t('adminMembers.unnamedMember') }
  function invitationName(row: EnterpriseInvitation): string { return row.kind === 'link' ? t('adminMembers.link') : row.display_name || row.email || t('adminMembers.unnamedMember') }
  function knownMember(row: EnterpriseMember): boolean { return membersReady.value && members.value.some(item => item.user_id === row.user_id) }
  function canEditMember(row: EnterpriseMember): boolean { return canManage.value && knownMember(row) && (row.role !== 'owner' || auth.currentTenantRole === 'owner') }
  function canRemoveMember(row: EnterpriseMember): boolean { return canEditMember(row) && (row.role !== 'owner' || ownerCount.value > 1) }
  function roleOptions(row: EnterpriseMember) { return (['owner', 'admin', 'contributor', 'viewer'] as const).filter(value => value !== 'owner' || auth.currentTenantRole === 'owner').map(value => ({ value, label: t(`tenantMember.role.${value}`), disabled: row.role === 'owner' && ownerCount.value <= 1 && value !== 'owner' })) }
  /** 对自身的角色/成员资格写入后重新校准身份，立即撤掉已经失去的管理能力。 */
  async function reconcileSelf(tenant: string, userId: string) {
    if (auth.user?.id !== userId || String(auth.effectiveTenantId) !== tenant) return
    context.invalidate()
    const valid = await auth.refreshFromAuthMe()
    if (auth.user?.id !== userId) return
    if (!valid) { auth.logout(); await router.replace('/login'); return }
    await context.load()
  }
  function confirmAction(body: string, operation: (tenant: string) => Promise<void>, applied?: (tenant: string) => Promise<void>) {
    if (!canManage.value || busy.value || loading.value || confirmation) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    const dialog = DialogPlugin.confirm({ header: t('adminMembers.confirm'), body,
      onConfirm: async () => {
        if (confirmation !== dialog) return
        dialog.hide(); if (confirmation === dialog) confirmation = undefined
        if (current !== epoch || !canManage.value || busy.value) return
        busy.value = true; error.value = ''; success.value = ''
        try {
          await operation(tenant)
          if (current !== epoch) return
          success.value = t('adminMembers.updated')
          if (applied) await applied(tenant)
        } catch (reason) { if (current === epoch) error.value = message(reason) }
        finally { if (current === epoch) busy.value = false }
      }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
    })
    confirmation = dialog
  }
  function changeRole(row: EnterpriseMember, value: unknown) {
    if (!canEditMember(row) || typeof value !== 'string' || !['owner', 'admin', 'contributor', 'viewer'].includes(value) || value === row.role) return
    const nextRole = value as MemberRole
    if ((nextRole === 'owner' && auth.currentTenantRole !== 'owner') || (row.role === 'owner' && nextRole !== 'owner' && ownerCount.value <= 1)) return
    let updated: EnterpriseMember
    confirmAction(t('adminMembers.roleConfirm', { name: memberName(row), role: t(`tenantMember.role.${nextRole}`) }), async tenant => { updated = await changeEnterpriseMemberRole(tenant, row.user_id, nextRole) }, async tenant => {
      members.value = members.value.map(item => item.user_id === row.user_id ? updated : item)
      if (row.user_id === auth.user?.id) await reconcileSelf(tenant, row.user_id)
    })
  }
  function remove(row: EnterpriseMember) {
    if (!canRemoveMember(row)) return
    confirmAction(t('adminMembers.removeConfirm', { name: memberName(row) }), tenant => removeEnterpriseMember(tenant, row.user_id), async tenant => {
      members.value = members.value.filter(item => item.user_id !== row.user_id)
      if (row.user_id === auth.user?.id) await reconcileSelf(tenant, row.user_id)
    })
  }
  function revoke(row: EnterpriseInvitation) {
    if (!invitationsReady.value || !invitations.value.some(item => item.id === row.id)) return
    confirmAction(t('adminMembers.revokeConfirm', { name: invitationName(row) }), tenant => revokeEnterpriseInvitation(tenant, row.id), async () => { invitations.value = invitations.value.filter(item => item.id !== row.id) })
  }
  function openEditor() { if (!canManage.value || busy.value || loading.value) return; closeEditor(); editorOpen.value = true }
  function openLink() { if (!canManage.value || busy.value || loading.value) return; closeLink(); linkOpen.value = true }
  async function submitMember({ validateResult }: { validateResult: unknown }) {
    if (validateResult !== true || !canManage.value || !editorOpen.value || busy.value || loading.value) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    const input: MemberEmailInput = { email: form.email.trim().toLowerCase(), role: form.role }
    if (createAccount.value) { input.username = form.username.trim().toLowerCase(); input.password = form.password; input.display_name = form.display_name.trim() }
    form.password = ''; busy.value = true; error.value = ''; success.value = ''
    try {
      const result = await addEnterpriseMember(tenant, input)
      input.password = undefined
      if (current !== epoch) return
      closeEditor(); await load()
      if (epoch === current + 1) success.value = t(result.status === 'created' ? 'adminMembers.created' : 'adminMembers.invited')
    } catch (reason) { if (current === epoch) error.value = message(reason) }
    finally { input.password = undefined; if (current === epoch) busy.value = false }
  }
  async function submitLink({ validateResult }: { validateResult: unknown }) {
    if (validateResult !== true || !canManage.value || !linkOpen.value || busy.value || loading.value || typeof linkForm.days !== 'number' || !Number.isInteger(linkForm.days) || linkForm.days < 1 || linkForm.days > 30) return
    const current = epoch, tenant = String(auth.effectiveTenantId)
    busy.value = true; error.value = ''; success.value = ''
    try { const row = await createEnterpriseInviteLink(tenant, linkForm.role, linkForm.days); if (current === epoch) { invitations.value.unshift(row); invitationsReady.value = true; closeLink(); tab.value = 'invitations'; invitePage.value = 1; success.value = t('adminMembers.linkCreated') } }
    catch (reason) { if (current === epoch) error.value = message(reason) }
    finally { if (current === epoch) busy.value = false }
  }
  watch(createAccount, () => { form.password = '' }, { flush: 'sync' })
  watch(search, () => { memberPage.value = 1 })
  watch(() => filteredMembers.value.length, count => { memberPage.value = Math.min(memberPage.value, Math.max(1, Math.ceil(count / pageSize))) })
  watch(() => invitations.value.length, count => { invitePage.value = Math.min(invitePage.value, Math.max(1, Math.ceil(count / pageSize))) })
  watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canManage], () => { search.value = ''; memberPage.value = 1; invitePage.value = 1; void load() }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(invalidate)
  return { members, invitations, loading, busy, membersError, invitationsError, error, success, membersReady, invitationsReady, tab, search, memberPage, invitePage, pageSize, filteredMembers, memberRows, invitationRows, canManage, ownerCount, editorOpen, createAccount, form, linkOpen, linkForm, load, closeEditor, closeLink, memberName, invitationName, canEditMember, canRemoveMember, roleOptions, changeRole, remove, revoke, openEditor, openLink, submitMember, submitLink }
}
