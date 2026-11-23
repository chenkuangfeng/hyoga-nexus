<script setup lang="ts">
/** Profile details, policy editing and worker-side acceptance in the same drawer. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SandboxGatewaySettings from './SandboxGatewaySettings.vue'
import {
  connectSandbox, getSandboxDetails, updateSandboxPolicy, type SandboxDetails, type SandboxPolicy,
} from '@nexus-web/core/api/nexus-sandboxes'

const props = defineProps<{ tenant: string; name: string }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { t } = useI18n()
const details = ref<SandboxDetails>()
const policy = ref<SandboxPolicy>()
const loading = ref(false)
const saving = ref(false)
const failed = ref(false)
const saveFailed = ref(false)
const saved = ref(false)
const connecting = ref(false)
const connectionFailed = ref(false)
const gatewayOpen = ref(false)
const timeoutFields = ['exec_timeout_max_seconds', 'skill_timeout_seconds', 'skill_timeout_max_seconds'] as const
const validPolicy = computed(() => policy.value
  && timeoutFields.every(field => Number.isInteger(policy.value?.[field])
    && Number(policy.value?.[field]) >= 1 && Number(policy.value?.[field]) <= 3600)
  && policy.value.skill_timeout_seconds <= policy.value.skill_timeout_max_seconds)
let disposed = false

async function load() {
  loading.value = true
  failed.value = false
  try {
    const result = await getSandboxDetails(props.tenant, props.name)
    if (disposed) return
    if (result.name !== props.name || typeof result.editable !== 'boolean' || !result.policy
      || !timeoutFields.every(field => Number.isInteger(result.policy[field]))
      || (result.acceptance !== null && !Array.isArray(result.acceptance?.items))) throw new Error('Invalid profile')
    details.value = result
    policy.value = { ...result.policy }
  } catch {
    if (!disposed) failed.value = true
  } finally {
    if (!disposed) loading.value = false
  }
}

async function save() {
  if (!details.value?.editable || !policy.value || !validPolicy.value || saving.value) return
  saving.value = true
  saveFailed.value = false
  saved.value = false
  try {
    const result = await updateSandboxPolicy(props.tenant, props.name, policy.value)
    if (disposed) return
    details.value = result
    policy.value = { ...result.policy }
    saved.value = true
    emit('saved')
  } catch {
    if (!disposed) saveFailed.value = true
  } finally {
    if (!disposed) saving.value = false
  }
}

async function connect() {
  if (connecting.value || saving.value || !details.value?.editable) return
  connecting.value = true
  connectionFailed.value = false
  try {
    const result = await connectSandbox(props.tenant, props.name)
    if (disposed) return
    details.value = result
    emit('saved')
  } catch {
    if (!disposed) connectionFailed.value = true
  } finally {
    if (!disposed) connecting.value = false
  }
}

async function refreshConnection() {
  try {
    const result = await getSandboxDetails(props.tenant, props.name)
    if (!disposed) { details.value = result; emit('saved') }
  } catch {
    if (!disposed) connectionFailed.value = true
  }
}

function togglePause() {
  if (details.value?.editable && policy.value && !saving.value) {
    policy.value.paused = !policy.value.paused
  }
}

onMounted(load)
onBeforeUnmount(() => { disposed = true })
</script>

<template>
  <t-drawer :visible="true" :header="`${t('sandboxSettings.details')} · ${name}`"
    size="min(36rem, 100vw)" :footer="false" :close-on-overlay-click="!saving" @close="emit('close')">
    <t-loading :loading="loading">
      <t-alert v-if="failed" theme="error" :message="t('settings.sandbox.loadFailed')" />
      <t-button v-if="failed" variant="outline" @click="load">{{ t('connectionUi.refresh') }}</t-button>
      <div v-if="details && policy && !failed" class="sandbox-detail">
        <section>
          <h3>{{ t('sandboxSettings.execution') }}</h3>
          <dl>
            <template v-if="details.image"><dt>{{ t('sandboxSettings.image') }}</dt><dd>{{ details.image }}</dd></template>
            <template v-if="details.remote_profile"><dt>{{ t('sandboxSettings.remoteProfile') }}</dt><dd>{{ details.remote_profile }}</dd></template>
            <template v-if="details.network"><dt>{{ t('sandboxSettings.network') }}</dt><dd>{{ t(`sandboxSettings.${details.network}`) }}</dd></template>
            <dt>{{ t('sandboxSettings.workspace') }}</dt><dd>{{ details.workspace_quota_mb }} MiB</dd>
            <template v-for="(value, key) in details.limits" :key="key">
              <dt>{{ t(`sandboxSettings.${key}`) }}</dt><dd>{{ value }}{{ key === 'memory_mb' ? ' MiB' : '' }}</dd>
            </template>
            <dt>{{ t('sandboxSettings.background') }}</dt><dd>{{ t(details.background ? 'sandboxSettings.supported' : 'sandboxSettings.unsupported') }}</dd>
            <dt>{{ t('sandboxSettings.build') }}</dt><dd>{{ t(details.build ? 'sandboxSettings.supported' : 'sandboxSettings.unsupported') }}</dd>
          </dl>
        </section>
        <section v-if="details.type === 'managed'">
          <h3>{{ t('sandboxSettings.connection') }}</h3>
          <p>{{ t('sandboxSettings.connectionHint') }}</p>
          <t-button v-if="details.editable" variant="outline" :loading="connecting" :disabled="saving" @click="connect">
            {{ t('sandboxSettings.connect') }}
          </t-button>
          <t-button v-if="details.editable" variant="text" @click="gatewayOpen = !gatewayOpen">
            {{ t('sandboxSettings.configureGateway') }}
          </t-button>
          <SandboxGatewaySettings v-if="gatewayOpen" :tenant="tenant" :name="name" @changed="refreshConnection" />
          <t-alert v-if="connectionFailed" theme="error" :message="t('sandboxSettings.connectionFailed')" />
          <dl v-if="details.connection">
            <dt>{{ t('sandboxSettings.provider') }}</dt><dd>{{ details.connection.provider }}</dd>
            <dt>{{ t('sandboxSettings.fileTransfer') }}</dt>
            <dd>{{ t(`sandboxSettings.${details.connection.file_transfer}`) }}</dd>
            <dt>{{ t('sandboxSettings.connectedAt') }}</dt><dd>{{ details.connection.connected_at }}</dd>
            <dt>{{ t('sandboxSettings.revision') }}</dt><dd>{{ details.connection.template_revision }}</dd>
            <dt>{{ t('sandboxSettings.digest') }}</dt><dd><code>{{ details.connection.policy_digest }}</code></dd>
          </dl>
        </section>
        <section>
          <h3>{{ t('sandboxSettings.policy') }}</h3>
          <t-form label-align="top" @submit="save">
            <t-form-item :label="t('sandboxSettings.paused')">
              <t-switch v-model="policy.paused" role="switch" :aria-label="t('sandboxSettings.paused')"
                :aria-checked="policy.paused" :aria-disabled="!details.editable || saving"
                :tabindex="details.editable && !saving ? 0 : -1" :disabled="!details.editable || saving"
                @keydown.space.prevent="togglePause" @keydown.enter.prevent="togglePause" />
            </t-form-item>
            <t-form-item v-for="field in timeoutFields" :key="field" :label="t(`sandboxSettings.${field}`)">
              <t-input-number v-model="policy[field]" :min="1" :max="3600" :step="1"
                :disabled="!details.editable || saving" :aria-label="t(`sandboxSettings.${field}`)" />
            </t-form-item>
            <t-alert v-if="!validPolicy" theme="warning" :message="t('sandboxSettings.invalidTimeout')" />
            <t-alert v-if="saveFailed" theme="error" :message="t('sandboxSettings.saveFailed')" />
            <t-alert v-if="saved" theme="success" :message="t('sandboxSettings.saved')" />
            <t-button v-if="details.editable" type="submit" :loading="saving" :disabled="!validPolicy || connecting">
              {{ t('sandboxSettings.save') }}
            </t-button>
          </t-form>
        </section>
        <section>
          <h3>{{ t('sandboxSettings.acceptance') }}</h3>
          <template v-if="details.acceptance">
            <p>
              <t-tag :theme="details.acceptance.passed ? 'success' : 'warning'">
                {{ t(details.acceptance.passed ? 'sandboxSettings.passed' : 'sandboxSettings.needsAcceptance') }}
              </t-tag>
              {{ details.acceptance.checked_at }}
            </p>
            <dl>
              <template v-for="item in details.acceptance.items" :key="item.name">
                <dt>{{ t(`sandboxSettings.probes.${item.name}`, item.name) }}</dt>
                <dd>{{ t(item.ok ? 'sandboxSettings.passed' : 'sandboxSettings.failed') }}</dd>
              </template>
            </dl>
          </template>
          <p v-else>{{ t(details.type === 'local' ? 'sandboxSettings.localOnly' : 'sandboxSettings.noReport') }}</p>
          <code v-if="details.type !== 'local'">uv run python -m nexus_worker --sandbox-check --profile {{ name }}</code>
        </section>
      </div>
    </t-loading>
  </t-drawer>
</template>

<style scoped lang="less">
.sandbox-detail { display: grid; gap: 20px; overflow-wrap: anywhere; }
.sandbox-detail h3 { margin: 0 0 10px; }
.sandbox-detail section + section { border-top: 1px solid var(--td-component-stroke); padding-top: 16px; }
.sandbox-detail dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px 16px; margin: 0; }
.sandbox-detail dd { margin: 0; }
.sandbox-detail :deep(.t-form) { display: grid; gap: 8px; justify-items: start; }
</style>
