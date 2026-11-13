<script setup lang="ts">
/** 管理端成员与邀请列表。分页/搜索基于后端完整列表，所有操作交由作用域隔离的控制器。 */
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { copyToClipboard } from '@nexus-web/core/utils/clipboard'
import type { LinkInvitation } from '@nexus-web/core/api/enterprise-members'
import JoinRequestsPanel from './JoinRequestsPanel.vue'
import { useMemberAdministration } from './useMemberAdministration'
const props = withDefaults(defineProps<{ workspaceHref?: string }>(), { workspaceHref: '/' })
const { t, locale } = useI18n(), auth = useAuthStore()
const state = reactive(useMemberAdministration(t))
const applicationsBusy = ref(false), applicationsRefresh = ref(0)
async function refreshLists() { if (applicationsBusy.value) return; applicationsRefresh.value++; await state.load() }
const inviteRoles = computed(() => ['admin', 'contributor', 'viewer'].map(value => ({ value, label: t(`tenantMember.role.${value}`) })))
const memberColumns = computed(() => [{ colKey: 'person', title: t('adminMembers.person'), minWidth: 220 }, { colKey: 'status', title: t('adminMembers.status'), width: 100 }, { colKey: 'joined_at', title: t('adminMembers.joined'), width: 190 }, { colKey: 'actions', title: t('adminMembers.roleActions'), minWidth: 300 }])
const invitationColumns = computed(() => [{ colKey: 'person', title: t('adminMembers.invitee'), minWidth: 220 }, { colKey: 'role', title: t('adminMembers.role'), width: 120 }, { colKey: 'created_at', title: t('adminMembers.sent'), width: 190 }, { colKey: 'details', title: t('adminMembers.details'), minWidth: 240 }, { colKey: 'actions', title: t('adminMembers.operations'), width: 160 }])
const rules = computed(() => ({
  email: [{ required: true, message: t('adminMembers.emailInvalid'), type: 'error' }, { pattern: /^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$/, message: t('adminMembers.emailInvalid'), type: 'error' }],
  username: state.createAccount ? [{ required: true, message: t('adminMembers.usernameHint'), type: 'error' }, { pattern: /^[a-z0-9][a-z0-9._-]{2,63}$/i, message: t('adminMembers.usernameHint'), type: 'error' }] : [],
  password: state.createAccount ? [{ required: true, message: t('adminMembers.passwordHint'), type: 'error' }, { min: 10, max: 256, message: t('adminMembers.passwordHint'), type: 'error' }] : [],
}))
function date(value: string): string { const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString(locale.value) }
let live = true
onBeforeUnmount(() => { live = false })
async function copyLink(row: LinkInvitation) {
  if (!state.canManage || !state.invitations.some(item => item.id === row.id && item.kind === 'link' && item.invite_path === row.invite_path)) return
  const tenant = String(auth.effectiveTenantId), user = auth.user?.id
  const base = new URL(props.workspaceHref, window.location.origin)
  const value = new URL(row.invite_path, base).href
  const ok = await copyToClipboard(value)
  if (!live || tenant !== String(auth.effectiveTenantId) || user !== auth.user?.id || !state.canManage) return
  if (ok) state.success = t('adminMembers.copied'); else state.error = t('adminMembers.copyFailed')
}
</script>
<template>
  <section class="members-page">
    <header><div><h1>{{ t('adminMembers.title') }}</h1><p>{{ t('adminMembers.description') }}</p></div><div class="member-actions"><t-button variant="outline" :disabled="state.busy || applicationsBusy" :loading="state.loading" @click="refreshLists">{{ t('connectionUi.refresh') }}</t-button><t-button v-if="state.canManage" :disabled="state.busy || state.loading || applicationsBusy" @click="state.openEditor">{{ t('adminMembers.invite') }}</t-button><t-button v-if="state.canManage" variant="outline" :disabled="state.busy || state.loading || applicationsBusy" @click="state.openLink">{{ t('adminMembers.createLink') }}</t-button></div></header>
    <t-alert v-if="!state.canManage" theme="warning" :message="t('adminMembers.denied')" />
    <template v-else>
      <t-alert v-if="state.error" theme="error" :message="state.error" />
      <t-alert v-if="state.success" theme="success" :message="state.success" />
      <t-tabs v-model="state.tab">
        <t-tab-panel value="members" :label="t('adminMembers.membersCount', { count: state.members.length })">
          <div class="member-toolbar"><t-input v-model="state.search" :aria-label="t('adminMembers.search')" :placeholder="t('adminMembers.search')" clearable /></div>
          <t-alert v-if="state.membersError" theme="error" :message="state.membersError" />
          <t-table row-key="user_id" :data="state.memberRows" :columns="memberColumns" :loading="state.loading" :empty="state.search ? t('adminMembers.noMatch') : t('adminMembers.noMembers')">
            <template #person="{ row }"><strong>{{ state.memberName(row) }}</strong> <t-tag v-if="row.user_id === auth.user?.id" size="small">{{ t('common.me') }}</t-tag><p class="person-detail">{{ row.email || row.username || '—' }}</p></template>
            <template #status><t-tag theme="success">{{ t('adminMembers.active') }}</t-tag></template>
            <template #joined_at="{ row }">{{ date(row.joined_at) }}</template>
            <template #actions="{ row }"><div class="member-actions"><t-select v-if="state.canEditMember(row)" class="member-role" :value="row.role" :options="state.roleOptions(row)" :aria-label="t('adminMembers.changeRoleLabel', { name: state.memberName(row) })" :disabled="state.busy || state.loading" @change="(value: unknown) => state.changeRole(row, value)" /><span v-else>{{ t(`tenantMember.role.${row.role}`) }}</span><t-button variant="text" theme="danger" :disabled="state.busy || state.loading || !state.canRemoveMember(row)" @click="state.remove(row)">{{ t('adminMembers.remove') }}</t-button></div><small v-if="row.role === 'owner' && state.ownerCount <= 1">{{ t('adminMembers.lastOwner') }}</small></template>
          </t-table>
          <t-pagination v-if="state.filteredMembers.length > state.pageSize" v-model="state.memberPage" :page-size="state.pageSize" :total="state.filteredMembers.length" :show-page-size="false" />
        </t-tab-panel>
        <t-tab-panel value="invitations" :label="t('adminMembers.invitationsCount', { count: state.invitations.length })">
          <p>{{ t('adminMembers.invitationHint') }}</p>
          <t-alert v-if="state.invitationsError" theme="error" :message="state.invitationsError" />
          <t-table row-key="id" :data="state.invitationRows" :columns="invitationColumns" :loading="state.loading" :empty="t('adminMembers.noInvitations')">
            <template #person="{ row }"><strong>{{ state.invitationName(row) }}</strong><p v-if="row.kind === 'person'" class="person-detail">{{ row.email || '—' }}</p><t-tag v-else>{{ t('adminMembers.link') }}</t-tag></template>
            <template #role="{ row }">{{ t(`tenantMember.role.${row.role}`) }}</template>
            <template #created_at="{ row }">{{ date(row.created_at) }}</template>
            <template #details="{ row }"><template v-if="row.kind === 'link'"><p>{{ t('adminMembers.expires', { date: date(row.expires_at) }) }}</p><p>{{ t('adminMembers.acceptedCount', { count: row.accepted_count }) }}</p><t-button variant="text" :disabled="state.busy || state.loading" @click="copyLink(row)">{{ t('adminMembers.copyLink') }}</t-button></template><span v-else>{{ t('adminMembers.pending') }}</span></template>
            <template #actions="{ row }"><t-button variant="text" theme="danger" :disabled="state.busy || state.loading" @click="state.revoke(row)">{{ t('adminMembers.revoke') }}</t-button></template>
          </t-table>
          <t-pagination v-if="state.invitations.length > state.pageSize" v-model="state.invitePage" :page-size="state.pageSize" :total="state.invitations.length" :show-page-size="false" />
        </t-tab-panel>
        <t-tab-panel value="applications" :label="t('adminApplications.title')"><JoinRequestsPanel v-if="state.tab === 'applications'" :refresh-key="applicationsRefresh" @approved="state.load" @busy="applicationsBusy = $event" /></t-tab-panel>
      </t-tabs>
      <t-alert theme="info" :message="t('adminMembers.limits')" />
    </template>
    <t-dialog :visible="state.editorOpen" :header="t('adminMembers.invite')" :footer="false" @close="state.closeEditor">
      <t-alert v-if="state.error" theme="error" :message="state.error" />
      <t-form :data="state.form" :rules="rules" layout="vertical" :disabled="state.busy" @submit="state.submitMember">
        <t-form-item :label="t('adminMembers.createAccount')"><t-switch v-model="state.createAccount" :aria-label="t('adminMembers.createAccount')" /></t-form-item>
        <p>{{ state.createAccount ? t('adminMembers.createAccountHint') : t('adminMembers.existingHint') }}</p>
        <t-form-item name="email" :label="t('adminMembers.email')"><t-input v-model="state.form.email" :maxlength="255" autocomplete="off" /></t-form-item>
        <t-form-item :label="t('adminMembers.role')"><t-select v-model="state.form.role" :options="inviteRoles" /></t-form-item>
        <template v-if="state.createAccount">
          <t-form-item name="username" :label="t('adminMembers.username')"><t-input v-model="state.form.username" :maxlength="64" autocomplete="off" /></t-form-item>
          <t-form-item :label="t('adminMembers.displayName')"><t-input v-model="state.form.display_name" :maxlength="160" /></t-form-item>
          <t-form-item name="password" :label="t('adminMembers.password')" :help="t('adminMembers.passwordHint')"><t-input v-model="state.form.password" type="password" :maxlength="256" autocomplete="new-password" /></t-form-item>
        </template>
        <t-button type="submit" theme="primary" :loading="state.busy">{{ state.createAccount ? t('adminMembers.createAndJoin') : t('adminMembers.sendInvite') }}</t-button>
      </t-form>
    </t-dialog>
    <t-dialog :visible="state.linkOpen" :header="t('adminMembers.createLink')" :footer="false" @close="state.closeLink">
      <t-alert v-if="state.error" theme="error" :message="state.error" />
      <t-form :data="state.linkForm" layout="vertical" :disabled="state.busy" @submit="state.submitLink">
        <t-alert theme="warning" :message="t('adminMembers.linkHint')" />
        <t-form-item :label="t('adminMembers.role')"><t-select v-model="state.linkForm.role" :options="inviteRoles" /></t-form-item>
        <t-form-item :label="t('adminMembers.expiryDays')"><t-input-number v-model="state.linkForm.days" :min="1" :max="30" :decimal-places="0" /></t-form-item>
        <t-button type="submit" theme="primary" :loading="state.busy" :disabled="!Number.isInteger(state.linkForm.days) || !state.linkForm.days || state.linkForm.days < 1 || state.linkForm.days > 30">{{ t('adminMembers.createLink') }}</t-button>
      </t-form>
    </t-dialog>
  </section>
</template>
<style scoped>
.members-page { display: grid; gap: 20px; }
.members-page header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 20px; }
h1 { margin: 0 0 12px; font-size: 24px; } p { color: var(--td-text-color-secondary); line-height: 1.6; }
.member-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.member-toolbar { margin: 20px 0; max-width: 420px; }
.member-role { width: 150px; }
.person-detail { margin: 4px 0; overflow-wrap: anywhere; }
.members-page :deep(.t-table__content) { overflow-x: auto; }
.members-page :deep(.t-pagination) { margin: 20px 0; }
small { display: block; margin-top: 8px; color: var(--td-text-color-secondary); }
</style>
