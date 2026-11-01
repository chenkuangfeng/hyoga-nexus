<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { orgApi } from '../../api/orgs'
import { adminSessionApi, type AdminAgent, type AdminSession } from '../../api/adminSessions'
import type { Tenant } from '../../types/chat'
import type { OrgNode } from '../../types/orgs'
import { i18n } from '../../i18n'

/** Platform administrator view: chat sessions across all spaces, filtered by space or organization node.
 * Memory is deliberately not shown here; it stays visible only to its owner.
 */
const tenants = ref<Tenant[]>([])
const agents = ref<AdminAgent[]>([])
const units = ref<OrgNode[]>([])
const tenantId = ref(''), agentId = ref(''), unitId = ref('')
const sessions = ref<AdminSession[]>([])
const loading = ref(false), error = ref('')

const message = (err: unknown) => (err instanceof Error ? err.message : i18n.global.t('errors.httpFailed'))
const tenantName = computed(() => new Map(tenants.value.map(item => [item.id, item.name])))
const unitName = computed(() => new Map(units.value.map(item => [item.id, item.name])))

async function loadSessions() {
  loading.value = true; error.value = ''
  try {
    sessions.value = await adminSessionApi.sessions({ tenantId: tenantId.value, agentId: agentId.value, orgUnitId: unitId.value })
  } catch (err) { error.value = message(err); sessions.value = [] }
  finally { loading.value = false }
}
watch([tenantId, agentId, unitId], () => void loadSessions())
onMounted(async () => {
  try {
    const [spaces, orgs, allAgents] = await Promise.all([adminSessionApi.tenants(), orgApi.orgs(), adminSessionApi.agents()])
    tenants.value = spaces
    agents.value = allAgents
    const trees = await Promise.all(orgs.map(org => orgApi.tree(org.id)))
    units.value = trees.flat()
  } catch (err) { error.value = message(err) }
  await loadSessions()
})
</script>

<template>
  <main class="admin-sessions" v-loading="loading" :aria-busy="loading">
    <header>
      <div><p class="eyebrow">{{ $t('adminSessions.eyebrow') }}</p><h1>{{ $t('shell.titles.adminSessions') }}</h1></div>
    </header>
    <p class="intro">{{ $t('adminSessions.intro') }}</p>
    <div class="filters">
      <label for="admin-tenant">{{ $t('adminSessions.space') }}</label>
      <el-select id="admin-tenant" v-model="tenantId" clearable :placeholder="$t('adminSessions.allSpaces')">
        <el-option v-for="item in tenants" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <label for="admin-agent">{{ $t('adminSessions.agent') }}</label>
      <el-select id="admin-agent" v-model="agentId" clearable :placeholder="$t('adminSessions.allAgents')">
        <el-option v-for="item in agents" :key="item.id" :label="$t('adminSessions.agentOption', { name: item.name, space: tenantName.get(item.tenant_id) || $t('adminSessions.defaultSpace') })" :value="item.id" />
      </el-select>
      <label for="admin-unit">{{ $t('adminSessions.orgNode') }}</label>
      <el-select id="admin-unit" v-model="unitId" clearable :placeholder="$t('adminSessions.allOrgs')">
        <el-option v-for="item in units" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notice" role="alert" />
    <el-empty v-if="!loading && !sessions.length" :description="$t('adminSessions.noResults')" />
    <table v-else-if="sessions.length" class="sessions" :aria-label="$t('adminSessions.tableLabel')">
      <thead>
        <tr><th scope="col">{{ $t('adminSessions.colTitle') }}</th><th scope="col">{{ $t('adminSessions.colSpace') }}</th><th scope="col">{{ $t('adminSessions.colOrg') }}</th><th scope="col">{{ $t('adminSessions.colOwner') }}</th><th scope="col">{{ $t('adminSessions.colUpdated') }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in sessions" :key="item.id">
          <td>{{ item.title || $t('adminSessions.untitled', { id: item.id.slice(-8) }) }}</td>
          <td>{{ tenantName.get(item.tenant_id) || item.tenant_id.slice(-8) }}</td>
          <td>
            <span v-if="item.org_unit_id">{{ unitName.get(item.org_unit_id) || $t('adminSessions.unitFallback') }}</span>
            <span v-if="item.org_unit_id" class="org-tag">{{ $t('adminSessions.orgAccess') }}</span>
            <span v-else class="muted">—</span>
          </td>
          <td>{{ $t('adminSessions.owner', { id: item.owner_user_id.slice(-8) }) }}</td>
          <td>{{ new Date(item.updated_at).toLocaleString() }}</td>
        </tr>
      </tbody>
    </table>
  </main>
</template>

<style scoped>
.admin-sessions { max-width: 1040px; margin: 0 auto; padding: 24px; }
header h1 { margin: 0; }
.intro, .muted { color: var(--muted-text); line-height: 1.6; font-size: 14px; }
.notice { margin-top: 12px; }
.filters { display: grid; grid-template-columns: 80px 240px 80px 240px; gap: 12px; align-items: center; margin: 16px 0; }
.filters label { font-size: 14px; font-weight: 600; }
.sessions { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.sessions th, .sessions td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 14px; overflow-wrap: anywhere; }
.org-tag { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 999px; font-size: 12px; background: var(--el-fill-color); color: var(--muted-text); }
@media (max-width: 720px) { .filters { grid-template-columns: 1fr; } }
</style>
