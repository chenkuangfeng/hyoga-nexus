<script setup lang="ts">
/** Provider provisioning and pending-instance recovery, restricted by the server to platform administrators. */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getGatewayExecutions, getGatewayProvider, retryGatewayCleanup, saveGatewayProvider,
  type GatewayExecution,
} from '@nexus-web/core/api/nexus-sandboxes'

const props = defineProps<{ tenant: string; name: string }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const form = reactive({ type: 'e2b' as 'e2b' | 'cubesandbox', template: '', domain: 'e2b.app', revision: '', api_key: '' })
const items = ref<GatewayExecution[]>([])
const hasKey = ref(false)
const loading = ref(false)
const saving = ref(false)
const retrying = ref('')
const failed = ref(false)
const saved = ref(false)
const valid = computed(() => !!form.template.trim() && !!form.revision.trim()
  && /^[a-zA-Z0-9.-]+$/.test(form.domain) && (hasKey.value || !!form.api_key.trim()))
let disposed = false

async function load() {
  loading.value = true
  failed.value = false
  try {
    const [provider, executions] = await Promise.all([
      getGatewayProvider(props.tenant, props.name), getGatewayExecutions(props.tenant, props.name),
    ])
    if (disposed) return
    if (!provider || !['e2b', 'cubesandbox', 'docker'].includes(provider.type)
      || typeof provider.has_api_key !== 'boolean' || !Array.isArray(executions.items)
      || executions.items.some(item => !/^[a-f0-9]{32}$/.test(item.id) || typeof item.state !== 'string')) {
      throw new Error('Invalid gateway configuration')
    }
    if (provider.type !== 'docker') {
      form.type = provider.type
      form.template = provider.template
      form.domain = provider.domain
      form.revision = provider.revision
    }
    hasKey.value = provider.has_api_key
    items.value = executions.items
  } catch {
    if (!disposed) failed.value = true
  } finally {
    if (!disposed) loading.value = false
  }
}

async function save() {
  if (!valid.value || saving.value || items.value.length) return
  saving.value = true
  failed.value = false
  saved.value = false
  try {
    await saveGatewayProvider(props.tenant, props.name, { ...form })
    if (disposed) return
    form.api_key = ''
    hasKey.value = true
    saved.value = true
    emit('changed')
  } catch {
    if (!disposed) failed.value = true
  } finally {
    if (!disposed) saving.value = false
  }
}

async function retry(item: GatewayExecution) {
  if (retrying.value) return
  retrying.value = item.id
  try {
    await retryGatewayCleanup(props.tenant, props.name, item.id)
    if (!disposed) await load()
  } catch {
    if (!disposed) failed.value = true
  } finally {
    if (!disposed) retrying.value = ''
  }
}
onMounted(load)
onBeforeUnmount(() => { disposed = true; form.api_key = '' })
</script>

<template>
  <t-loading :loading="loading">
    <div class="gateway-config">
      <t-alert v-if="failed" theme="error" :message="t('sandboxSettings.gatewayFailed')" />
      <t-button variant="text" :disabled="saving" @click="load">{{ t('connectionUi.refresh') }}</t-button>
      <t-form label-align="top" @submit="save">
        <t-form-item :label="t('sandboxSettings.provider')">
          <t-select v-model="form.type" :disabled="saving" :aria-label="t('sandboxSettings.provider')"
            :options="[{ value: 'e2b', label: 'E2B' }, { value: 'cubesandbox', label: 'CubeSandbox' }]" />
        </t-form-item>
        <t-form-item v-for="field in (['template', 'domain', 'revision'] as const)" :key="field"
          :label="t(`sandboxSettings.${field}`)">
          <t-input v-model="form[field]" :maxlength="256" :disabled="saving" :aria-label="t(`sandboxSettings.${field}`)" />
        </t-form-item>
        <t-form-item :label="t('sandboxSettings.apiKey')" :help="t(hasKey ? 'sandboxSettings.keyStored' : 'sandboxSettings.keyRequired')">
          <t-input v-model="form.api_key" type="password" autocomplete="new-password" :maxlength="1024"
            :disabled="saving" :aria-label="t('sandboxSettings.apiKey')" />
        </t-form-item>
        <t-alert v-if="items.length" theme="warning" :message="t('sandboxSettings.pendingInstances')" />
        <t-alert v-if="saved" theme="success" :message="t('sandboxSettings.providerSaved')" />
        <t-button type="submit" :loading="saving" :disabled="!valid || items.length > 0 || loading">
          {{ t('sandboxSettings.saveProvider') }}
        </t-button>
      </t-form>
      <h4>{{ t('sandboxSettings.instances') }}</h4>
      <t-empty v-if="!loading && !items.length" :description="t('sandboxSettings.noInstances')" />
      <article v-for="item in items" :key="item.id" class="gateway-instance">
        <code>{{ item.id }}</code>
        <t-tag>{{ t(`sandboxSettings.states.${item.state}`, item.state) }}</t-tag>
        <t-button v-if="item.state === 'cleanup_pending'" variant="outline" :loading="retrying === item.id"
          :disabled="!!retrying && retrying !== item.id" @click="retry(item)">
          {{ t('sandboxSettings.retryCleanup') }}
        </t-button>
      </article>
    </div>
  </t-loading>
</template>

<style scoped lang="less">
.gateway-config { display: grid; gap: 12px; min-width: 0; }
.gateway-instance { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.gateway-instance code { overflow-wrap: anywhere; min-width: 0; }
</style>
