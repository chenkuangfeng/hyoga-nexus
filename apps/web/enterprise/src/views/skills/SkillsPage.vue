<script setup lang="ts">
/** WeKnora SkillSettings.vue 的目录卡片及安装入口，版本与审查使用 Nexus 契约。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { rescanSkillVersion, listTenantSkills, listSkillVersions, downloadSkillBundle, disableBuiltinResource, restoreBuiltinResource, type TenantSkill, type SkillVersionInfo } from '@nexus-web/core/api/nexus-agents'
import NexusSkillInstallPanel from '@nexus-web/core/components/agent-editor/NexusSkillInstallPanel.vue'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import SkillSubmissionsPage from './SkillSubmissionsPage.vue'
import { useEnterpriseContext } from '../../stores/context'
const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const rows = ref<TenantSkill[]>([]), query = ref(''), tab = ref('library'), loading = ref(false), error = ref(''), installing = ref(false), selected = ref<TenantSkill | null>(null), versions = ref<SkillVersionInfo[]>([]), busy = ref(false)
let epoch = 0, detailEpoch = 0
const filtered = computed(() => rows.value.filter(row => `${row.name} ${row.description}`.toLowerCase().includes(query.value.toLowerCase())))
async function load() {
  const current = ++epoch; detailEpoch++; rows.value = []; selected.value = null; versions.value = []; error.value = ''; installing.value = false; busy.value = false; loading.value = false
  if (!context.can('tools:manage') || !tenant.value) return
  loading.value = true
  try { const result = await listTenantSkills(tenant.value, ''); if (current === epoch) rows.value = result }
  catch { if (current === epoch) error.value = t('nexusAgent.mySkills.failed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id}:${context.revision}:${context.can('tools:manage')}`, load, { immediate: true })
onBeforeUnmount(() => { epoch++; detailEpoch++ })
async function inspect(row: TenantSkill) {
  const current = epoch, detail = ++detailEpoch; selected.value = row; versions.value = []
  try { const result = await listSkillVersions(tenant.value, row.name); if (current === epoch && detail === detailEpoch) versions.value = result }
  catch { if (current === epoch && detail === detailEpoch) error.value = t('nexusAgent.mySkills.failed') }
}
async function toggle(row: TenantSkill) {
  if (busy.value || !context.can('tools:manage')) return
  const current = epoch; busy.value = true
  try { await (row.disabled ? restoreBuiltinResource : disableBuiltinResource)(tenant.value, 'skill', row.name, true); if (current === epoch) await load() }
  catch { if (current === epoch) error.value = t('nexusAgent.mySkills.failed') }
  finally { if (current === epoch) busy.value = false }
}
async function rescan(version: number) {
  const row = selected.value, current = epoch
  if (!row || busy.value || row.scope !== 'space' || !context.can('tools:manage')) return
  busy.value = true
  try { await rescanSkillVersion(tenant.value, row.name, version); if (current === epoch) await inspect(row) }
  catch { if (current === epoch) error.value = t('nexusAgent.mySkills.failed') }
  finally { if (current === epoch) busy.value = false }
}
async function download(row: TenantSkill, version?: number) {
  const current = epoch
  try { const blob = await downloadSkillBundle(tenant.value, row.name, version); if (current !== epoch) return; const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `${row.name}.zip`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
  catch { if (current === epoch) error.value = t('nexusAgent.mySkills.failed') }
}
const props = defineProps<{ embedded?: boolean }>()
const emit = defineEmits<{ count: [value: number] }>()
watch([rows, loading, error], () => {
  if (!loading.value && !error.value) emit('count', rows.value.length)
})
</script>
<template>
  <section class="skill-settings"><header v-if="!props.embedded" class="section-header"><div><h2>{{ t('consoleLayout.skills') }}</h2><p>{{ t('settings.skills.description') }}</p></div><t-button v-if="context.can('tools:manage')" @click="installing = true"><t-icon name="add" />{{ t('consoleLayout.install') }}</t-button></header>
    <Teleport v-if="props.embedded && context.can('tools:manage')" to="#enterprise-toolbox-action">
      <t-button variant="outline" size="small" @click="installing = true">
        <template #icon><t-icon name="add" /></template>{{ t('consoleLayout.install') }}
      </t-button>
    </Teleport>
    <t-alert v-if="!context.can('tools:manage')" theme="info" :message="t('adminConsole.denied')" />
    <template v-else><t-tabs v-model="tab"><t-tab-panel value="library" :label="t('consoleLayout.library')" /><t-tab-panel value="review" :label="t('consoleLayout.review')" /></t-tabs>
      <SkillSubmissionsPage v-if="tab === 'review'" />
      <template v-else><Teleport to="#enterprise-toolbox-search" :disabled="!props.embedded">
        <t-input v-model="query" clearable :placeholder="t('menu.search')" :aria-label="t('menu.search')" />
      </Teleport><t-alert v-if="error" theme="error" :message="error"><template #operation><t-button variant="text" @click="load">{{ t('common.retry') }}</t-button></template></t-alert>
        <t-loading :loading="loading"><div class="skill-list"><article v-for="row in filtered" :key="`${row.scope}:${row.name}`" class="skill-card"><div class="skill-card__main"><div class="skill-card__body"><div class="skill-card__header"><div class="skill-card__badge">{{ row.name.slice(0,1).toUpperCase() }}</div><div class="skill-card__heading"><h3 class="skill-card__title">{{ row.name }}</h3><span class="skill-card__type">{{ row.version || '—' }}</span></div><div class="skill-card__actions"><t-button variant="text" :aria-label="t('common.expand')" @click="inspect(row)"><t-icon name="folder" /></t-button></div></div><p class="skill-card__desc">{{ row.description || '—' }}</p></div></div><div class="skill-card__footer"><t-tag>{{ t(row.scope === 'builtin' ? 'toolbox.skills.badge.builtin' : 'consoleLayout.enterprise') }}</t-tag><t-tag v-if="row.disabled">{{ t('common.off') }}</t-tag><t-button variant="text" @click="download(row)">{{ t('toolbox.skills.export') }}</t-button><t-popconfirm v-if="row.scope === 'builtin' && !row.disabled" :content="t('nexusAgent.disableHint')" @confirm="toggle(row)"><t-button variant="text" :disabled="busy">{{ t('nexusAgent.disableHere') }}</t-button></t-popconfirm><t-button v-else-if="row.scope === 'builtin'" variant="text" :disabled="busy" @click="toggle(row)">{{ t('nexusAgent.restore') }}</t-button></div></article></div><t-empty v-if="!loading && !filtered.length" :description="t('toolbox.skills.empty')" /></t-loading>
      </template>
      <SettingDrawer v-model:visible="installing" :title="t('consoleLayout.install')" hide-footer><NexusSkillInstallPanel v-if="installing" :key="`${tenant}:${context.revision}`" :tenant-id="tenant" @installed="load" /></SettingDrawer>
      <SettingDrawer :visible="!!selected" :title="selected?.name || ''" hide-footer @update:visible="(value: boolean) => { if (!value) { selected = null; detailEpoch++ } }"><p v-if="selected">{{ selected.description }}</p><ul><li v-for="version in versions" :key="version.version">{{ version.version }} · {{ version.verdict }} · {{ version.build_state }} · {{ version.created_at }}<t-button v-if="version.has_bundle && selected" variant="text" @click="download(selected, version.version)">{{ t('toolbox.skills.export') }}</t-button><t-button v-if="selected?.scope === 'space'" variant="text" :disabled="busy" @click="rescan(version.version)">{{ t('toolbox.skills.rescan') }}</t-button></li></ul></SettingDrawer>
    </template>
  </section>
</template>
<style scoped lang="less">
@import './SkillsPage.reference.less';
.skill-settings { min-width: 0; } .skill-list { margin-top: 20px; } .skill-card__footer { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 12px 16px; }
</style>
