<script setup lang="ts">
/** 管理端桌面外壳：企业切换、服务端权限导航、独立业务路由。 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { logout } from '@nexus-web/core/api/auth'
import { useAdminContext } from './stores/context'
const props = withDefaults(defineProps<{ workspaceHref?: string }>(), { workspaceHref: '/' })
const auth = useAuthStore(), context = useAdminContext(), router = useRouter()
const { t } = useI18n()
const switching = ref(false), error = ref('')
const choices = computed(() => auth.memberships.map(row => ({ label: row.tenant_name || t('adminConsole.unnamedEnterprise'), value: String(row.tenant_id) })))
async function refresh(): Promise<boolean> {
  context.invalidate(); error.value = ''
  if (!await auth.refreshFromAuthMe()) { await router.replace('/login'); return false }
  await context.load()
  return true
}
async function switchTenant(value: unknown) {
  if (switching.value || typeof value !== 'string' || value === String(auth.effectiveTenantId || '')) return
  const membership = auth.memberships.find(row => String(row.tenant_id) === value)
  if (!membership) return
  switching.value = true; error.value = ''
  auth.setSelectedTenant(value, membership.tenant_name)
  try { if (await refresh()) await router.replace('/') }
  catch { error.value = t('adminConsole.failed') }
  finally { switching.value = false }
}
async function signOut() {
  if (switching.value) return
  switching.value = true; context.invalidate()
  try { await logout() }
  catch { /* 本地身份仍须清除，避免网络故障后留存管理页面。 */ }
  finally { auth.logout(); context.invalidate(); await router.replace('/login'); switching.value = false }
}
</script>
<template>
  <div class="admin-shell">
    <header class="admin-header">
      <strong>{{ t('adminConsole.title') }}</strong>
      <div class="admin-account">
        <label for="admin-tenant">{{ t('adminConsole.enterprise') }}</label>
        <t-select :input-props="{ id: 'admin-tenant', 'aria-label': t('adminConsole.enterprise') }" :value="String(auth.effectiveTenantId || '')" :options="choices" :disabled="switching || context.loading" @change="switchTenant" />
        <a :href="props.workspaceHref">{{ t('navigationErrors.backWorkspace') }}</a>
        <t-button variant="text" :disabled="switching" @click="signOut">{{ t('adminConsole.logout') }}</t-button>
      </div>
    </header>
    <div class="admin-body">
      <aside v-if="auth.currentEntries.includes('admin')" class="admin-sidebar">
        <nav :aria-label="t('adminConsole.navigation')">
          <RouterLink to="/" exact-active-class="is-active">{{ t('adminConsole.overview') }}</RouterLink>
          <RouterLink v-if="context.can('policy:manage')" to="/policy" active-class="is-active">{{ t('adminConsole.policy') }}</RouterLink>
        </nav>
      </aside>
      <main class="admin-main">
        <t-alert v-if="error" theme="error" :message="error" />
        <section v-if="!auth.currentEntries.includes('admin')"><h1>{{ t('adminConsole.denied') }}</h1><p>{{ t('adminConsole.deniedHint') }}</p></section>
        <t-alert v-else-if="context.failed" theme="error" :message="t('adminConsole.permissionFailed')"><template #operation><t-button variant="text" @click="refresh">{{ t('connectionUi.refresh') }}</t-button></template></t-alert>
        <t-loading v-else :loading="context.loading || switching"><RouterView v-if="context.ready && !switching" /></t-loading>
      </main>
    </div>
  </div>
</template>
<style scoped>
.admin-shell { min-height: 100vh; }
.admin-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 16px 24px; background: var(--td-bg-color-container); border-bottom: 1px solid var(--td-component-border); }
.admin-account { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.admin-account :deep(.t-select__wrap) { width: 240px; }
.admin-account a { color: var(--td-brand-color); }
.admin-body { display: flex; min-height: calc(100vh - 72px); }
.admin-sidebar { width: 220px; flex-shrink: 0; background: var(--td-bg-color-container); border-right: 1px solid var(--td-component-border); padding: 24px 12px; }
.admin-sidebar nav { display: grid; gap: 8px; }
.admin-sidebar a { display: block; padding: 12px 16px; border-radius: var(--td-radius-default); color: var(--td-text-color-primary); text-decoration: none; }
.admin-sidebar a.is-active { color: var(--td-brand-color); background: var(--td-brand-color-light); }
.admin-main { flex: 1; min-width: 0; padding: 32px; }
a:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
@media(max-width: 900px) { .admin-header { align-items: flex-start; flex-direction: column; } .admin-sidebar { width: 160px; } .admin-main { padding: 16px; } }
</style>
