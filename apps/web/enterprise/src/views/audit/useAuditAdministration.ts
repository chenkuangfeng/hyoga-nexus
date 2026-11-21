/** 审计元数据与日期导出编排；迟到响应不能在切换企业后更新列表或下载旧企业文件。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useEnterpriseContext } from '../../stores/context'
import { listEnterpriseAudit, exportEnterpriseAudit, validAuditExportRange, type EnterpriseAuditRecord } from '@nexus-web/core/api/enterprise-audit'

export function useAuditAdministration() {
  const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
  const rows = ref<EnterpriseAuditRecord[]>([]), loaded = ref(false), loading = ref(false), exporting = ref(false)
  const error = ref(''), exportError = ref(''), exported = ref(false), search = ref(''), limit = ref(100), selected = ref<EnterpriseAuditRecord | null>(null)
  const end = ref(new Date().toISOString().slice(0, 10)), start = ref(new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10))
  let epoch = 0, readEpoch = 0, exportEpoch = 0
  const canRead = computed(() => context.can('audit:read'))
  const validRange = computed(() => validAuditExportRange(start.value, end.value))
  const filteredRows = computed(() => {
    const query = search.value.trim().toLowerCase()
    return rows.value.filter(row => !query || [row.action, row.result, row.actor_user_id || '', row.target_type, row.target_id].some(value => value.toLowerCase().includes(query)))
  })
  function message(reason: unknown) { return reason && typeof reason === 'object' && 'message' in reason && typeof reason.message === 'string' && !reason.message.endsWith('_invalid') ? reason.message : t('adminConsole.failed') }
  function invalidate() {
    epoch++; readEpoch++; exportEpoch++
    rows.value = []; selected.value = null; search.value = ''; loaded.value = false; loading.value = false; exporting.value = false; error.value = ''; exportError.value = ''; exported.value = false
  }
  async function load() {
    const scope = epoch, current = ++readEpoch
    rows.value = []; selected.value = null; loaded.value = false; error.value = ''; loading.value = false
    if (!canRead.value) return
    loading.value = true
    try { const result = await listEnterpriseAudit(String(auth.effectiveTenantId), limit.value); if (scope === epoch && current === readEpoch) { rows.value = result; loaded.value = true } }
    catch (reason) { if (scope === epoch && current === readEpoch) error.value = message(reason) }
    finally { if (scope === epoch && current === readEpoch) loading.value = false }
  }
  /** 获取 Blob 后再次核对作用域，再触发下载；延迟释放 URL，避免浏览器尚未接收时被回收。 */
  async function download() {
    if (!canRead.value || !validRange.value || exporting.value) return
    const scope = epoch, current = ++exportEpoch, tenant = String(auth.effectiveTenantId), from = start.value, to = end.value
    exporting.value = true; exportError.value = ''; exported.value = false
    try {
      const blob = await exportEnterpriseAudit(tenant, from, to)
      if (scope !== epoch || current !== exportEpoch || !canRead.value) return
      const url = URL.createObjectURL(blob), anchor = document.createElement('a')
      anchor.href = url; anchor.download = `audit-${tenant}-${from}-${to}.jsonl`
      try { document.body.appendChild(anchor); anchor.click() }
      finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
      exported.value = true
    } catch (reason) { if (scope === epoch && current === exportEpoch) exportError.value = message(reason) }
    finally { if (scope === epoch && current === exportEpoch) exporting.value = false }
  }
  function inspect(row: EnterpriseAuditRecord) { if (canRead.value && rows.value.includes(row)) selected.value = row }
  watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canRead], () => { invalidate(); void load() }, { immediate: true, flush: 'sync' })
  watch(limit, () => { void load() })
  onBeforeUnmount(invalidate)
  return { rows, loaded, loading, exporting, error, exportError, exported, search, limit, selected, start, end, canRead, validRange, filteredRows, load, download, inspect }
}
