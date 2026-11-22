<script setup lang="ts">
/** 使用已保存的模型配置调试请求，临时输入和输出随抽屉关闭释放。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import { debugEnterpriseModel, type EnterpriseModelDebugResult } from '@nexus-web/core/api/enterprise-models'
import { copyWithToast } from '@nexus-web/core/utils/clipboard'
import { modelLabel, modelTypeIcons, modelTypes, type ModelCard } from './modelTypes'

const props = defineProps<{ tenant: string; models: ModelCard[] }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const availableTypes = computed(() => modelTypes.filter(type => props.models.some(card => card.model.model_type === type)))
const type = ref(availableTypes.value[0] ?? 'chat')
const selected = ref('')
const text = ref(''), documents = ref(''), system = ref('')
const file = ref<File>()
const temperature = ref<number>(), maxTokens = ref(512)
const result = ref<EnterpriseModelDebugResult | null>(null), error = ref(''), running = ref(false)
const models = computed(() => props.models.filter(card => card.model.model_type === type.value))
const options = computed(() => models.value.map(card => ({
  value: card.model.id, label: modelLabel(card.model),
})))
const candidates = computed(() => documents.value.split('\n').map(line => line.trim()).filter(Boolean))
const media = computed(() => type.value === 'vision' || type.value === 'speech')
const canRun = computed(() => !running.value && !!selected.value
  && (media.value ? !!file.value && file.value.size > 0 && file.value.size <= 10 * 1024 * 1024 : !!text.value.trim())
  && (type.value !== 'rerank' || (candidates.value.length > 0 && candidates.value.length <= 16
    && candidates.value.every(document => document.length <= 2000))))
let alive = true
watch(type, () => { selected.value = ''; file.value = undefined; result.value = null; error.value = '' })
watch(selected, () => { result.value = null; error.value = '' })
onBeforeUnmount(() => { alive = false })
const output = computed(() => {
  if (result.value && 'text' in result.value) return result.value.text
  return result.value ? JSON.stringify(result.value, null, 2) : ''
})

async function run() {
  const card = models.value.find(item => item.model.id === selected.value)
  if (!canRun.value || !card) return
  result.value = null
  error.value = ''
  running.value = true
  try {
    const reply = await debugEnterpriseModel(props.tenant, card.provider.id, card.model.id, {
      text: text.value.trim(),
      ...(type.value === 'rerank' ? { documents: candidates.value } : {}),
      ...(type.value === 'chat' ? { system_prompt: system.value, max_output_tokens: maxTokens.value,
        temperature: temperature.value } : {}),
    }, media.value ? file.value : undefined)
    if (alive) {
      if (reply.ok) result.value = reply.result
      else error.value = reply.message
    }
  } catch {
    if (alive) error.value = t('modelSettings.debug.requestFailed')
  } finally {
    if (alive) running.value = false
  }
}
</script>

<template>
  <SettingDrawer :visible="true" :title="t('modelSettings.debug.title')" :description="t('modelSettings.debug.description')"
    icon="play-circle-stroke" width="560px" storage-key="setting-drawer:width:model-debug"
    :confirm-text="t('modelSettings.debug.run')" :confirm-loading="running" :confirm-disabled="!canRun"
    :cancel-text="t('common.close')" @update:visible="value => { if (!value) emit('close') }" @confirm="run" @cancel="emit('close')">
    <template v-if="result" #footer-left>
      <t-button variant="outline" @click="copyWithToast(output, 'common.copied')">{{ t('modelSettings.debug.copyResult') }}</t-button>
    </template>
    <template v-if="error" #footer-extra><t-alert theme="error" :message="error" /></template>
    <div class="debug-form" :inert="running || undefined">
      <section class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ t('modelSettings.debug.groupModel') }}</h4>
        <div v-if="availableTypes.length > 1" class="model-type-options" role="group" :aria-label="t('modelSettings.debug.modelType')">
          <button v-for="value in availableTypes" :key="value" type="button" class="model-type-option"
            :class="{ 'is-active': type === value }" :aria-pressed="type === value" @click="type = value">
            <t-icon :name="modelTypeIcons[value]" class="model-type-option__icon" aria-hidden="true" />
            {{ t('adminModels.types.' + value) }}
          </button>
        </div>
        <label>{{ t('modelSettings.debug.model') }}
          <t-select v-model="selected" :options="options" filterable
            :placeholder="t('modelSettings.debug.modelPlaceholder')" />
        </label>
      </section>
      <template v-if="selected">
        <section class="setting-drawer__section">
          <h4 class="setting-drawer__section-title">{{ t('modelSettings.debug.groupInput') }}</h4>
          <label v-if="type !== 'speech'">{{ t(type === 'vision' ? 'modelSettings.debug.vlmPrompt'
            : type === 'embedding' ? 'modelSettings.debug.embeddingInput' : 'modelSettings.debug.query') }}
            <t-textarea v-model="text" :maxlength="8000" :autosize="{ minRows: 4, maxRows: 8 }" />
          </label>
          <label v-if="media">
            {{ t(type === 'vision' ? 'modelSettings.debug.imageFile' : 'modelSettings.debug.audioFile') }} · ≤10 MiB
            <input :key="type" type="file" :accept="type === 'vision' ? '.png,.jpg,.jpeg,.webp' : '.wav,.mp3,.m4a,.flac,.ogg,.webm'"
              @change="file = ($event.target as HTMLInputElement).files?.[0]" />
          </label>
          <label v-if="type === 'rerank'">{{ t('modelSettings.debug.documents') }}
            <t-textarea v-model="documents" :maxlength="32000" :autosize="{ minRows: 4, maxRows: 8 }"
              :placeholder="t('modelSettings.debug.documentsPlaceholder')" />
            <small>{{ t('modelSettings.debug.documentsHint') }}</small>
          </label>
        </section>
        <section v-if="type === 'chat'" class="setting-drawer__section">
          <h4 class="setting-drawer__section-title">{{ t('modelSettings.debug.parameters') }}</h4>
          <div class="parameter-grid">
            <label>Temperature<t-input-number v-model="temperature" :min="0" :max="2" :step="0.1" /></label>
            <label>Max Tokens<t-input-number v-model="maxTokens" :min="1" :max="2048" :step="64" /></label>
          </div>
          <label>{{ t('modelSettings.debug.systemPrompt') }}
            <t-textarea v-model="system" :maxlength="4000" :autosize="{ minRows: 2, maxRows: 4 }" />
          </label>
        </section>
      </template>
      <section v-if="result" class="setting-drawer__section" aria-live="polite">
        <h4 class="setting-drawer__section-title">{{ t('modelSettings.debug.groupResult') }}</h4>
        <p v-if="result.type === 'embedding'">{{ t('modelSettings.debug.metrics.dimension') }} · {{ result.dimension }}</p>
        <pre class="debug-output">{{ output }}</pre>
      </section>
    </div>
  </SettingDrawer>
</template>

<style scoped lang="less">
@import './ModelEditor.reference.less';

.debug-form label { display: grid; gap: 8px; margin-top: 12px; }
.parameter-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.debug-output {
  padding: 12px;
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-secondarycontainer);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
