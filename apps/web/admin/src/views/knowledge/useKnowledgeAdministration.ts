/** 企业知识库目录及内容管理员编排。目标代次和身份代次共同保护查询、确认及写入后反馈。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from '../../stores/context'
import { listEnterpriseKnowledgeBases, listKnowledgeMaintainers, addKnowledgeMaintainer, removeKnowledgeMaintainer, type EnterpriseKnowledgeBase, type KnowledgeMaintainer } from '@nexus-web/core/api/enterprise-knowledge'
import { listEnterpriseMembers, type EnterpriseMember } from '@nexus-web/core/api/enterprise-members'

export function useKnowledgeAdministration() {
  const auth = useAuthStore(), context = useAdminContext(), { t } = useI18n()
  const rows = ref<EnterpriseKnowledgeBase[]>([]), loading = ref(false), ready = ref(false), error = ref(''), search = ref('')
  const editor = ref(false), editingId = ref<string | undefined>(undefined)
  const editorKey = computed(() => `${tenant.value}:${auth.user?.id}:${context.revision}`)
  function openEditor(row?: EnterpriseKnowledgeBase) {
    if (!canManage.value || !ready.value || busy.value || editor.value || (row && (!rows.value.includes(row) || !row.can_manage))) return
    editingId.value = row?.id; editor.value = true
  }
  function openSettings() { void MessagePlugin.info(t('adminKnowledge.settingsUnavailable')) }
  const selected = ref<EnterpriseKnowledgeBase | null>(null), maintainers = ref<KnowledgeMaintainer[]>([]), members = ref<EnterpriseMember[]>([])
  const maintainersReady = ref(false), membersReady = ref(false), panelLoading = ref(false), busy = ref(false)
  const panelError = ref(''), membersError = ref(''), success = ref(''), selectedMember = ref('')
  const canManage = computed(() => context.can('enterprise_kbs:manage'))
  const canReadMembers = computed(() => context.can('members:manage'))
  const tenant = computed(() => String(auth.effectiveTenantId || ''))
  const filtered = computed(() => rows.value.filter(row => `${row.name} ${row.description}`.toLowerCase().includes(search.value.trim().toLowerCase())))
  const candidates = computed(() => members.value.filter(member => !maintainers.value.some(row => row.user_id === member.user_id)))
  const memberName = (member: EnterpriseMember) => member.display_name || member.username || member.email || t('adminMembers.unnamedMember')
  const maintainerName = (member: KnowledgeMaintainer) => member.display_name || member.email || t('adminMembers.unnamedMember')
  const memberOptions = computed(() => candidates.value.map(member => ({ value: member.user_id, label: [memberName(member), member.email].filter((value, index, all) => value && all.indexOf(value) === index).join(' · ') })))
  const editable = computed(() => canManage.value && !!selected.value?.can_manage && maintainersReady.value && !panelLoading.value && !busy.value)
  const canAdd = computed(() => editable.value && canReadMembers.value && membersReady.value && candidates.value.some(row => row.user_id === selectedMember.value))
  let epoch = 0, panelEpoch = 0, read = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
  function resetPanel() {
    panelEpoch++; confirmation?.hide(); confirmation = undefined
    selected.value = null; maintainers.value = []; members.value = []; maintainersReady.value = false; membersReady.value = false
    panelLoading.value = false; busy.value = false; panelError.value = ''; membersError.value = ''; success.value = ''; selectedMember.value = ''
  }
  function invalidate() { editor.value = false; editingId.value = undefined; epoch++; read++; resetPanel(); rows.value = []; ready.value = false; loading.value = false; error.value = ''; search.value = '' }
  async function load() {
    if (busy.value) return
    const current = epoch, request = ++read, scope = tenant.value
    resetPanel(); rows.value = []; ready.value = false; error.value = ''
    if (!canManage.value || !scope) return
    loading.value = true
    try { const result = await listEnterpriseKnowledgeBases(scope); if (current === epoch && request === read) { rows.value = result; ready.value = true } }
    catch { if (current === epoch && request === read) error.value = t('adminConsole.failed') }
    finally { if (current === epoch && request === read) loading.value = false }
  }
  /** 管理员与成员目录独立处理失败；成员列表不可用时仍可撤销已有管理员。 */
  async function inspect(row: EnterpriseKnowledgeBase) {
    if (!canManage.value || !ready.value || busy.value || !row.can_manage || !rows.value.includes(row)) return
    resetPanel(); selected.value = row
    const current = epoch, target = panelEpoch, scope = tenant.value
    panelLoading.value = true
    const results = await Promise.allSettled([listKnowledgeMaintainers(scope, row.id), canReadMembers.value ? listEnterpriseMembers(scope) : Promise.resolve(null)])
    if (current !== epoch || target !== panelEpoch) return
    if (results[0].status === 'fulfilled') { maintainers.value = results[0].value; maintainersReady.value = true }
    else panelError.value = t('adminConsole.failed')
    if (results[1].status === 'fulfilled' && results[1].value !== null) { members.value = results[1].value; membersReady.value = true }
    else if (results[1].status === 'rejected') membersError.value = t('adminKnowledge.membersFailed')
    panelLoading.value = false
  }
  function closePanel() { if (!busy.value) resetPanel() }
  function confirmWrite(adding: boolean, user: string, name: string) {
    if (!editable.value || !selected.value || confirmation) return
    const current = epoch, target = panelEpoch, scope = tenant.value, kb = selected.value.id
    const valid = () => current === epoch && target === panelEpoch && canManage.value
    const dialog = DialogPlugin.confirm({ header: t(adding ? 'adminKnowledge.add' : 'adminKnowledge.remove'), body: t(adding ? 'adminKnowledge.addConfirm' : 'adminKnowledge.removeConfirm', { kb: selected.value.name, member: name }),
      onConfirm: async () => {
        if (confirmation !== dialog) return
        dialog.hide(); confirmation = undefined
        if (!valid() || busy.value) return
        busy.value = true; panelError.value = ''; success.value = ''
        try {
          if (adding) {
            const result = await addKnowledgeMaintainer(scope, kb, user)
            if (!valid()) return
            maintainers.value = result; selectedMember.value = ''
          } else {
            await removeKnowledgeMaintainer(scope, kb, user)
            if (!valid()) return
          }
        } catch { if (valid()) { panelError.value = t('adminConsole.failed'); busy.value = false }; return }
        success.value = t(adding ? 'adminKnowledge.added' : 'adminKnowledge.removed')
        if (!adding) {
          // 写入已成功，重读失败单独反馈，不能把成功的撤销报告为写入失败。
          maintainersReady.value = false; maintainers.value = []
          try { const result = await listKnowledgeMaintainers(scope, kb); if (!valid()) return; maintainers.value = result; maintainersReady.value = true }
          catch { if (valid()) panelError.value = t('adminKnowledge.refreshFailed') }
        }
        if (valid()) busy.value = false
      }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
    })
    confirmation = dialog
  }
  function add() {
    const member = candidates.value.find(row => row.user_id === selectedMember.value)
    if (canAdd.value && member) confirmWrite(true, member.user_id, memberName(member))
  }
  function remove(row: KnowledgeMaintainer) { if (editable.value && maintainers.value.includes(row)) confirmWrite(false, row.user_id, maintainerName(row)) }
  watch([tenant, () => auth.user?.id, () => context.revision, canManage, canReadMembers], () => { invalidate(); void load() }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(invalidate)
  return { editor, editingId, editorKey, tenant, openEditor, openSettings, rows, loading, ready, error, search, selected, maintainers, maintainersReady, membersReady, panelLoading, busy, panelError, membersError, success, selectedMember, canManage, canReadMembers, filtered, memberOptions, maintainerName, canAdd, editable, load, inspect, closePanel, add, remove }
}
