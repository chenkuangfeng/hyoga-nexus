<template>
  <!--
    Create/edit dialog for one MCP service (openspec 2026-11-08-mcp, tasks 4.1–4.2).
    The form collects connection parameters only; credential references stay references and the
    OAuth client secret is carried over from the stored config, never displayed.
  -->
  <EditorDialog :visible="visible" :header="title" width="640px" :footer="false" :close-on-overlay-click="false"
    :z-index="2000" @close="close">
    <t-alert v-if="error" theme="error" :message="error" class="mcp-dialog-alert" />

    <t-form label-align="top" class="mcp-dialog-form" @submit.prevent>
      <t-form-item :label="$t('toolbox.mcp.name')">
        <t-input v-model="form.name" maxlength="64" :placeholder="$t('toolbox.mcp.namePlaceholder')" />
      </t-form-item>
      <t-form-item :label="$t('toolbox.mcp.descriptionLabel')">
        <t-textarea v-model="form.description" maxlength="4000" :autosize="{ minRows: 2, maxRows: 4 }"
          :placeholder="$t('toolbox.mcp.descriptionPlaceholder')" />
      </t-form-item>
      <t-form-item :label="$t('toolbox.mcp.transport')">
        <t-select v-model="form.transport" class="mcp-dialog-transport">
          <t-option value="streamable_http" :label="$t('toolbox.mcp.transports.streamable_http')" />
          <t-option value="sse" :label="$t('toolbox.mcp.transports.sse')" />
          <t-option value="stdio" :label="$t('toolbox.mcp.transports.stdio')" />
        </t-select>
      </t-form-item>

      <template v-if="form.transport === 'stdio'">
        <t-form-item :label="$t('toolbox.mcp.command')">
          <t-input v-model="form.command" :placeholder="$t('toolbox.mcp.commandPlaceholder')" />
        </t-form-item>
        <t-form-item :label="$t('toolbox.mcp.args')">
          <t-textarea v-model="form.args" :autosize="{ minRows: 2, maxRows: 6 }"
            :placeholder="$t('toolbox.mcp.argsPlaceholder')" />
        </t-form-item>
        <t-form-item :label="$t('toolbox.mcp.env')">
          <NexusMcpKeyValueEditor v-model="form.env" />
        </t-form-item>
      </template>

      <template v-else>
        <t-form-item :label="$t('toolbox.mcp.url')">
          <t-input v-model="form.url" :placeholder="$t('toolbox.mcp.urlPlaceholder')" />
        </t-form-item>
        <t-form-item :label="$t('toolbox.mcp.headers')">
          <NexusMcpKeyValueEditor v-model="form.headers" />
          <p class="mcp-dialog-hint">{{ $t('toolbox.mcp.headersHint') }}</p>
        </t-form-item>
        <t-form-item :label="$t('toolbox.mcp.authType')">
          <t-radio-group v-model="form.authType" variant="default-filled">
            <t-radio-button value="none">{{ $t('toolbox.mcp.authNone') }}</t-radio-button>
            <t-radio-button value="oauth">{{ $t('toolbox.mcp.authOAuth') }}</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <template v-if="form.authType === 'oauth'">
          <t-form-item :label="$t('toolbox.mcp.oauthScopes')">
            <t-input v-model="form.oauthScopes" :placeholder="$t('toolbox.mcp.oauthScopesPlaceholder')" />
          </t-form-item>
          <t-form-item :label="$t('toolbox.mcp.oauthClientId')">
            <t-input v-model="form.oauthClientId" :placeholder="$t('toolbox.mcp.oauthClientIdPlaceholder')" />
          </t-form-item>
          <p class="mcp-dialog-hint">{{ $t('toolbox.mcp.oauthHint') }}</p>
        </template>
        <t-form-item v-if="form.transport === 'sse'" :label="$t('toolbox.mcp.sseReadTimeout')">
          <t-input-number v-model="form.sseReadTimeout" :min="1" :max="3600" :decimal-places="0" theme="row" />
        </t-form-item>
      </template>

      <t-form-item :label="$t('toolbox.mcp.timeout')">
        <t-input-number v-model="form.timeout" :min="1" :max="300" :decimal-places="0" theme="row" />
        <p class="mcp-dialog-hint">{{ $t('toolbox.mcp.timeoutHint') }}</p>
      </t-form-item>
    </t-form>

    <div class="mcp-dialog-actions">
      <t-button variant="outline" :disabled="saving" @click="close">{{ $t('common.cancel') }}</t-button>
      <t-button theme="primary" :loading="saving" @click="save">{{ $t('common.save') }}</t-button>
    </div>
  </EditorDialog>
</template>

<script setup lang="ts">
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  createMcpService, updateMcpService, type McpService, type McpServiceInput,
} from '@nexus-web/core/api/nexus-mcp'
import { configFromForm, formFromService, validateMcpForm } from './toolboxMcp'
import NexusMcpKeyValueEditor from './NexusMcpKeyValueEditor.vue'

const props = defineProps<{ visible: boolean, tenantId: string, service: McpService | null }>()
const emit = defineEmits<{
  (event: 'update:visible', value: boolean): void
  (event: 'saved', value: McpService): void
}>()
const { t } = useI18n()

const form = ref(formFromService(null))
const saving = ref(false)
const error = ref('')

const title = computed(() => t(props.service ? 'toolbox.mcp.editTitle' : 'toolbox.mcp.createTitle'))

function failure(cause: unknown): string {
  const record = (cause && typeof cause === 'object' ? cause : {}) as Record<string, unknown>
  return typeof record.message === 'string' && record.message ? record.message : t('toolbox.mcp.saveFailed')
}

// Opening the dialog always starts from the stored service, so a cancelled edit never leaks into the next one.
watch(() => props.visible, (visible) => {
  if (!visible) return
  form.value = formFromService(props.service)
  error.value = ''
})

function close() {
  if (saving.value) return
  emit('update:visible', false)
}

async function save() {
  if (saving.value) return
  const problem = validateMcpForm(form.value)
  if (problem) {
    error.value = t(`toolbox.mcp.${problem}`)
    return
  }
  saving.value = true
  error.value = ''
  const body: McpServiceInput = {
    name: form.value.name.trim(),
    description: form.value.description,
    transport: form.value.transport,
    config: configFromForm(form.value, props.service),
  }
  try {
    const saved = props.service
      ? await updateMcpService(props.tenantId, props.service.id, body)
      : await createMcpService(props.tenantId, body)
    emit('saved', saved)
    emit('update:visible', false)
  } catch (cause) {
    error.value = failure(cause)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.mcp-dialog-alert { margin-bottom: 12px; }
.mcp-dialog-transport { width: 240px; }
.mcp-dialog-hint { margin: 4px 0 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.mcp-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 8px; }
</style>
