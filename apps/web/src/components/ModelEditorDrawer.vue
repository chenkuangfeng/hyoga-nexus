<script setup lang="ts">
/**
 * Add or edit a configured model. Layout follows WeKnora's drawer: type first, then the provider,
 * model name and connection, advanced switches for chat models only, and a read-only summary of how
 * the model will be called. Testing uses the form as it stands, so nothing has to be saved first.
 *
 * `draft` is the composable's reactive state; the drawer edits it in place and emits `save` / `test`.
 * Keys typed here are cleared by the composable after each submission and are never displayed back.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { MODEL_TYPES, type ModelType, type ModelProvider, type TestResult } from '../types/modelSettings'
import { NEW_PROVIDER } from '../composables/useModelSettings'
import type { ModelPreset } from '../data/modelPresets'

const props = defineProps<{
  modelValue: boolean
  draft: {
    modelId: string; providerId: string; type: ModelType; name: string; newName: string; newBaseUrl: string
    newScope: 'personal' | 'tenant'; api_key: string; protocol: string; stream: boolean; text_tools: boolean
    temperature: number | undefined; reasoning_effort: string
  }
  providers: ModelProvider[]
  presets: ModelPreset[]
  busy: boolean
  testing: boolean
  testResult: TestResult | null
  canShareProviders: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: []
  test: []
  preset: [name: string]
}>()
const { t } = useI18n()

const editing = computed(() => !!props.draft.modelId)
const creatingProvider = computed(() => !editing.value && props.draft.providerId === NEW_PROVIDER)
const chat = computed(() => props.draft.type === 'chat')
const reasoningLevels = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
const protocolLabels: Record<string, string> = {
  openai_chat_completions: 'OpenAI Chat Completions',
  openai_responses: 'OpenAI Responses',
  anthropic_messages: 'Anthropic Messages',
}
const providerLabel = computed(() => props.providers.find(item => item.id === props.draft.providerId)?.name || '')
const canSave = computed(() => {
  if (!props.draft.name.trim() || props.busy) return false
  if (creatingProvider.value) return !!props.draft.newBaseUrl.trim() && !!props.draft.api_key
  return true
})
const canTest = computed(() => {
  if (!props.draft.name.trim() || props.testing || props.busy) return false
  if (creatingProvider.value) return !!props.draft.newBaseUrl.trim() && !!props.draft.api_key
  return true
})
</script>

<template>
  <el-drawer :model-value="modelValue" :title="editing ? t('modelPage.editModelTitle') : t('modelPage.addModelTitle')" size="min(520px, 96vw)" class="model-drawer" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @update:model-value="(value: boolean) => emit('update:modelValue', value)">
    <form class="drawer-form" @submit.prevent="emit('save')">
      <section class="drawer-section" aria-labelledby="drawer-type">
        <h3 id="drawer-type">{{ t('modelPage.modelType') }}</h3>
        <el-radio-group v-model="draft.type" :disabled="busy || editing" size="default" aria-labelledby="drawer-type">
          <el-radio-button v-for="type in MODEL_TYPES" :key="type" :value="type">{{ t(`modelPage.types.${type}`) }}</el-radio-button>
        </el-radio-group>
        <p v-if="!chat" class="muted">{{ t('modelPage.pendingNote') }}</p>
      </section>

      <section class="drawer-section" aria-labelledby="drawer-provider">
        <h3 id="drawer-provider">{{ t('modelPage.provider') }}</h3>
        <el-select v-if="!editing" id="drawer-provider-select" v-model="draft.providerId" :disabled="busy">
          <el-option v-for="item in providers" :key="item.id" :label="item.name" :value="item.id" />
          <el-option :label="t('modelPage.newProvider')" :value="NEW_PROVIDER" />
        </el-select>
        <p v-else class="muted">{{ providerLabel }}</p>
        <template v-if="creatingProvider">
          <el-form-item :label="t('modelPage.providerName')" label-for="drawer-new-name" class="stack">
            <el-input id="drawer-new-name" v-model="draft.newName" maxlength="160" :disabled="busy" :placeholder="t('modelPage.customProvider')" />
          </el-form-item>
          <el-form-item :label="t('modelPage.baseUrl')" label-for="drawer-new-url" class="stack">
            <el-input id="drawer-new-url" v-model="draft.newBaseUrl" maxlength="512" placeholder="https://api.example.com/v1" :disabled="busy" />
          </el-form-item>
          <el-form-item v-if="canShareProviders" :label="t('modelPage.scope')" label-for="drawer-new-scope" class="stack">
            <el-select id="drawer-new-scope" v-model="draft.newScope" :disabled="busy">
              <el-option :label="t('modelPage.scopePersonal')" value="personal" />
              <el-option :label="t('modelPage.scopeShared')" value="tenant" />
            </el-select>
          </el-form-item>
          <el-form-item label="API Key" label-for="drawer-new-key" class="stack">
            <el-input id="drawer-new-key" v-model="draft.api_key" type="password" autocomplete="new-password" maxlength="8192" :disabled="busy" />
          </el-form-item>
          <p class="muted">{{ t('modelPage.keyNote') }}</p>
        </template>
      </section>

      <section class="drawer-section" aria-labelledby="drawer-model">
        <h3 id="drawer-model">{{ t('modelPage.model') }}</h3>
        <el-form-item :label="t('modelPage.modelName')" label-for="drawer-model-name" class="stack">
          <el-input id="drawer-model-name" v-model="draft.name" maxlength="160" :disabled="busy" :placeholder="t('modelPage.modelNameHint')" />
        </el-form-item>
        <el-form-item v-if="presets.length" :label="t('modelPage.presets')" label-for="drawer-preset" class="stack">
          <el-select id="drawer-preset" :model-value="''" :disabled="busy" :placeholder="t('modelPage.presetPlaceholder')" @change="(value: string) => emit('preset', value)">
            <el-option v-for="preset in presets" :key="preset.name" :label="preset.name" :value="preset.name">
              <span>{{ preset.name }}</span>
              <el-tag v-if="preset.vision" size="small" class="tag">{{ t('modelPage.tagVision') }}</el-tag>
            </el-option>
          </el-select>
        </el-form-item>
      </section>

      <section v-if="chat" class="drawer-section" aria-labelledby="drawer-advanced">
        <h3 id="drawer-advanced">{{ t('modelPage.advanced') }}</h3>
        <el-form-item :label="t('modelPage.protocol')" class="stack">
          <el-select v-model="draft.protocol" :disabled="busy">
            <el-option v-for="(label, value) in protocolLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('modelPage.stream')" class="inline"><el-switch v-model="draft.stream" :disabled="busy" /></el-form-item>
        <el-form-item :label="t('modelPage.textTools')" class="inline"><el-switch v-model="draft.text_tools" :disabled="busy" /></el-form-item>
        <el-form-item :label="t('modelPage.temperature')" class="stack"><el-input-number v-model="draft.temperature" :min="0" :max="2" :step="0.1" :disabled="busy" /></el-form-item>
        <el-form-item :label="t('modelPage.reasoning')" class="stack">
          <el-select v-model="draft.reasoning_effort" clearable :disabled="busy">
            <el-option v-for="value in reasoningLevels" :key="value" :label="value" :value="value" />
          </el-select>
        </el-form-item>
      </section>

      <section class="drawer-section summary" aria-labelledby="drawer-call">
        <h3 id="drawer-call">{{ t('modelPage.callingTitle') }}</h3>
        <dl>
          <dt>{{ t('modelPage.callProtocol') }}</dt><dd>{{ protocolLabels[draft.protocol] || draft.protocol }}</dd>
          <template v-if="chat">
            <dt>{{ t('modelPage.stream') }}</dt><dd>{{ draft.stream ? t('modelPage.on') : t('modelPage.off') }}</dd>
            <dt>{{ t('modelPage.reasoning') }}</dt><dd>{{ draft.reasoning_effort || t('modelPage.notSet') }}</dd>
          </template>
        </dl>
      </section>

      <p v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'" role="status">{{ testResult.message }}</p>
    </form>
    <template #footer>
      <p class="muted footer-note">{{ t('modelPage.draftNote') }}</p>
      <div class="footer-actions">
        <el-button :disabled="!canTest" :loading="testing" @click="emit('test')">{{ t('modelPage.testDraft') }}</el-button>
        <el-button :disabled="busy" @click="emit('update:modelValue', false)">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="busy" :disabled="!canSave" @click="emit('save')">{{ t('modelPage.saveAndClose') }}</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-form { display: grid; gap: 20px; }
.drawer-section { display: grid; gap: 8px; }
.drawer-section h3 { margin: 0; font-size: 15px; }
.stack { margin-bottom: 8px; }
.stack :deep(.el-form-item__label) { padding-bottom: 4px; }
.inline { margin-bottom: 4px; }
.muted { color: var(--muted-text); font-size: 13px; line-height: 1.6; margin: 0; overflow-wrap: anywhere; }
.summary { padding: 12px 14px; border: 1px dashed var(--border); border-radius: 8px; }
.summary dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 16px; margin: 0; font-size: 13px; }
.summary dt { color: var(--muted-text); }
.summary dd { margin: 0; font-family: ui-monospace, monospace; overflow-wrap: anywhere; }
.tag { margin-left: 8px; }
.test-result { margin: 0; padding: 10px 12px; border-radius: 6px; font-size: 13px; overflow-wrap: anywhere; }
.test-result.ok { background: var(--selected); color: var(--el-color-success); }
.test-result.fail { background: var(--selected); color: var(--el-color-danger); }
.footer-note { margin-bottom: 12px; }
.footer-actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
</style>
