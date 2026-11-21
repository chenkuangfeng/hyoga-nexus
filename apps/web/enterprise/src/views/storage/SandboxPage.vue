<script setup lang="ts">
/** 按 WeKnora 沙箱设置组织部署档位。后台 agent-tools 给出隔离验收状态。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getAgentToolCatalog, type AgentSandboxProfile } from '@nexus-web/core/api/nexus-agents'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n()
const auth = useAuthStore()
const context = useEnterpriseContext()
const canRead = computed(() => ['owner', 'admin'].includes(auth.currentTenantRole || ''))
const profiles = ref<AgentSandboxProfile[]>([])
const loading = ref(false)
const error = ref(false)
const activeType = ref('all')
const query = ref('')
const reasons: Record<string, string> = {
  sandbox_disabled: 'reasonSandboxDisabled',
  sandbox_not_accepted: 'reasonNotAccepted',
  sandbox_local_not_allowed: 'reasonLocalNotAllowed',
  sandbox_profile_unknown: 'reasonUnknown',
}
const typeNames = computed(() => ({ docker: 'Docker', bwrap: 'Bubblewrap', local: t('nexusAgent.sandboxProfile.typeLocal') }))
const types = computed(() => [...new Set(profiles.value.map(profile => profile.type))])
const filtered = computed(() => profiles.value.filter(profile =>
  (activeType.value === 'all' || activeType.value === profile.type)
  && profile.name.toLowerCase().includes(query.value.trim().toLowerCase()),
))
let request = 0

async function load() {
  const current = ++request
  const tenant = auth.effectiveTenantId
  profiles.value = []
  error.value = false
  loading.value = false
  if (!tenant || !canRead.value) return
  loading.value = true
  try {
    const catalog = await getAgentToolCatalog(String(tenant))
    if (current !== request) return
    const items = catalog.sandbox_profiles ?? []
    if (!Array.isArray(items) || items.some(item => !item || typeof item.name !== 'string'
      || !Object.hasOwn(typeNames.value, item.type) || typeof item.default !== 'boolean'
      || typeof item.available !== 'boolean' || typeof item.reason !== 'string')) throw new Error('Invalid sandbox profiles')
    profiles.value = items
    if (!types.value.some(type => type === activeType.value)) activeType.value = 'all'
  } catch {
    if (current === request) error.value = true
  } finally {
    if (current === request) loading.value = false
  }
}
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canRead], load, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { request++ })
</script>

<template>
  <section class="sandbox-settings">
    <header class="section-header">
      <div><h2>{{ t('enterpriseNav.sandbox') }}</h2><p>{{ t('enterpriseNav.sandboxDescription') }}</p></div>
      <t-button v-if="canRead" variant="outline" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button>
    </header>
    <t-alert v-if="!canRead" theme="info" :message="t('adminConsole.denied')" />
    <t-alert v-else-if="error" theme="error" :message="t('settings.sandbox.loadFailed')" />
    <template v-else>
      <div class="sandbox-tabs-row">
        <t-tabs v-model="activeType" class="sandbox-type-tabs">
          <t-tab-panel value="all" :label="`${t('common.all')} ${profiles.length}`" />
          <t-tab-panel v-for="type in types" :key="type" :value="type"
            :label="`${typeNames[type]} ${profiles.filter(profile => profile.type === type).length}`" />
        </t-tabs>
        <t-input v-model="query" clearable :placeholder="t('menu.search')" :aria-label="t('menu.search')">
          <template #prefix-icon><t-icon name="search" aria-hidden="true" /></template>
        </t-input>
      </div>
      <t-loading :loading="loading">
        <div class="sandbox-grid">
          <article v-for="profile in filtered" :key="profile.name" class="sandbox-card">
            <div class="sandbox-card__badge"><t-icon name="code" aria-hidden="true" /></div>
            <div class="sandbox-card__body">
              <h3>{{ profile.name }}</h3>
              <p>{{ typeNames[profile.type] }}</p>
              <t-tag v-if="profile.default" size="small">{{ t('common.default') }}</t-tag>
              <t-tag size="small" :theme="profile.available ? 'success' : 'warning'">
                {{ profile.available ? t('nexusAgent.sandboxProfile.available')
                  : t(`nexusAgent.sandboxProfile.${reasons[profile.reason] || 'reasonUnavailable'}`) }}
              </t-tag>
            </div>
          </article>
        </div>
        <t-empty v-if="!loading && !filtered.length" :description="t(profiles.length ? 'common.noResult' : 'enterpriseNav.sandboxEmpty')" />
      </t-loading>
    </template>
  </section>
</template>

<style scoped lang="less">
@import (reference) '@nexus-web/core/styles/provider-card.less';

.sandbox-tabs-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 16px; }
.sandbox-type-tabs { flex: 1; min-width: 0; }
.sandbox-tabs-row :deep(.t-input__wrap) { width: min(15rem, 100%); }
.sandbox-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 12px; }
.sandbox-card { .provider-card(); padding: 12px; gap: 12px; }
.sandbox-card__badge { .provider-card-badge(); background: var(--td-bg-color-secondarycontainer); }
.sandbox-card__body { min-width: 0; overflow-wrap: anywhere; }
.sandbox-card__body h3, .sandbox-card__body p { margin: 0 0 4px; }
.sandbox-card__body :deep(.t-tag) { margin: 0 4px 4px 0; max-width: 100%; }
</style>
