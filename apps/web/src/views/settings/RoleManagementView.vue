<script setup lang="ts">
import { reactive } from 'vue'
import { useRoles } from '../../composables/useRoles'
import { agentPermissionLabels, apiLabels, menuLabels } from '../../types/roles'
import { i18n } from '../../i18n'
const roles = useRoles()
const { tenants, tenant, loading, busy, error, feedback, catalog, canManage, roles: roleRows, assignableMembers, agents,
  grantRoleId, grantAgentId, grantPermissions, agentPermissions, roleDialog, editingRoleId, roleForm, rolesOf } = roles
const menuName = (key: string) => (menuLabels[key] ? i18n.global.t(menuLabels[key]) : key)
const account = reactive({ username: '', displayName: '', password: '', role: 'member' as 'admin' | 'member' })
async function submitAccount() {
  if (busy.value) return
  try { await roles.createAccount(account.username, account.displayName, account.password, account.role) }
  finally { account.password = '' }
  if (!error.value) account.username = ''
}
const apiName = (key: string) => (apiLabels[key] ? i18n.global.t(apiLabels[key]) : key)
</script>
<template>
  <main class="role-settings" v-loading="loading" :aria-busy="loading || busy">
    <header><div><p class="eyebrow">{{ $t('common.spaceEyebrow') }}</p><h1>{{ $t('shell.titles.spaceRoles') }}</h1></div>
      <el-button :disabled="busy || loading || !tenant || !canManage" @click="roles.openRole()">{{ $t('roleSettings.newRole') }}</el-button></header>
    <p class="intro">{{ $t('roleSettings.intro') }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="error" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>
    <el-empty v-if="!loading && tenant && !canManage" :description="$t('roleSettings.noPermission')" />
    <template v-if="canManage">
      <section class="settings-section" aria-labelledby="role-list-title">
        <h2 id="role-list-title">{{ $t('roleSettings.roles') }}</h2>
        <el-empty v-if="!roleRows.length" :description="$t('roleSettings.noCustomRoles')" />
        <ul class="role-list">
          <li v-for="item in roleRows" :key="item.id">
            <div><strong>{{ item.name }}</strong>
              <p>{{ $t('roleSettings.menusLine', { list: item.menus.map(menuName).join($t('roleSettings.separator')) || $t('roleSettings.none') }) }}</p>
              <p>{{ $t('roleSettings.apisLine', { list: item.apis.map(apiName).join($t('roleSettings.separator')) || $t('roleSettings.none') }) }}</p></div>
            <el-button :disabled="busy" @click="roles.openRole(item)">{{ $t('roleSettings.editRole', { name: item.name }) }}</el-button>
          </li>
        </ul>
      </section>
      <section class="settings-section" aria-labelledby="account-title">
        <h2 id="account-title">{{ $t('roleSettings.addAccount') }}</h2>
        <p class="intro">{{ $t('roleSettings.accountIntro') }}</p>
        <form class="account-form" @submit.prevent="submitAccount">
          <label for="new-account-username">{{ $t('auth.username') }}</label>
          <el-input id="new-account-username" v-model="account.username" maxlength="64" autocomplete="off" :disabled="busy" />
          <label for="new-account-name">{{ $t('roleSettings.displayName') }}</label>
          <el-input id="new-account-name" v-model="account.displayName" maxlength="160" :disabled="busy" />
          <label for="new-account-password">{{ $t('roleSettings.initialPassword') }}</label>
          <el-input id="new-account-password" v-model="account.password" type="password" maxlength="256" show-password autocomplete="new-password" :disabled="busy" />
          <label for="new-account-role">{{ $t('roleSettings.spaceRole') }}</label>
          <el-select id="new-account-role" v-model="account.role" :disabled="busy">
            :label="$t('roleSettings.memberRole')" value="member" />
            :label="$t('roleSettings.adminRole')" value="admin" />
          </el-select>
          <el-button type="primary" native-type="submit" :disabled="busy || !account.username.trim() || account.password.length < 10">{{ $t('roleSettings.createAccount') }}</el-button>
        </form>
      </section>
      <section class="settings-section" aria-labelledby="assign-title">
        <h2 id="assign-title">{{ $t('roleSettings.memberRoles') }}</h2>
        <p class="intro">{{ $t('roleSettings.ownerAdminIntro') }}</p>
        <el-empty v-if="!assignableMembers.length" :description="$t('roleSettings.noAssignable')" />
        <ul class="assign-list">
          <li v-for="member in assignableMembers" :key="member.user_id">
            <span class="member-id">{{ $t('roleSettings.memberLabel', { id: member.user_id.slice(0, 8) }) }}</span>
            <el-select :model-value="rolesOf(member.user_id)" multiple :disabled="busy || loading" :placeholder="$t('roleSettings.unassigned')"
              :aria-label="$t('roleSettings.memberRolesAria', { id: member.user_id.slice(0, 8) })" @change="(value: string[]) => roles.setMemberRoles(member.user_id, value)">
              <el-option v-for="item in roleRows" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </li>
        </ul>
      </section>
      <section class="settings-section" aria-labelledby="grant-title">
        <h2 id="grant-title">{{ $t('roleSettings.agentPermissions') }}</h2>
        <p class="intro">{{ $t('roleSettings.grantIntro') }}</p>
        <div class="grant-form">
          <el-select v-model="grantRoleId" :placeholder="$t('roleSettings.pickRole')" :disabled="busy" :aria-label="$t('roleSettings.pickRole')">
            <el-option v-for="item in roleRows" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-select v-model="grantAgentId" :placeholder="$t('roleSettings.pickAgent')" :disabled="busy" :aria-label="$t('roleSettings.pickAgent')">
            <el-option v-for="item in agents" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-checkbox-group v-model="grantPermissions" :disabled="busy || !grantRoleId || !grantAgentId" :aria-label="$t('roleSettings.agentPermissions')">
            <el-checkbox v-for="permission in agentPermissions" :key="permission" :value="permission">{{ $t(agentPermissionLabels[permission]) }}</el-checkbox>
          </el-checkbox-group>
          <el-button :disabled="busy || !grantRoleId || !grantAgentId" @click="roles.saveGrant">{{ $t('roleSettings.saveGrant') }}</el-button>
        </div>
      </section>
    </template>
    <el-dialog v-model="roleDialog" :title="editingRoleId ? $t('roleSettings.editTitle') : $t('roleSettings.newRole')" width="520px">
      <el-form label-position="top" @submit.prevent="roles.saveRole">
        <el-form-item :label="$t('roleSettings.roleName')" required>
          <el-input v-model="roleForm.name" maxlength="64" :disabled="!!editingRoleId" show-word-limit />
        </el-form-item>
        <el-form-item :label="$t('roleSettings.menus')">
          <el-checkbox-group v-model="roleForm.menus">
            <el-checkbox v-for="menu in catalog.menus" :key="menu" :value="menu">{{ menuName(menu) }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item :label="$t('roleSettings.apis')">
          <el-checkbox-group v-model="roleForm.apis" class="api-grants">
            <el-checkbox v-for="api in catalog.apis" :key="api" :value="api">{{ apiName(api) }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-button type="primary" native-type="submit" :disabled="busy || (!editingRoleId && !roleForm.name.trim())">{{ $t('roleSettings.saveRole') }}</el-button>
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
