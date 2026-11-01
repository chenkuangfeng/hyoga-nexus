<script setup lang="ts">
import { reactive } from 'vue'
import { useRoles } from '../../composables/useRoles'
import { agentPermissionLabels, apiLabels, menuLabels } from '../../types/roles'
const roles = useRoles()
const { tenants, tenant, loading, busy, error, feedback, catalog, canManage, roles: roleRows, assignableMembers, agents,
  grantRoleId, grantAgentId, grantPermissions, agentPermissions, roleDialog, editingRoleId, roleForm, rolesOf } = roles
const menuName = (key: string) => menuLabels[key] || key
const account = reactive({ username: '', displayName: '', password: '', role: 'member' as 'admin' | 'member' })
async function submitAccount() {
  if (busy.value) return
  try { await roles.createAccount(account.username, account.displayName, account.password, account.role) }
  finally { account.password = '' }
  if (!error.value) account.username = ''
}
const apiName = (key: string) => apiLabels[key] || key
</script>
<template>
  <main class="role-settings" v-loading="loading" :aria-busy="loading || busy">
    <header><div><p class="eyebrow">HYOGA NEXUS / 空间管理</p><h1>角色与权限</h1></div>
      <el-button :disabled="busy || loading || !tenant || !canManage" @click="roles.openRole()">新建角色</el-button></header>
    <p class="intro">角色决定成员可以访问的菜单、后台接口和可用的智能体。成员可同时拥有多个角色，权限取并集。空间的 owner 与 admin 始终拥有全部权限。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="error" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>
    <el-empty v-if="!loading && tenant && !canManage" description="你没有管理角色的权限，请联系空间管理员。" />
    <template v-if="canManage">
      <section class="settings-section" aria-labelledby="role-list-title">
        <h2 id="role-list-title">角色</h2>
        <el-empty v-if="!roleRows.length" description="尚未创建自定义角色" />
        <ul class="role-list">
          <li v-for="item in roleRows" :key="item.id">
            <div><strong>{{ item.name }}</strong>
              <p>菜单：{{ item.menus.map(menuName).join('、') || '无' }}</p>
              <p>接口：{{ item.apis.map(apiName).join('、') || '无' }}</p></div>
            <el-button :disabled="busy" @click="roles.openRole(item)">编辑 {{ item.name }}</el-button>
          </li>
        </ul>
      </section>
      <section class="settings-section" aria-labelledby="account-title">
        <h2 id="account-title">添加账号</h2>
        <p class="intro">账号由管理员创建并加入当前空间。初始密码至少 10 个字符，成员首次登录后应立即修改。</p>
        <form class="account-form" @submit.prevent="submitAccount">
          <label for="new-account-username">账号</label>
          <el-input id="new-account-username" v-model="account.username" maxlength="64" autocomplete="off" :disabled="busy" />
          <label for="new-account-name">显示名称</label>
          <el-input id="new-account-name" v-model="account.displayName" maxlength="160" :disabled="busy" />
          <label for="new-account-password">初始密码</label>
          <el-input id="new-account-password" v-model="account.password" type="password" maxlength="256" show-password autocomplete="new-password" :disabled="busy" />
          <label for="new-account-role">空间角色</label>
          <el-select id="new-account-role" v-model="account.role" :disabled="busy">
            <el-option label="普通成员" value="member" />
            <el-option label="管理员" value="admin" />
          </el-select>
          <el-button type="primary" native-type="submit" :disabled="busy || !account.username.trim() || account.password.length < 10">创建账号</el-button>
        </form>
      </section>
      <section class="settings-section" aria-labelledby="assign-title">
        <h2 id="assign-title">成员角色</h2>
        <p class="intro">owner 与 admin 已拥有全部权限，不需要分配角色。</p>
        <el-empty v-if="!assignableMembers.length" description="暂无可分配角色的普通成员" />
        <ul class="assign-list">
          <li v-for="member in assignableMembers" :key="member.user_id">
            <span class="member-id">成员 {{ member.user_id.slice(0, 8) }}</span>
            <el-select :model-value="rolesOf(member.user_id)" multiple :disabled="busy || loading" placeholder="未分配角色"
              :aria-label="`成员 ${member.user_id.slice(0, 8)} 的角色`" @change="(value: string[]) => roles.setMemberRoles(member.user_id, value)">
              <el-option v-for="item in roleRows" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </li>
        </ul>
      </section>
      <section class="settings-section" aria-labelledby="grant-title">
        <h2 id="grant-title">智能体权限</h2>
        <p class="intro">为角色设置对某个智能体的权限。授予者只能授予自己拥有的权限。</p>
        <div class="grant-form">
          <el-select v-model="grantRoleId" placeholder="选择角色" :disabled="busy" aria-label="选择角色">
            <el-option v-for="item in roleRows" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-select v-model="grantAgentId" placeholder="选择智能体" :disabled="busy" aria-label="选择智能体">
            <el-option v-for="item in agents" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-checkbox-group v-model="grantPermissions" :disabled="busy || !grantRoleId || !grantAgentId" aria-label="智能体权限">
            <el-checkbox v-for="permission in agentPermissions" :key="permission" :value="permission">{{ agentPermissionLabels[permission] }}</el-checkbox>
          </el-checkbox-group>
          <el-button :disabled="busy || !grantRoleId || !grantAgentId" @click="roles.saveGrant">保存智能体权限</el-button>
        </div>
      </section>
    </template>
    <el-dialog v-model="roleDialog" :title="editingRoleId ? '编辑角色' : '新建角色'" width="520px">
      <el-form label-position="top" @submit.prevent="roles.saveRole">
        <el-form-item label="角色名称" required>
          <el-input v-model="roleForm.name" maxlength="64" :disabled="!!editingRoleId" show-word-limit />
        </el-form-item>
        <el-form-item label="菜单">
          <el-checkbox-group v-model="roleForm.menus">
            <el-checkbox v-for="menu in catalog.menus" :key="menu" :value="menu">{{ menuName(menu) }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="后台接口权限">
          <el-checkbox-group v-model="roleForm.apis" class="api-grants">
            <el-checkbox v-for="api in catalog.apis" :key="api" :value="api">{{ apiName(api) }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-button type="primary" native-type="submit" :disabled="busy || (!editingRoleId && !roleForm.name.trim())">保存角色</el-button>
      </el-form>
    </el-dialog>
  </main>
</template>
<style scoped>
.role-settings { max-width: 960px; margin: 0 auto; padding: 24px; }
.role-list, .assign-list { list-style: none; padding: 0; margin: 0; }
.role-list li, .assign-list li { display: flex; gap: 16px; align-items: center; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.role-list p { margin: 4px 0; color: var(--el-text-color-secondary); font-size: 14px; }
.grant-form { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.api-grants { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 12px; }
.account-form { display: grid; gap: 8px; max-width: 420px; }
.account-form label { font-size: 14px; color: var(--el-text-color-regular); }
.member-id { font-family: var(--el-font-family-mono, monospace); }
@media (max-width: 640px) { .api-grants { grid-template-columns: 1fr; } .role-list li, .assign-list li { flex-direction: column; align-items: flex-start; } }
</style>
