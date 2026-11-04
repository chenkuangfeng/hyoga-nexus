<template>
  <div class="native-sessions">
    <header class="native-sessions__header">
      <div>
        <h2 class="native-sessions__title">{{ $t('nativeRuns.title') }}</h2>
        <p class="native-sessions__subtitle">{{ $t('nativeRuns.subtitle') }}</p>
      </div>
      <t-button theme="primary" :disabled="!tenantId || agents.length === 0" @click="showCreate = true"
        data-testid="native-new-session">
        {{ $t('nativeRuns.newSession') }}
      </t-button>
    </header>

    <t-alert v-if="errorText" theme="error" :message="errorText" class="native-sessions__alert" />

    <div v-if="showCreate" class="native-sessions__create" data-testid="native-create-form">
      <t-form layout="vertical" @submit="createSession">
        <t-form-item :label="$t('nativeRuns.agent')" name="agent">
          <t-select v-model="selectedAgent" :placeholder="$t('nativeRuns.agentPlaceholder')" :loading="loadingAgents"
            data-testid="native-agent-select">
            <t-option v-for="agent in agents" :key="agent.id" :value="agent.published_version_id as string"
              :label="agent.name" />
          </t-select>
        </t-form-item>
        <t-form-item :label="$t('nativeRuns.sessionTitle')" name="title">
          <t-input v-model="sessionTitle" :placeholder="$t('nativeRuns.sessionTitlePlaceholder')" :maxlength="255" />
        </t-form-item>
        <div class="native-sessions__create-actions">
          <t-button variant="outline" @click="showCreate = false">{{ $t('common.cancel') }}</t-button>
          <t-button type="submit" theme="primary" :disabled="!selectedAgent || creating" :loading="creating">
            {{ $t('nativeRuns.create') }}
          </t-button>
        </div>
      </t-form>
    </div>

    <t-loading :loading="loadingSessions" size="small">
      <ul v-if="sessions.length > 0" class="native-sessions__list" data-testid="native-session-list">
        <li v-for="session in sessions" :key="session.id">
          <router-link class="native-sessions__item" :to="`/platform/native/sessions/${session.id}`">
            <span class="native-sessions__item-title">{{ session.title || $t('nativeRuns.untitled') }}</span>
            <span class="native-sessions__item-time">{{ formatTime(session.updated_at) }}</span>
          </router-link>
        </li>
      </ul>
      <p v-else-if="!loadingSessions" class="native-sessions__empty">{{ $t('nativeRuns.empty') }}</p>
    </t-loading>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import { createSession as createSessionApi, listAgents, listSessions, type AgentView, type SessionView } from '@/api/native-runs'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const tenantId = computed(() => authStore.effectiveTenantId)
const sessions = ref<SessionView[]>([])
const agents = ref<AgentView[]>([])
const loadingSessions = ref(false)
const loadingAgents = ref(false)
const showCreate = ref(false)
const selectedAgent = ref<string | undefined>(undefined)
const sessionTitle = ref('')
const creating = ref(false)
const errorText = ref('')

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const data = error as { message?: unknown; error?: unknown } | null
  if (data && typeof data.message === 'string') return data.message
  if (data && typeof data.error === 'string') return data.error
  return fallback
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

async function loadAll() {
  errorText.value = ''
  const tenant = tenantId.value
  if (!tenant) {
    errorText.value = t('nativeRuns.noSpace')
    return
  }
  loadingSessions.value = true
  loadingAgents.value = true
  try {
    const [sessionRows, agentRows] = await Promise.all([listSessions(tenant), listAgents(tenant)])
    sessions.value = sessionRows
    // Only published agents can run: a draft has no version to create a Session against.
    agents.value = agentRows.filter(agent => agent.published_version_id !== null)
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  } finally {
    loadingSessions.value = false
    loadingAgents.value = false
  }
}

async function createSession() {
  if (!tenantId.value || !selectedAgent.value) return
  creating.value = true
  try {
    const session = await createSessionApi(tenantId.value, selectedAgent.value, sessionTitle.value.trim())
    showCreate.value = false
    sessionTitle.value = ''
    selectedAgent.value = undefined
    await router.push(`/platform/native/sessions/${session.id}`)
  } catch (error) {
    MessagePlugin.error(messageOf(error, t('nativeRuns.loadError')))
  } finally {
    creating.value = false
  }
}

onMounted(loadAll)
watch(tenantId, loadAll)
</script>

<style lang="less" scoped>
.native-sessions {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  max-width: 880px;
  margin: 0 auto;
  width: 100%;
}

.native-sessions__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.native-sessions__title {
  margin: 0 0 4px;
  font-size: var(--app-text-3xl);
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.native-sessions__subtitle {
  margin: 0;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-base);
}

.native-sessions__create {
  padding: 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-container);
}

.native-sessions__create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.native-sessions__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.native-sessions__item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
  text-decoration: none;

  &:hover,
  &:focus-visible {
    border-color: var(--td-brand-color);
  }
}

.native-sessions__item-time {
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-sm);
  white-space: nowrap;
}

.native-sessions__empty {
  color: var(--td-text-color-secondary);
  text-align: center;
  padding: 32px 0;
}
</style>
