<script setup lang="ts">
/** WeKnora sandbox settings cards and editor, backed by the Nexus shared profile registry. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { DialogPlugin, MessagePlugin, type DropdownOption } from 'tdesign-vue-next'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  deleteSandboxConfiguration, listSandboxProfiles,
  type SandboxBackend, type SandboxCatalog, type SandboxDetails,
} from '@nexus-web/core/api/nexus-sandboxes'
import SandboxProfileDrawer from './SandboxProfileDrawer.vue'
import SandboxConfigEditorDrawer from './SandboxConfigEditorDrawer.vue'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n()
const auth = useAuthStore()
const context = useEnterpriseContext()
const canRead = computed(() => ['owner', 'admin'].includes(auth.currentTenantRole || ''))
const catalog = ref<SandboxCatalog>()
const profiles = computed(() => catalog.value?.items || [])
const loading = ref(false)
const error = ref(false)
const activeType = ref<SandboxBackend | 'all'>('all')
const query = ref('')
const selected = ref('')
const editorOpen = ref(false)
const editing = ref<SandboxDetails | null>(null)
const deleting = ref('')
const types: SandboxBackend[] = ['local', 'ssh', 'bwrap', 'docker', 'managed']
const typeNames = computed(() => ({
  docker: 'Docker', bwrap: 'Bubblewrap', ssh: 'SSH',
  managed: t('nexusAgent.sandboxProfile.typeManaged'), local: t('nexusAgent.sandboxProfile.typeLocal'),
}))
const reasons: Record<string, string> = {
  sandbox_disabled: 'reasonSandboxDisabled', sandbox_not_accepted: 'reasonNotAccepted',
  sandbox_local_not_allowed: 'reasonLocalNotAllowed', sandbox_profile_unknown: 'reasonUnknown',
  sandbox_connection_required: 'reasonConnection', sandbox_profile_paused: 'reasonPaused',
  sandbox_ssh_not_allowed: 'reasonSshNotAllowed',
}
const filtered = computed(() => profiles.value.filter(profile =>
  (activeType.value === 'all' || activeType.value === profile.type)
  && [profile.display_name, profile.name, profile.description].join(' ').toLowerCase().includes(query.value.trim().toLowerCase()),
))
let request = 0
let deleteDialog: ReturnType<typeof DialogPlugin.confirm> | undefined
function title(profile: SandboxDetails) { return profile.display_name || profile.name }
function target(profile: SandboxDetails): string {
  return String(profile.configuration?.endpoint || profile.configuration?.ssh_host || profile.image || profile.remote_profile || '')
}
async function load() {
  const current = ++request
  const tenant = auth.effectiveTenantId
  loading.value = true
  error.value = false
  if (!tenant || !canRead.value) { loading.value = false; return }
  try {
    const result = await listSandboxProfiles(String(tenant))
    if (current !== request) return
    if (!Array.isArray(result.items) || typeof result.can_manage !== 'boolean' || !Number.isInteger(result.revision)
      || result.items.some(item => !item || typeof item.name !== 'string' || !types.includes(item.type))) {
      throw new Error('Invalid sandbox catalog')
    }
    catalog.value = result
  } catch {
    if (current === request) error.value = true
  } finally {
    if (current === request) loading.value = false
  }
}
function openEditor(profile: SandboxDetails | null) {
  if (!catalog.value?.can_manage) return
  editing.value = profile
  editorOpen.value = true
}
function openCard(profile: SandboxDetails) {
  if (catalog.value?.can_manage) openEditor(profile)
  else selected.value = profile.name
}
function menu(profile: SandboxDetails): DropdownOption[] {
  return [
    { value: 'edit', content: t('sandboxConfig.edit') },
    { value: 'details', content: t('sandboxSettings.details') },
    { value: 'delete', content: t('sandboxConfig.delete'), theme: 'error', disabled: profile.default || !!deleting.value },
  ]
}
function action(value: unknown, profile: SandboxDetails) {
  if (value === 'edit') openEditor(profile)
  if (value === 'details') selected.value = profile.name
  if (value !== 'delete' || !catalog.value?.can_manage) return
  const tenant = String(auth.effectiveTenantId)
  const revision = catalog.value.revision
  const current = request
  deleteDialog?.destroy()
  const dialog = DialogPlugin.confirm({
    header: t('sandboxConfig.delete'), body: t('sandboxConfig.deleteConfirm', { name: title(profile) }),
    confirmBtn: { content: t('sandboxConfig.delete'), theme: 'danger' },
    onConfirm: async () => {
      if (deleting.value || current !== request) { dialog.destroy(); return }
      deleting.value = profile.name
      try {
        await deleteSandboxConfiguration(tenant, profile.name, revision)
        dialog.destroy()
        if (current === request) await load()
      } catch {
        if (current === request) MessagePlugin.error(t('sandboxConfig.deleteFailed'))
      } finally { deleting.value = '' }
    },
    onClose: () => dialog.destroy(),
  })
  deleteDialog = dialog
}
async function saved(profile: SandboxDetails) {
  editorOpen.value = false
  MessagePlugin.success(t('sandboxConfig.saved'))
  await load()
  if (profiles.value.some(item => item.name === profile.name)) selected.value = profile.name
}
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canRead], () => {
  deleteDialog?.destroy()
  deleteDialog = undefined
  selected.value = ''
  editorOpen.value = false
  catalog.value = undefined
  void load()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { request++; deleteDialog?.destroy() })
</script>

<template>
  <section class="sandbox-settings">
    <header class="section-header">
      <div class="section-header__top">
        <div class="section-header__titlewrap">
          <h2>{{ t('enterpriseNav.sandbox') }}</h2>
          <t-popup trigger="click" placement="bottom-left" :content="t('sandboxConfig.scopeHint')">
            <t-button variant="text" shape="square" :aria-label="t('sandboxConfig.scopeTitle')">
              <t-icon name="help-circle" aria-hidden="true" />
            </t-button>
          </t-popup>
        </div>
        <div class="header-actions">
          <t-button v-if="catalog?.can_manage" variant="text" @click="openEditor(null)">
            <template #icon><t-icon name="add" aria-hidden="true" /></template>{{ t('sandboxConfig.add') }}
          </t-button>
          <t-button v-if="canRead" variant="text" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button>
        </div>
      </div>
      <p class="section-description">{{ t('sandboxConfig.descriptionText') }}</p>
    </header>
    <t-alert v-if="!canRead" theme="info" :message="t('adminConsole.denied')" />
    <t-alert v-else-if="error" theme="error" :message="t('settings.sandbox.loadFailed')" />
    <template v-else>
      <div v-if="catalog" class="setting-row">
        <div class="setting-info">
          <strong>{{ t('sandboxConfig.deployment') }}</strong>
          <p>{{ t(catalog.enabled ? 'sandboxConfig.deploymentEnabled' : 'sandboxConfig.deploymentDisabled') }}</p>
        </div>
        <t-tag :theme="catalog.enabled ? 'success' : 'warning'">
          {{ t(catalog.enabled ? 'sandboxConfig.enabled' : 'sandboxConfig.disabled') }}
        </t-tag>
      </div>
      <div class="sandbox-tabs-row">
        <t-tabs v-model="activeType" class="sandbox-type-tabs">
          <t-tab-panel value="all" :label="`${t('common.all')} ${profiles.length}`" />
          <t-tab-panel v-for="type in types" :key="type" :value="type"
            :label="`${typeNames[type]} ${profiles.filter(profile => profile.type === type).length}`" />
        </t-tabs>
        <t-input v-model="query" clearable class="sandbox-search" :placeholder="t('menu.search')" :aria-label="t('menu.search')">
          <template #prefix-icon><t-icon name="search" aria-hidden="true" /></template>
        </t-input>
      </div>
      <div class="sandbox-list-scroll">
        <t-loading :loading="loading" class="sandbox-list-loading">
          <div class="sandbox-grid">
            <article v-for="profile in filtered" :key="profile.name" class="sandbox-card sandbox-card--clickable"
              role="button" tabindex="0" :aria-label="title(profile)" @click="openCard(profile)"
              @keydown.enter.self="openCard(profile)" @keydown.space.self.prevent="openCard(profile)">
              <div class="sandbox-card__badge"><t-icon :name="profile.type === 'ssh' ? 'server' : 'code'" aria-hidden="true" /></div>
              <div class="sandbox-card__body">
                <div class="sandbox-card__header">
                  <h3 class="sandbox-card__title" :title="title(profile)">{{ title(profile) }}</h3>
                  <t-tag v-if="profile.default" size="small">{{ t('common.default') }}</t-tag>
                  <div v-if="catalog?.can_manage" class="sandbox-card__actions" @click.stop @keydown.stop>
                    <t-dropdown :options="menu(profile)" trigger="click" @click="(item: DropdownOption) => action(item.value, profile)">
                      <t-button variant="text" shape="square" class="sandbox-card__more" :aria-label="t('sandboxConfig.more')">
                        <t-icon name="ellipsis" aria-hidden="true" />
                      </t-button>
                    </t-dropdown>
                  </div>
                </div>
                <div class="sandbox-card__subtitle">
                  <span>{{ typeNames[profile.type] }}</span>
                  <span v-if="profile.description" class="sandbox-card__desc">{{ profile.description }}</span>
                </div>
                <div v-if="target(profile)" class="sandbox-card__url" :title="target(profile)">{{ target(profile) }}</div>
                <div class="sandbox-card__status">
                  <t-tag size="small" :theme="profile.available ? 'success' : 'warning'">
                    {{ profile.available ? t('nexusAgent.sandboxProfile.available')
                      : t(`nexusAgent.sandboxProfile.${reasons[profile.reason] || 'reasonUnavailable'}`) }}
                  </t-tag>
                  <t-button variant="text" size="small" @click.stop="selected = profile.name" @keydown.stop>
                    {{ t('sandboxSettings.details') }}
                  </t-button>
                </div>
              </div>
            </article>
          </div>
          <t-empty v-if="!loading && !filtered.length" class="sandbox-empty"
            :description="t(profiles.length ? 'common.noResult' : 'enterpriseNav.sandboxEmpty')" />
        </t-loading>
      </div>
    </template>
    <SandboxConfigEditorDrawer v-if="editorOpen && catalog && auth.effectiveTenantId" :key="editing?.name || 'new'"
      :tenant="String(auth.effectiveTenantId)" :record="editing" :revision="catalog.revision" :defaults="catalog.defaults"
      :preset="activeType === 'all' ? 'docker' : activeType" @close="editorOpen = false" @saved="saved" />
    <SandboxProfileDrawer v-if="selected && auth.effectiveTenantId" :key="selected"
      :tenant="String(auth.effectiveTenantId)" :name="selected" @close="selected = ''" @saved="load" />
  </section>
</template>

<style scoped lang="less">
@import (reference) '@nexus-web/core/styles/provider-card.less';
.sandbox-settings { min-height: 0; display: flex; flex-direction: column; }
.section-header__top, .section-header__titlewrap, .header-actions { display: flex; align-items: center; gap: 12px; }
.section-header__top { justify-content: space-between; flex-wrap: wrap; }
.section-header h2 { margin: 0; }
.section-description { color: var(--td-text-color-secondary); }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 14px 16px;
  margin-bottom: 16px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); }
.setting-info p { margin: 6px 0 0; color: var(--td-text-color-secondary); }
.sandbox-tabs-row { display: flex; align-items: center; gap: 20px; border-bottom: 1px solid var(--td-component-stroke); }
.sandbox-type-tabs { flex: 1; min-width: 0; background: transparent;
  :deep(.t-tabs__nav-item) { height: 44px; }
  :deep(.t-tabs__content) { display: none; }
}
.sandbox-search { flex: 0 0 240px; width: 240px; }
.sandbox-list-scroll { flex: 1; min-height: 0; overflow: auto; padding: 16px 0 28px; }
.sandbox-list-loading { display: block; min-height: 160px; }
.sandbox-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap: 12px; }
.sandbox-card { .provider-card(); &--clickable { .provider-card-interactive(); } }
.sandbox-card__badge { .provider-card-badge(); }
.sandbox-card__body { .provider-card-body(); }
.sandbox-card__header { .provider-card-header(); }
.sandbox-card__title { .provider-card-title(); }
.sandbox-card__subtitle { .provider-card-subtitle(); }
.sandbox-card__desc, .sandbox-card__url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.sandbox-card__url { font-family: ui-monospace, monospace; font-size: var(--app-text-xs); color: var(--td-text-color-placeholder); }
.sandbox-card__actions { flex-shrink: 0; }
.sandbox-card__more { .provider-card-more(); }
.sandbox-card:hover .sandbox-card__more, .sandbox-card:focus-within .sandbox-card__more { opacity: 1; }
.sandbox-card__status { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 4px; }
.sandbox-empty { padding: 40px 16px; }
@media (max-width: 680px) {
  .sandbox-tabs-row { flex-wrap: wrap; gap: 12px; }
  .sandbox-type-tabs { flex-basis: 100%; }
  .sandbox-search { flex-basis: 100%; width: 100%; }
}
@media (prefers-reduced-motion: reduce) { .sandbox-card { transition: none; } }
</style>
