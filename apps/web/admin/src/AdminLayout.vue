<script setup lang="ts">
/** 管理端外壳：企业切换、服务端权限导航、独立业务路由。 */
import { computed, ref, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { logout } from '@nexus-web/core/api/auth'
import { useAdminContext } from './stores/context'
// 管理端仅复用公共契约，不引入工作台的会话、邀请和资源状态。
const collapsed = ref(false), accountOpen = ref(false)
let narrow = false
const accountRoot = ref<HTMLElement | null>(null), accountButton = ref<HTMLButtonElement | null>(null)
const preferenceKey = 'nexus.admin.sidebar.collapsed'
const userName = computed(() => auth.user?.username || auth.user?.email || '')
const tenantName = computed(() => auth.currentTenantName || t('adminConsole.unnamedEnterprise'))
/** 本地偏好不可用时仍允许折叠，且不改变工作台的侧栏设置。 */
function toggleSidebar() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem(preferenceKey, String(collapsed.value)) } catch { /* 禁用存储时保留内存状态。 */ }
}
function closeAccount(restoreFocus = false) {
  accountOpen.value = false
  if (restoreFocus) void nextTick(() => accountButton.value?.focus())
}
function onPointerDown(event: PointerEvent) {
  if (event.target instanceof Node && !accountRoot.value?.contains(event.target)) closeAccount()
}
function onKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape' && accountOpen.value) { event.preventDefault(); closeAccount(true) }
}
/** 首次进入手机宽度时收起侧栏；不覆写用户的桌面偏好，手机内仍可手动展开。 */
function onResize() {
  const next = window.innerWidth <= 600
  if (next && !narrow) { collapsed.value = true; closeAccount() }
  narrow = next
}
onMounted(() => {
  try { collapsed.value = localStorage.getItem(preferenceKey) === 'true' } catch { /* 使用默认展开态。 */ }
  onResize()
  window.addEventListener('resize', onResize)
  window.addEventListener('pointerdown', onPointerDown)
  window.addEventListener('keydown', onKeyDown)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('pointerdown', onPointerDown)
  window.removeEventListener('keydown', onKeyDown)
})
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
  closeAccount(true)
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
  <div class="admin-shell" :class="{ 'is-collapsed': collapsed }">
    <aside class="admin-sidebar" :aria-label="t('adminConsole.title')">
      <header class="sidebar-header">
        <span v-if="!collapsed" class="logo-wordmark">Nexus</span>
        <button type="button" class="sidebar-toggle" :aria-label="t(collapsed ? 'menu.expandSidebar' : 'menu.collapseSidebar')" :title="t(collapsed ? 'menu.expandSidebar' : 'menu.collapseSidebar')" :aria-expanded="!collapsed" aria-controls="admin-navigation" @click="toggleSidebar">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><rect x="1.5" y="1.5" width="17" height="17" rx="3" stroke="currentColor" stroke-width="1.5"/><path d="M7.5 1.5v17M4 7.5v5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </header>
      <nav id="admin-navigation" class="sidebar-nav" :aria-label="t('adminConsole.title')">
        <template v-if="auth.currentEntries.includes('admin')">
          <RouterLink v-if="auth.currentTenantRole === 'owner'" class="nav-item" to="/enterprise" active-class="active" :aria-label="t('adminEnterprise.title')" :title="collapsed ? t('adminEnterprise.title') : undefined"><t-icon name="info-circle" class="nav-icon" /><span v-if="!collapsed">{{ t('adminEnterprise.title') }}</span></RouterLink>
          <RouterLink class="nav-item" to="/" exact-active-class="active" :aria-label="t('adminConsole.overview')" :title="collapsed ? t('adminConsole.overview') : undefined"><t-icon name="home" class="nav-icon" /><span v-if="!collapsed">{{ t('adminConsole.overview') }}</span></RouterLink>
          <RouterLink v-if="context.can('org:manage')" class="nav-item" to="/organization" active-class="active" :aria-label="t('adminOrganization.title')" :title="collapsed ? t('adminOrganization.title') : undefined"><t-icon name="view-organization" class="nav-icon" /><span v-if="!collapsed">{{ t('adminOrganization.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('org:manage')" class="nav-item" to="/wecom" active-class="active" :aria-label="t('adminWecom.title')" :title="collapsed ? t('adminWecom.title') : undefined"><t-icon name="link" class="nav-icon" /><span v-if="!collapsed">{{ t('adminWecom.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('members:manage')" class="nav-item" to="/members" active-class="active" :aria-label="t('adminMembers.title')" :title="collapsed ? t('adminMembers.title') : undefined"><t-icon name="usergroup" class="nav-icon" /><span v-if="!collapsed">{{ t('adminMembers.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('roles:manage')" class="nav-item" to="/roles" active-class="active" :aria-label="t('adminRoles.title')" :title="collapsed ? t('adminRoles.title') : undefined"><t-icon name="user-safety" class="nav-icon" /><span v-if="!collapsed">{{ t('adminRoles.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('models:manage')" class="nav-item" to="/models" active-class="active" :aria-label="t('adminModels.title')" :title="collapsed ? t('adminModels.title') : undefined"><t-icon name="control-platform" class="nav-icon" /><span v-if="!collapsed">{{ t('adminModels.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('tools:manage')" class="nav-item" to="/mcp-endpoints" active-class="active" :aria-label="t('connectionUi.endpoints')" :title="collapsed ? t('connectionUi.endpoints') : undefined"><t-icon name="link" class="nav-icon" /><span v-if="!collapsed">{{ t('connectionUi.endpoints') }}</span></RouterLink>
          <RouterLink v-if="context.can('tools:manage')" class="nav-item" to="/mcp-services" active-class="active" :aria-label="t('mcpSettings.title')" :title="collapsed ? t('mcpSettings.title') : undefined"><t-icon name="tools" class="nav-icon" /><span v-if="!collapsed">{{ t('mcpSettings.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('enterprise_kbs:manage')" class="nav-item" to="/knowledge" active-class="active" :aria-label="t('adminKnowledge.title')" :title="collapsed ? t('adminKnowledge.title') : undefined"><t-icon name="folder" class="nav-icon" /><span v-if="!collapsed">{{ t('adminKnowledge.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('enterprise_kbs:manage')" class="nav-item" to="/storage" active-class="active" :aria-label="t('adminStorage.title')" :title="collapsed ? t('adminStorage.title') : undefined"><t-icon name="folder-open" class="nav-icon" /><span v-if="!collapsed">{{ t('adminStorage.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('enterprise_kbs:manage')" class="nav-item" to="/vector-stores" active-class="active" :aria-label="t('adminVector.title')" :title="collapsed ? t('adminVector.title') : undefined"><t-icon name="database" class="nav-icon" /><span v-if="!collapsed">{{ t('adminVector.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('enterprise_kbs:manage')" class="nav-item" to="/graph-stores" active-class="active" :aria-label="t('adminGraph.title')" :title="collapsed ? t('adminGraph.title') : undefined"><t-icon name="chart-bubble" class="nav-icon" /><span v-if="!collapsed">{{ t('adminGraph.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('enterprise_agents:manage')" class="nav-item" to="/agents" active-class="active" :aria-label="t('adminAgents.title')" :title="collapsed ? t('adminAgents.title') : undefined"><t-icon name="app" class="nav-icon" /><span v-if="!collapsed">{{ t('adminAgents.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('enterprise_agents:manage')" class="nav-item" to="/channels" active-class="active" :aria-label="t('adminChannels.title')" :title="collapsed ? t('adminChannels.title') : undefined"><t-icon name="chat" class="nav-icon" /><span v-if="!collapsed">{{ t('adminChannels.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('audit:read')" class="nav-item" to="/audit" active-class="active" :aria-label="t('adminAudit.title')" :title="collapsed ? t('adminAudit.title') : undefined"><t-icon name="file-search" class="nav-icon" /><span v-if="!collapsed">{{ t('adminAudit.title') }}</span></RouterLink>
          <RouterLink v-if="context.can('policy:manage')" class="nav-item" to="/policy" active-class="active" :aria-label="t('adminConsole.policy')" :title="collapsed ? t('adminConsole.policy') : undefined"><t-icon name="setting" class="nav-icon" /><span v-if="!collapsed">{{ t('adminConsole.policy') }}</span></RouterLink>
        </template>
      </nav>
      <div ref="accountRoot" class="account-root" @focusout="(event) => { if (event.relatedTarget && !accountRoot?.contains(event.relatedTarget as Node)) closeAccount() }">
        <button ref="accountButton" type="button" class="account-button" :aria-label="[tenantName, userName].filter(Boolean).join(' · ')" :aria-expanded="accountOpen" aria-controls="admin-account-panel" @click="accountOpen = !accountOpen">
          <span class="user-avatar"><img v-if="auth.user?.avatar" :src="auth.user.avatar" alt="" /><span v-else>{{ userName.slice(0, 1).toUpperCase() || 'N' }}</span></span>
          <span v-if="!collapsed" class="account-identity"><strong>{{ tenantName }}</strong><span>{{ userName }}</span></span>
          <t-icon v-if="!collapsed" name="chevron-up" />
        </button>
        <section v-if="accountOpen" id="admin-account-panel" class="account-panel" :aria-label="t('adminConsole.enterprise')">
          <div class="account-summary"><strong>{{ userName }}</strong><span>{{ auth.user?.email }}</span></div>
          <label for="admin-tenant">{{ t('adminConsole.enterprise') }}</label>
          <t-select :popup-props="{ attach: '#admin-account-panel' }" :input-props="{ id: 'admin-tenant', 'aria-label': t('adminConsole.enterprise') }" :value="String(auth.effectiveTenantId || '')" :options="choices" :disabled="switching || context.loading" @change="switchTenant" />
          <t-button block variant="text" theme="default" :disabled="switching" @click="signOut">{{ t('adminConsole.logout') }}</t-button>
        </section>
      </div>
    </aside>
    <div class="admin-main">
    <main class="admin-content-wrapper" :class="{ 'admin-content-wrapper--resource-list': $route.path === '/members' }">
      <t-alert v-if="error" theme="error" :message="error" />
      <section v-if="!auth.currentEntries.includes('admin')" class="role-denied"><t-icon name="lock-on" size="48px" /><h2>{{ t('adminConsole.denied') }}</h2><p>{{ t('adminConsole.deniedHint') }}</p></section>
      <t-alert v-else-if="context.failed" theme="error" :message="t('adminConsole.permissionFailed')"><template #operation><t-button variant="text" @click="refresh">{{ t('connectionUi.refresh') }}</t-button></template></t-alert>
      <t-loading v-else :loading="context.loading || switching"><RouterView v-if="context.ready && !switching" /></t-loading>
    </main>
    </div>
  </div>
</template>
<style scoped>
/* 尺寸与视觉栅格沿用 workspace：260px / 48px，18px 图标与 8px 间隔。 */
.admin-shell { display: flex; height: 100%; min-height: 0; overflow: hidden; }
.admin-sidebar { width: 260px; flex-shrink: 0; display: flex; flex-direction: column; padding: 8px 4px 6px; background: var(--td-bg-color-sidebar); border-right: 1px solid var(--td-component-stroke); position: relative; }
.sidebar-header { display: flex; align-items: center; justify-content: space-between; height: 39px; margin-bottom: 4px; padding: 0 2px 0 10px; flex-shrink: 0; }
.logo-wordmark { font-size: 24px; font-weight: 700; letter-spacing: -.8px; }
.sidebar-toggle { width: 32px; height: 32px; display: grid; place-items: center; color: var(--td-text-color-secondary); }
button { font: inherit; border: 0; background: transparent; cursor: pointer; border-radius: var(--app-radius-xs); }
button:hover, .nav-item:hover { background: var(--td-bg-color-container-hover); }
button:focus-visible, .nav-item:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.sidebar-nav { flex: 1; min-height: 0; overflow-y: auto; }
.nav-item { display: flex; align-items: center; gap: 8px; min-height: 34px; padding: 6px 8px 6px 10px; margin-bottom: 6px; color: var(--td-text-color-primary); text-decoration: none; border-radius: var(--app-radius-xs); }
.nav-item.active { background: var(--td-bg-color-secondarycontainer); color: var(--td-brand-color); }
.nav-icon { font-size: 18px; flex-shrink: 0; }
.account-root { position: relative; flex-shrink: 0; }
.account-button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 10px 8px; text-align: left; color: var(--td-text-color-primary); }
.user-avatar { width: 28px; height: 28px; flex-shrink: 0; display: grid; place-items: center; border-radius: 50%; background: var(--td-bg-color-secondarycontainer); color: var(--td-brand-color); overflow: hidden; }
.user-avatar img { width: 100%; height: 100%; object-fit: cover; }
.account-identity { display: flex; flex-direction: column; flex: 1; min-width: 0; gap: 3px; }
.account-identity strong, .account-identity > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-identity strong { font-size: var(--app-text-sm); font-weight: 500; }
.account-identity > span, .account-summary span { font-size: var(--app-text-xs); color: var(--td-text-color-secondary); }
.account-panel { position: absolute; bottom: calc(100% + 8px); left: 4px; width: min(280px, calc(100vw - 24px)); z-index: 100; padding: 16px; display: grid; gap: 12px; background: var(--td-bg-color-container); border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); box-shadow: var(--td-shadow-2); }
.account-summary { display: grid; gap: 4px; overflow-wrap: anywhere; }
.account-panel :deep(.t-select__wrap) { min-width: 0; width: 100%; }
.admin-main { flex: 1; min-width: 0; min-height: 0; display: flex; overflow-y: auto; background: var(--td-bg-color-container); }
.is-collapsed .admin-sidebar { width: 48px; padding: 8px 0; }
.is-collapsed .sidebar-header { padding: 0; justify-content: center; }
.is-collapsed .nav-item { width: 32px; padding: 0; justify-content: center; margin: 0 auto 6px; }
.is-collapsed .account-button { justify-content: center; padding: 10px 0; }
@media (max-width: 720px) { .admin-sidebar { width: 220px; } }
.admin-content-wrapper { width: 100%; padding: 40px 48px; }
.admin-content-wrapper--resource-list { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; padding: 20px 28px 0; }
.admin-content-wrapper--resource-list > :deep(.t-loading__parent) { flex: 1; min-height: 0; }
.role-denied { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 240px; padding: 64px 24px; text-align: center; }
.role-denied > .t-icon { color: var(--td-text-color-placeholder); }
.role-denied h2 { margin: 0; font-size: var(--app-text-xl); }
.role-denied p { color: var(--td-text-color-secondary); max-width: 360px; line-height: 1.6; }
@media (max-width: 720px) { .admin-content-wrapper { padding: 24px 16px; } .admin-content-wrapper--resource-list { padding: 16px 16px 0; } }
</style>
