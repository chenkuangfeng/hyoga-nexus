<script setup lang="ts">
/**
 * Left sidebar: logo, space selector, grouped navigation, the current space's conversations and the
 * signed-in user. Collapses to an icon column on medium screens and becomes a drawer on small ones.
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { navigation } from '../router/navigation'
import { setTenant, workspace } from '../stores/workspace'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ toggle: []; navigate: []; signOut: [] }>()
const route = useRoute()
const router = useRouter()

const visibleGroups = computed(() => navigation.filter(group => !group.requiresAdmin || workspace.user?.is_platform_admin))
const activeSession = computed(() => (route.name === 'chat' ? String(route.params.sessionId || '') : ''))

function go(path: string) {
  void router.push(path)
  emit('navigate')
}
function openSession(id: string) { void router.push(`/chat/${id}`); emit('navigate') }
function isActive(path: string) { return route.path === path || route.path.startsWith(path + '/') }
</script>

<template>
  <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': collapsed }" aria-label="工作台导航">
    <div class="sidebar-head">
      <span class="brand" aria-hidden="true">HN</span>
      <span v-if="!collapsed" class="brand-name">Hyoga Nexus</span>
      <button type="button" class="icon-button" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" :aria-expanded="!collapsed" @click="emit('toggle')">
        <span aria-hidden="true">{{ collapsed ? '›' : '‹' }}</span>
      </button>
    </div>

    <div v-if="!collapsed" class="space-picker">
      <label for="space-select">工作空间</label>
      <el-select id="space-select" :model-value="workspace.tenantId" :disabled="!workspace.tenants.length" placeholder="选择空间" @change="(value: string) => setTenant(value)">
        <el-option v-for="item in workspace.tenants" :key="item.id" :value="item.id" :label="item.via_organization ? `${item.name}（组织）` : item.name" />
      </el-select>
    </div>

    <nav class="sidebar-nav" aria-label="主导航">
      <section v-for="group in visibleGroups" :key="group.title" class="nav-group">
        <h2 v-if="!collapsed" class="nav-title">{{ group.title }}</h2>
        <ul>
          <li v-for="item in group.items" :key="item.path">
            <button type="button" class="nav-item" :class="{ active: isActive(item.path) }" :aria-current="isActive(item.path) ? 'page' : undefined" :title="item.label" @click="go(item.path)">
              <span class="nav-glyph" aria-hidden="true">{{ item.label.slice(0, 1) }}</span>
              <span v-if="!collapsed">{{ item.label }}</span>
            </button>
          </li>
        </ul>

        <!-- The current space's conversations, shown under the chat entry. -->
        <div v-if="group.title === '工作台' && !collapsed" class="session-section">
          <p class="nav-title">会话</p>
          <p v-if="workspace.sessionsError" class="session-error" role="alert">{{ workspace.sessionsError }}</p>
          <p v-else-if="!workspace.sessions.length" class="muted">暂无会话</p>
          <ul v-else aria-label="会话列表">
            <li v-for="session in workspace.sessions" :key="session.id">
              <button type="button" class="session-item" :class="{ selected: session.id === activeSession }" :aria-current="session.id === activeSession ? 'page' : undefined" :title="session.title" @click="openSession(session.id)">
                {{ session.title || '未命名会话' }}
              </button>
            </li>
          </ul>
        </div>
      </section>
    </nav>

    <div class="sidebar-user">
      <div v-if="!collapsed" class="user-text">
        <strong>{{ workspace.user?.display_name || '已登录用户' }}</strong>
        <span v-if="workspace.user?.is_platform_admin" class="muted">平台管理员</span>
      </div>
      <button type="button" class="link-button" :title="'退出登录'" @click="emit('signOut')">{{ collapsed ? '退' : '退出登录' }}</button>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar { position: sticky; top: 0; display: flex; flex-direction: column; gap: 12px; height: 100vh; width: 248px; padding: 12px; box-sizing: border-box; background: var(--surface); border-right: 1px solid var(--border); overflow: hidden; transition: width 0.2s ease; }
.app-sidebar--collapsed { width: 60px; }
.sidebar-head { display: flex; align-items: center; gap: 8px; min-height: 40px; }
.brand { display: inline-grid; place-items: center; width: 32px; height: 32px; border-radius: 8px; background: var(--el-color-primary); color: #fff; font-weight: 700; font-size: 13px; }
.brand-name { flex: 1; font-weight: 600; }
.icon-button { margin-left: auto; width: 32px; height: 32px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); cursor: pointer; font-size: 18px; line-height: 1; }
.space-picker { display: grid; gap: 6px; }
.space-picker label { font-size: 13px; color: var(--muted-text); }
.sidebar-nav { flex: 1; min-height: 0; overflow-y: auto; display: grid; gap: 14px; align-content: start; }
.nav-group ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.nav-title { margin: 0 0 4px; font-size: 12px; color: var(--muted-text); font-weight: 600; letter-spacing: 0.02em; }
.nav-item { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; padding: 6px 10px; border: 0; border-radius: 6px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nav-item:hover { background: var(--selected); }
.nav-item.active { background: var(--selected); color: var(--el-color-primary); font-weight: 600; }
.nav-item:focus-visible, .session-item:focus-visible, .icon-button:focus-visible, .link-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.nav-glyph { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; background: var(--selected); font-size: 12px; flex: none; }
.session-section { margin-top: 10px; }
.session-section ul { display: grid; gap: 2px; }
.session-item { width: 100%; min-height: 36px; padding: 6px 10px; border: 0; border-radius: 6px; background: transparent; font: inherit; font-size: 14px; text-align: left; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item:hover, .session-item.selected { background: var(--selected); }
.session-error { color: var(--el-color-danger); font-size: 13px; }
.sidebar-user { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 10px; border-top: 1px solid var(--border); }
.user-text { display: grid; min-width: 0; }
.link-button { border: 0; background: transparent; color: var(--el-color-primary); font: inherit; cursor: pointer; min-height: 40px; }
.muted { color: var(--muted-text); font-size: 13px; }
@media (max-width: 767px) { .app-sidebar { width: min(280px, 86vw); } }
</style>
