/** 企业目录和归档编排；刷新列表不重挂编辑器，发布失败时可继续编辑同一份草稿。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listEnterpriseAgents, archiveEnterpriseAgent } from '@nexus-web/core/api/enterprise-agents'
import type { NexusAgent } from '@nexus-web/core/api/nexus-agents'
import { useAdminContext } from '../../stores/context'

export function useAgentAdministration() {
  const auth = useAuthStore(), context = useAdminContext(), { t } = useI18n()
  const rows = ref<NexusAgent[]>([]), loading = ref(false), ready = ref(false), busy = ref(false), error = ref(''), search = ref('')
  const editor = ref(false), selected = ref<string | null>(null), revision = ref(0)
  const tenant = computed(() => String(auth.effectiveTenantId || ''))
  const canManage = computed(() => context.can('enterprise_agents:manage'))
  const canGrant = computed(() => context.can('roles:manage'))
  const filtered = computed(() => rows.value.filter(row => `${row.name} ${row.description}`.toLowerCase().includes(search.value.trim().toLowerCase())))
  let epoch = 0, read = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
  function invalidate() {
    epoch++; read++; revision.value++; confirmation?.hide(); confirmation = undefined
    rows.value = []; loading.value = false; ready.value = false; busy.value = false; error.value = ''; search.value = ''; editor.value = false; selected.value = null
  }
  async function load() {
    if (!canManage.value || !tenant.value) return
    const current = epoch, request = ++read, scope = tenant.value
    loading.value = true; ready.value = false; rows.value = []; error.value = ''
    try { const result = await listEnterpriseAgents(scope); if (current === epoch && request === read) { rows.value = result; ready.value = true } }
    catch { if (current === epoch && request === read) error.value = t('adminConsole.failed') }
    finally { if (current === epoch && request === read) loading.value = false }
  }
  function open(row?: NexusAgent) {
    if (!canManage.value || !ready.value || busy.value || editor.value || (row && (!rows.value.includes(row) || !row.can_maintain))) return
    selected.value = row?.id || null; editor.value = true
  }
  function archive(row: NexusAgent) {
    if (!canManage.value || !ready.value || busy.value || editor.value || confirmation || !rows.value.includes(row) || !row.can_maintain) return
    const current = epoch, scope = tenant.value
    const dialog = DialogPlugin.confirm({ header: t('adminAgents.archive'), body: t('adminAgents.archiveConfirm', { name: row.name }),
      onConfirm: async () => {
        if (confirmation !== dialog) return
        dialog.hide(); confirmation = undefined
        if (current !== epoch || !canManage.value || busy.value) return
        busy.value = true; error.value = ''
        try { await archiveEnterpriseAgent(scope, row.id) }
        catch { if (current === epoch) { error.value = t('adminConsole.failed'); busy.value = false }; return }
        if (current !== epoch) return
        void MessagePlugin.success(t('adminAgents.archived'))
        await load()
        if (current === epoch) busy.value = false
      }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
    })
    confirmation = dialog
  }
  function modelSettings() { void MessagePlugin.info(t('adminAgents.modelsPending')) }
  watch([tenant, () => auth.user?.id, () => context.revision, canManage], () => { invalidate(); void load() }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(invalidate)
  return { rows, loading, ready, busy, error, search, editor, selected, revision, tenant, canManage, canGrant, filtered, load, open, archive, modelSettings }
}
