<script setup lang="ts">
/** 企业文件存储目录；只开放服务端已有的本地后端增删与已保存连接测试。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from '../../stores/context'
import { createEnterpriseStorageBackend, deleteEnterpriseStorageBackend, listEnterpriseStorageBackends, testEnterpriseStorageBackend, type EnterpriseStorageBackend } from '@nexus-web/core/api/enterprise-storage'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const rows = ref<EnterpriseStorageBackend[]>([]), ready = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const name = ref(''), root = ref('')
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const canManage = computed(() => context.can('enterprise_kbs:manage'))
async function load() {
  const current = ++epoch, scope = tenant.value
  ready.value = false; rows.value = []; error.value = ''
  if (!scope || !canManage.value) return
  loading.value = true
  try { const result = await listEnterpriseStorageBackends(scope); if (current === epoch) { rows.value = result; ready.value = true } }
  catch { if (current === epoch) error.value = t('adminStorage.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; ready.value = false; loading.value = false; busy.value = false; error.value = ''; name.value = ''; root.value = '' }
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
async function add() {
  if (!canManage.value || !ready.value || busy.value || !name.value.trim() || !root.value.trim()) return
  const current = epoch, scope = tenant.value
  busy.value = true; error.value = ''
  try {
    const result = await createEnterpriseStorageBackend(scope, name.value.trim(), root.value.trim())
    if (current !== epoch || !canManage.value) return
    rows.value = [...rows.value, result]; name.value = ''; root.value = ''; MessagePlugin.success(t('adminStorage.created'))
  } catch { if (current === epoch) error.value = t('adminStorage.saveFailed') }
  finally { if (current === epoch) busy.value = false }
}
async function test(row: EnterpriseStorageBackend) {
  if (!canManage.value || busy.value || !ready.value) return
  const current = epoch, scope = tenant.value
  busy.value = true; error.value = ''
  try { const result = await testEnterpriseStorageBackend(scope, row.id); if (current !== epoch) return
    if (result.ok) MessagePlugin.success(t('adminStorage.testOk'))
    else error.value = result.message || t('adminStorage.testFailed')
  } catch { if (current === epoch) error.value = t('adminStorage.testFailed') }
  finally { if (current === epoch) busy.value = false }
}
function remove(row: EnterpriseStorageBackend) {
  if (!canManage.value || row.builtin || busy.value || !ready.value || confirmation) return
  const current = epoch, scope = tenant.value
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminStorage.deleteTitle'), body: t('adminStorage.deleteConfirm', { name: row.name }), theme: 'danger',
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (current !== epoch || !canManage.value || busy.value) return
      busy.value = true; error.value = ''
      try { await deleteEnterpriseStorageBackend(scope, row.id); if (current !== epoch) return
        rows.value = rows.value.filter(item => item.id !== row.id); MessagePlugin.success(t('adminStorage.deleted'))
      } catch { if (current === epoch) error.value = t('adminStorage.deleteFailed') }
      finally { if (current === epoch) busy.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
</script>

<template>
  <section class="storage-page">
    <header class="section-header"><div><h2>{{ t('adminStorage.title') }}</h2><p>{{ t('adminStorage.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminStorage.scopeHint')" />
      <t-alert v-if="error" theme="error" :message="error" />
      <section class="storage-form"><h3>{{ t('adminStorage.addTitle') }}</h3><div class="fields"><label>{{ t('adminStorage.name') }}<t-input v-model="name" :maxlength="160" :disabled="busy" /></label><label>{{ t('adminStorage.root') }}<t-input v-model="root" :disabled="busy" :placeholder="t('adminStorage.rootPlaceholder')" /></label><t-button theme="primary" :disabled="!ready || busy || !name.trim() || !root.trim()" :loading="busy" @click="add">{{ t('adminStorage.add') }}</t-button></div></section>
      <t-loading :loading="loading"><div v-if="ready" class="table-shell"><table><thead><tr><th>{{ t('adminStorage.name') }}</th><th>{{ t('adminStorage.provider') }}</th><th>{{ t('adminStorage.kind') }}</th><th>{{ t('adminStorage.actions') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.name }}</td><td>{{ row.provider }}</td><td>{{ t(row.builtin ? 'adminStorage.builtin' : 'adminStorage.custom') }}</td><td><t-button variant="text" :disabled="busy" @click="test(row)">{{ t('adminStorage.test') }}</t-button><t-button v-if="!row.builtin" variant="text" theme="danger" :disabled="busy" @click="remove(row)">{{ t('adminStorage.delete') }}</t-button></td></tr><tr v-if="!rows.length"><td colspan="4">{{ t('adminStorage.empty') }}</td></tr></tbody></table></div></t-loading>
    </template>
  </section>
</template>

<style scoped>
.storage-page { min-width: 0; }
.storage-form { margin: 24px 0; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.storage-form h3 { margin: 0 0 16px; }
.fields { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 16px; }
.fields label { display: grid; gap: 8px; width: min(340px, 100%); }
.fields :deep(.t-input) { width: 100%; }
.table-shell { max-width: 100%; overflow-x: auto; margin-top: 16px; }
table { width: 100%; min-width: 560px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
</style>
