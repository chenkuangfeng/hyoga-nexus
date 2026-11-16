<script setup lang="ts">
/** 企业文件存储目录；只开放服务端已有的本地后端增删与已保存连接测试。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { providerLogo } from '@nexus-web/core/utils/providerLogos'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from '../../stores/context'
import { createEnterpriseStorageBackend, deleteEnterpriseStorageBackend, listEnterpriseStorageBackends, testEnterpriseStorageBackend, type EnterpriseStorageBackend } from '@nexus-web/core/api/enterprise-storage'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
/** 沿用原版的官方 SVG / 单色 mask 与未知提供方字母回退。 */
const resolveLogo = (id: string) => providerLogo('storage', id)
const badgeClass = (id: string) => ({ 'backend-card__badge--logo': !!resolveLogo(id), 'backend-card__badge--mono': resolveLogo(id)?.mode === 'mono' })
const badgeStyle = (id: string) => resolveLogo(id)?.mode === 'mono' ? { '--logo-url': `url("${resolveLogo(id)!.url}")` } : {}
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const rows = ref<EnterpriseStorageBackend[]>([]), ready = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const name = ref(''), root = ref(''), editor = ref(false)
function openCreate() { if (!ready.value || busy.value) return; name.value = ''; root.value = ''; editor.value = true }
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
function invalidate() { editor.value = false; epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; ready.value = false; loading.value = false; busy.value = false; error.value = ''; name.value = ''; root.value = '' }
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
async function add() {
  if (!canManage.value || !ready.value || busy.value || !name.value.trim() || !root.value.trim()) return
  const current = epoch, scope = tenant.value
  busy.value = true; error.value = ''
  try {
    const result = await createEnterpriseStorageBackend(scope, name.value.trim(), root.value.trim())
    if (current !== epoch || !canManage.value) return
    rows.value = [...rows.value, result]; name.value = ''; root.value = ''; editor.value = false; MessagePlugin.success(t('adminStorage.created'))
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
  <section class="storage-backend-settings">
    <header class="section-header"><div><h2>{{ t('settings.storage.title') }}</h2><p>{{ t('adminStorage.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminStorage.scopeHint')" /><t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading" class="backend-list-loading"><div v-if="ready" class="backend-grid">
        <article v-for="row in rows" :key="row.id" class="backend-card" :class="`backend-card--${row.provider}`">
          <span class="backend-card__badge" :class="badgeClass(row.provider)" :style="badgeStyle(row.provider)" :aria-label="row.provider"><img v-if="resolveLogo(row.provider)?.mode === 'color'" :src="resolveLogo(row.provider)!.url" :alt="row.provider" class="backend-card__badge-img" /><template v-else-if="!resolveLogo(row.provider)">{{ row.provider.charAt(0).toUpperCase() }}</template></span>
          <div class="backend-card__body"><div class="backend-card__header"><h3 class="backend-card__title">{{ row.name }}</h3>
            <t-dropdown :options="[{ content: t('adminStorage.test'), value: 'test' }, ...(!row.builtin ? [{ content: t('adminStorage.delete'), value: 'delete', theme: 'error' as const }] : [])]" trigger="click" placement="bottom-right" @click="(option: { value?: unknown }) => option.value === 'delete' ? remove(row) : test(row)">
              <t-button class="backend-card__action-btn" variant="text" shape="square" :disabled="busy" :aria-label="`${row.name} · ${t('adminStorage.actions')}`"><t-icon name="ellipsis" /></t-button>
            </t-dropdown>
          </div><p class="backend-card__subtitle">{{ row.provider.toUpperCase() }}<span class="backend-card__sep">·</span>{{ t(row.builtin ? 'adminStorage.builtin' : 'adminStorage.custom') }}</p></div>
        </article>
        <button type="button" class="backend-card backend-card--add" :disabled="busy" @click="openCreate"><span class="backend-card--add__icon"><t-icon name="add" /></span><span class="backend-card--add__label">{{ t('adminStorage.add') }}</span></button>
      </div></t-loading>
    </template>
    <SettingDrawer v-model:visible="editor" :title="t('adminStorage.addTitle')" icon="cloud" :confirm-loading="busy" :confirm-disabled="!ready || busy || !name.trim() || !root.trim()" :cancel-disabled="busy" @confirm="add" @cancel="editor = false">
      <t-alert v-if="error" theme="error" :message="error" />
      <t-form layout="vertical" :disabled="busy" @submit="add"><t-form-item :label="t('adminStorage.name')"><t-input v-model="name" :maxlength="160" /></t-form-item><t-form-item :label="t('adminStorage.root')"><t-input v-model="root" :placeholder="t('adminStorage.rootPlaceholder')" /></t-form-item></t-form>
    </SettingDrawer>
  </section>
</template>
<style scoped lang="less">
@import './StoragePage.reference.less';
</style>
