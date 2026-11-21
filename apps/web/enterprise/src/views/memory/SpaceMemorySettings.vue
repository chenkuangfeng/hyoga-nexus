<template>
  <!-- Space memory settings on the Nexus API (openspec 2026-11-05-memory-switches 2.2, 2026-11-06-memory-evolution
       2.8 / 5.5). Template, class names and styles follow WeKnora MemoryWorkspaceSettings.vue; settings Nexus does
       not have stay in place, disabled and marked as planned (decision 4 of the switches proposal). -->
  <div class="memory-workspace-settings">
    <div class="section-header">
      <h2>{{ t('memoryWorkspaceSettings.title') }}</h2>
      <p class="section-description">{{ t('memoryWorkspaceSettings.description') }}</p>
    </div>

    <div class="intro">
      <t-icon name="info-circle" class="intro-icon" />
      <div>
        <p class="intro-title">{{ t('memoryWorkspaceSettings.introTitle') }}</p>
        <p class="intro-desc">{{ t('memoryWorkspaceSettings.introDescription') }}</p>
      </div>
    </div>

    <p v-if="loadError" class="load-error" role="alert">{{ loadError }}</p>
    <p v-else-if="!canEdit && loaded" class="readonly-hint">{{ t('nexusMemory.readonlyHint') }}</p>

    <div v-if="loaded" class="settings-group"><t-button v-if="canEdit" :loading="saving" @click="save">{{ t('common.save') }}</t-button>
      <div class="setting-row">
        <div class="setting-info">
          <label>{{ t('memoryWorkspaceSettings.enableLabel') }}</label>
          <p class="desc">{{ t('memoryWorkspaceSettings.enableDescription') }}</p>
        </div>
        <div class="setting-control">
          <t-switch v-model="config.enabled" :disabled="!canEdit"  />
        </div>
      </div>

      <div v-if="config.enabled" class="setting-row">
        <div class="setting-info">
          <label>{{ t('memoryWorkspaceSettings.writeModeLabel') }}</label>
          <p class="desc">{{ t('memoryWorkspaceSettings.writeModeDescription') }}</p>
          <p class="desc hint">
            {{ config.write_mode === 'auto' ? t('memoryWorkspaceSettings.writeModeAutoHint')
              : t('memoryWorkspaceSettings.writeModeExplicitHint') }}
          </p>
        </div>
        <div class="setting-control">
          <t-radio-group v-model="config.write_mode" :disabled="!canEdit" >
            <t-radio-button value="explicit">{{ t('memoryWorkspaceSettings.writeModeExplicit') }}</t-radio-button>
            <t-radio-button value="auto">{{ t('memoryWorkspaceSettings.writeModeAuto') }}</t-radio-button>
          </t-radio-group>
        </div>
      </div>

      <!-- WeKnora chooses the extraction model per space; Nexus keeps it per member in "my memory". -->
      <div v-if="config.enabled && config.write_mode === 'auto'" class="setting-row">
        <div class="setting-info">
          <label>{{ t('memoryWorkspaceSettings.extractModelLabel') }} <span class="planned-tag">{{ t('nexusMemory.memberSetting') }}</span></label>
          <p class="desc">{{ t('nexusMemory.extractModelPerMember') }}</p>
        </div>
      </div>

      <div v-for="item in plannedRows" v-show="config.enabled" :key="item" class="setting-row is-planned">
        <div class="setting-info">
          <label>{{ t(`memoryWorkspaceSettings.${item}Label`) }} <span class="planned-tag">{{ t('nexusMemory.planned') }}</span></label>
          <p class="desc">{{ t(`memoryWorkspaceSettings.${item}Description`) }}</p>
        </div>
      </div>

      <div v-if="config.enabled" class="setting-row">
        <div class="setting-info">
          <label>{{ t('memoryWorkspaceSettings.embeddingModelLabel') }}</label>
          <p class="desc">{{ t('nexusMemory.embeddingModelDesc') }}</p>
        </div>
        <div class="setting-control" style="min-width: 280px">
          <t-select v-model="config.embedding_model_version_id" :disabled="!canEdit" clearable
            :placeholder="t('nexusMemory.embeddingNone')" >
            <t-option v-for="model in embeddingModels" :key="model.version_id" :value="model.version_id" :label="model.name" />
          </t-select>
        </div>
      </div>

      <div v-if="config.enabled && config.write_mode === 'auto'" class="setting-row">
        <div class="setting-info">
          <label>{{ t('memoryWorkspaceSettings.interestThresholdLabel') }}</label>
          <p class="desc">{{ t('memoryWorkspaceSettings.interestThresholdDescription') }}</p>
        </div>
        <div class="setting-control">
          <t-input-number v-model="config.interest_threshold" :min="2" :max="10" :step="1" :disabled="!canEdit"
             />
        </div>
      </div>

      <div v-if="config.enabled && config.write_mode === 'auto'" class="setting-row instructions-row">
        <div class="setting-info">
          <label>{{ t('memoryWorkspaceSettings.instructionsLabel') }}</label>
          <p class="desc">{{ t('memoryWorkspaceSettings.instructionsDescription') }}</p>
        </div>
        <div class="setting-control instructions-control">
          <t-textarea v-model="config.extract_instructions" :autosize="{ minRows: 3, maxRows: 8 }" :maxlength="1000"
            :disabled="!canEdit" :placeholder="t('memoryWorkspaceSettings.instructionsPlaceholder')" />
        </div>
      </div>

      <div v-if="config.enabled" class="setting-row">
        <div class="setting-info">
          <label>{{ t('nexusMemory.providerLabel') }}</label>
          <p class="desc">{{ t('nexusMemory.providerDesc') }}</p>
        </div>
        <div class="setting-control">
          <span class="provider-value">{{ provider || t('nexusMemory.providerBuiltin') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch, reactive, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getSpaceMemorySettings, updateSpaceMemorySettings, type SpaceMemorySettingsInput } from '@nexus-web/core/api/nexus-memory'
import { getModelSettings, type NexusModel } from '@nexus-web/core/api/nexus-models'

const { t } = useI18n()
const authStore = useAuthStore()

/** WeKnora settings with no Nexus backend: shown disabled as planned. */
const plannedRows = ['extractDelay', 'extractMinInterval', 'conditioning', 'maxItems'] as const

const config = reactive<SpaceMemorySettingsInput>({
  enabled: true, write_mode: 'auto', extract_instructions: '', embedding_model_version_id: null, interest_threshold: 3,
})
const canEdit = ref(false)
const loaded = ref(false)
const loadError = ref('')
const provider = ref<string | null>(null)
const embeddingModels = ref<NexusModel[]>([])
const saving = ref(false)
let epoch = 0
async function load() {
  const current = ++epoch, tenantId = authStore.effectiveTenantId
  loaded.value = false; canEdit.value = false; loadError.value = ''; embeddingModels.value = []
  if (!tenantId) return
  try {
    const settings = await getSpaceMemorySettings(tenantId)
    if (current !== epoch) return
    Object.assign(config, settings); canEdit.value = settings.can_edit; provider.value = settings.memory_provider; loaded.value = true
    try { const models = await getModelSettings(tenantId, true); if (current === epoch) embeddingModels.value = models.providers.flatMap(p => p.models).filter(m => m.model_type === 'embedding') } catch { /* 模型目录失败不影响已有记忆规则。 */ }
  } catch { if (current === epoch) loadError.value = t('nexusMemory.loadFailed') }
}
async function save() {
  const tenantId = authStore.effectiveTenantId, current = epoch
  if (!tenantId || !canEdit.value || saving.value) return
  const body = { enabled: config.enabled, write_mode: config.write_mode, extract_instructions: config.extract_instructions, embedding_model_version_id: config.embedding_model_version_id || null, interest_threshold: config.interest_threshold }
  saving.value = true
  try { await updateSpaceMemorySettings(tenantId, body); if (current === epoch) MessagePlugin.success(t('memoryWorkspaceSettings.toasts.saveSuccess')) }
  catch { if (current === epoch) loadError.value = t('nexusMemory.loadFailed') }
  finally { if (current === epoch) saving.value = false }
}
watch(() => `${authStore.effectiveTenantId}:${authStore.user?.id}:${authStore.currentTenantRole}`, () => { saving.value = false; void load() }, { immediate: true })
onBeforeUnmount(() => epoch++)
</script>

<style lang="less" scoped>
@import (reference) '@nexus-web/core/styles/settings-section.less';

.memory-workspace-settings {
  width: 100%;
}

.section-header {
  .settings-section-header();
}

.intro {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  margin-bottom: 8px;
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-secondarycontainer);
}

.intro-icon {
  color: var(--td-brand-color);
  margin-top: 2px;
  flex-shrink: 0;
}

.intro-title {
  margin: 0 0 4px 0;
  font-size: var(--app-text-base);
  font-weight: 500;
  color: var(--td-text-color-primary);
}

.intro-desc {
  margin: 0;
  font-size: var(--app-text-md);
  line-height: 1.6;
  color: var(--td-text-color-secondary);
}

.load-error {
  color: var(--td-error-color);
}

.readonly-hint {
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-md);
}

.settings-group {
  display: flex;
  flex-direction: column;
}

.setting-row {
  .setting-row();
}

.setting-row.is-planned {
  opacity: 0.6;
}

.setting-info {
  .setting-info();

  .hint {
    margin-top: 4px !important;
    color: var(--td-text-color-placeholder);
  }
}

.setting-control {
  .setting-control();
}

.planned-tag {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: var(--app-radius-sm);
  font-size: var(--app-text-sm);
  font-weight: 400;
  color: var(--td-text-color-secondary);
  background: var(--td-bg-color-secondarycontainer);
}

.provider-value {
  color: var(--td-text-color-secondary);
}

.instructions-row {
  flex-direction: column;
  align-items: stretch;

  .setting-info {
    max-width: 100%;
    padding-right: 0;
    margin-bottom: 10px;
  }
}

.instructions-control {
  width: 100%;
  justify-content: stretch;
}
</style>
