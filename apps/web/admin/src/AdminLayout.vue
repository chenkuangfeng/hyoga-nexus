<script setup lang="ts">
/** 管理端桌面外壳：企业切换、服务端权限导航、独立业务路由。 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { logout } from '@nexus-web/core/api/auth'
import { useAdminContext } from './stores/context'
import SettingsModalShell from '@nexus-web/core/components/SettingsModalShell.vue'
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
function backToWorkspace() { window.location.assign(props.workspaceHref) }
async function signOut() {
  if (switching.value) return
  switching.value = true; context.invalidate()
  try { await logout() }
  catch { /* 本地身份仍须清除，避免网络故障后留存管理页面。 */ }
  finally { auth.logout(); context.invalidate(); await router.replace('/login'); switching.value = false }
}
</script>
<template>
  <SettingsModalShell :visible="true" :title="t('adminConsole.title')" full-page @close="backToWorkspace">
    <template #sidebar-header-extra>
      <div class="admin-account">
        <label for="admin-tenant">{{ t('adminConsole.enterprise') }}</label>
        <t-select :input-props="{ id: 'admin-tenant', 'aria-label': t('adminConsole.enterprise') }" :value="String(auth.effectiveTenantId || '')" :options="choices" :disabled="switching || context.loading" @change="switchTenant" />
        <t-button variant="text" theme="default" size="small" :disabled="switching" @click="signOut">{{ t('adminConsole.logout') }}</t-button>
      </div>
    </template>
    <template #nav>
      <template v-if="auth.currentEntries.includes('admin')">
        <div class="nav-group-title">{{ t('adminConsole.enterprise') }}</div>
        <RouterLink class="nav-item" to="/" exact-active-class="active"><t-icon name="home" class="nav-icon" /><span class="nav-label">{{ t('adminConsole.overview') }}</span></RouterLink>
        <RouterLink v-if="context.can('org:manage')" class="nav-item" to="/organization" active-class="active"><t-icon name="view-organization" class="nav-icon" /><span class="nav-label">{{ t('adminOrganization.title') }}</span></RouterLink>
        <RouterLink v-if="context.can('members:manage')" class="nav-item" to="/members" active-class="active"><t-icon name="usergroup" class="nav-icon" /><span class="nav-label">{{ t('adminMembers.title') }}</span></RouterLink>
        <RouterLink v-if="context.can('policy:manage')" class="nav-item" to="/policy" active-class="active"><t-icon name="setting" class="nav-icon" /><span class="nav-label">{{ t('adminConsole.policy') }}</span></RouterLink>
      </template>
    </template>
    <main class="admin-content-wrapper" :class="{ 'admin-content-wrapper--resource-list': $route.path === '/members' }">
      <t-alert v-if="error" theme="error" :message="error" />
      <section v-if="!auth.currentEntries.includes('admin')" class="role-denied"><t-icon name="lock-on" size="48px" /><h2>{{ t('adminConsole.denied') }}</h2><p>{{ t('adminConsole.deniedHint') }}</p></section>
      <t-alert v-else-if="context.failed" theme="error" :message="t('adminConsole.permissionFailed')"><template #operation><t-button variant="text" @click="refresh">{{ t('connectionUi.refresh') }}</t-button></template></t-alert>
      <t-loading v-else :loading="context.loading || switching"><RouterView v-if="context.ready && !switching" /></t-loading>
    </main>
  </SettingsModalShell>
</template>
<style scoped>
.admin-account { display: grid; gap: 8px; margin-top: 12px; }
.admin-account label { color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
.admin-account :deep(.t-select__wrap) { width: 100%; min-width: 0; }
.admin-account .t-button { justify-self: start; }
.nav-item { text-decoration: none; }
.nav-item:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.admin-content-wrapper { width: 100%; padding: 40px 48px; }
.admin-content-wrapper--resource-list { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; padding: 20px 28px 0; }
.admin-content-wrapper--resource-list > :deep(.t-loading__parent) { flex: 1; min-height: 0; }
.role-denied { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 240px; padding: 64px 24px; text-align: center; }
.role-denied > .t-icon { color: var(--td-text-color-placeholder); }
.role-denied h2 { margin: 0; font-size: var(--app-text-xl); }
.role-denied p { color: var(--td-text-color-secondary); max-width: 360px; line-height: 1.6; }
@media (max-width: 720px) { .admin-content-wrapper { padding: 24px 16px; } .admin-content-wrapper--resource-list { padding: 16px 16px 0; } }
</style>
