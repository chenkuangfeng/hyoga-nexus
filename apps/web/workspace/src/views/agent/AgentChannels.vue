<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getNexusAgent, type NexusAgent } from '@nexus-web/core/api/nexus-agents'
import IMChannelPanel from '@nexus-web/core/components/IMChannelPanel.vue'

const route = useRoute(), router = useRouter(), auth = useAuthStore()
const { t } = useI18n()
const tenantId = computed(() => String(auth.effectiveTenantId || ''))
const agentId = computed(() => String(route.params.agentId || ''))
const agent = ref<NexusAgent | null>(null)
const loading = ref(false), error = ref('')
const tab = computed(() => route.query.tab === 'embed' ? 'embed' : 'im')
let epoch = 0
async function load() {
  const current = ++epoch
  agent.value = null; error.value = ''; loading.value = true
  if (!tenantId.value || !agentId.value) { loading.value = false; return }
  try { const tenant = tenantId.value, id = agentId.value; const row = await getNexusAgent(tenant, id); if (row.tenant_id !== tenant || row.id !== id) throw new Error(t('connectionUi.failed')); if (current === epoch) agent.value = row }
  catch (reason) { if (current === epoch) error.value = reason instanceof Error ? reason.message : t('connectionUi.failed') }
  finally { if (current === epoch) loading.value = false }
}
watch([tenantId, agentId, () => auth.user?.id], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { epoch++ })
</script>
<template>
  <main class="agent-channels">
    <header><t-link href="/platform/agents">{{ t('connectionUi.backAgents') }}</t-link><h1>{{ agent?.name || t('connectionUi.channels') }}</h1></header>
    <t-alert v-if="error" theme="error" :message="error" /><t-button v-if="error" @click="load">{{ t('connectionUi.refresh') }}</t-button>
    <t-loading :loading="loading">
      <t-alert v-if="agent && agent.can_maintain !== true" theme="warning" :message="t('connectionUi.maintainersOnly')" />
      <template v-else-if="agent && (agent.ownership === 'personal' || agent.ownership === 'enterprise')">
        <div class="channel-tabs" role="tablist" :aria-label="t('connectionUi.channels')">
          <t-button role="tab" :aria-selected="tab === 'im'" @click="router.replace({ query: { tab: 'im' } })">{{ t('connectionUi.im') }}</t-button>
          <t-button role="tab" :aria-selected="tab === 'embed'" @click="router.replace({ query: { tab: 'embed' } })">{{ t('connectionUi.embed') }}</t-button>
        </div>
        <IMChannelPanel v-if="tab === 'im'" :tenant-id="tenantId" :agent-id="agentId" :ownership="agent.ownership" />
        <t-alert v-else theme="info" :message="t('connectionUi.embedPlanned')" />
      </template>
    </t-loading>
  </main>
</template>
<style scoped>
.agent-channels { max-width: 1100px; width: 100%; padding: 24px; margin: 0 auto; }
.channel-tabs { display: flex; gap: 12px; margin: 16px 0; }
@media (max-width: 640px) { .agent-channels { padding: 16px; } }
</style>
