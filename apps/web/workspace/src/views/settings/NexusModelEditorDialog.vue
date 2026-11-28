<template>
  <!--
    Add / edit a model on Nexus. Structure and classes follow WeKnora `components/ModelEditorDialog.vue`
    (centered SettingDrawer, type chooser, provider section, connection test in the footer).
    The provider dropdown lists the caller's manageable providers plus "custom (OpenAI-compatible)",
    which creates a provider on save (spec model-management R5).
  -->
  <SettingDrawer placement="center" :visible="visible" :title="editing ? $t('model.editor.editTitle') : $t('model.editor.addTitle')"
    :description="$t('nexusModels.testHint')" :icon="typeIcon(form.model_type)" :confirm-loading="saving" :cancel-disabled="saving"
    :confirm-text="$t('model.editor.saveAndClose')" :close-on-overlay-click="!saving" :close-on-esc-keydown="!saving"
    @update:visible="(v: boolean) => emit('update:visible', v)" @confirm="save" @cancel="emit('update:visible', false)">

    <template v-if="form.model_type === 'chat'" #footer-left>
      <t-button variant="outline" :loading="checking" :disabled="saving || !form.model_name.trim() || !form.base_url.trim()"
        @click="testConnection">
        <template #icon>
          <t-icon v-if="!checking && tested && testOk" name="check-circle-filled" class="status-icon available" />
          <t-icon v-else-if="!checking && tested && !testOk" name="close-circle-filled" class="status-icon unavailable" />
        </template>
        {{ checking ? $t('model.editor.testing') : $t('model.editor.testConnection') }}
      </t-button>
      <span v-if="tested" :class="['connection-status', testOk ? 'success' : 'error']">
        {{ testMessage || (testOk ? $t('model.editor.connectionSuccess') : $t('model.editor.connectionFailed')) }}
      </span>
    </template>

    <t-form :inert="saving || undefined" :data="form" layout="vertical">
      <section v-if="!editing" class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ $t('model.editor.sectionType') }}</h4>
        <div class="model-type-options" role="radiogroup" :aria-label="$t('model.editor.typeLabel')">
          <button v-for="type in NEXUS_TYPES" :key="type" type="button" class="model-type-option"
            :class="{ 'is-active': form.model_type === type }" role="radio" :aria-checked="form.model_type === type"
            @click="form.model_type = type">
            <t-icon :name="typeIcon(type)" class="model-type-option__icon" />
            <span class="model-type-option__label">{{ typeLabel(type) }}</span>
          </button>
        </div>
      </section>
      <section v-else class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ $t('model.editor.sectionType') }}</h4>
        <p class="form-desc">{{ typeLabel(form.model_type) }} · {{ $t('nexusModels.typeLocked') }}</p>
      </section>

      <section class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ $t('model.editor.sectionProvider') }}</h4>

        <div v-if="!editing" class="form-item">
          <label class="form-label">{{ $t('model.editor.providerLabel') }}</label>
          <t-select v-model="form.provider_id">
            <t-option v-for="provider in providers" :key="provider.id" :value="provider.id"
              :label="`${provider.name} · ${$t(`nexusModels.scope.${provider.scope}`)}`" />
            <t-option value="" :label="$t('nexusModels.providerCustom')" />
          </t-select>
          <p v-if="form.provider_id" class="form-desc">{{ $t('nexusModels.existingProviderHint') }}</p>
        </div>

        <template v-if="editsProvider">
          <div class="form-item">
            <label class="form-label required">{{ $t('nexusModels.providerName') }}</label>
            <t-input v-model="form.provider_name" :maxlength="160" :placeholder="$t('nexusModels.providerNamePlaceholder')" />
          </div>
          <div class="form-item">
            <label class="form-label required">{{ $t('model.editor.baseUrlLabel') }}</label>
            <t-input v-model="form.base_url" :maxlength="512" :placeholder="$t('nexusModels.baseUrlPlaceholder')" />
          </div>
          <div class="form-item">
            <label class="form-label" :class="{ required: !editing }">{{ $t('nexusModels.apiKey') }}</label>
            <t-input v-model="form.api_key" type="password" class="api-key-input" autocomplete="new-password" spellcheck="false"
              :placeholder="$t('nexusModels.apiKeyPlaceholder')">
              <template #prefix-icon><t-icon name="lock-on" /></template>
            </t-input>
            <p v-if="editing" class="form-desc">{{ $t('nexusModels.apiKeyKeep') }}</p>
            <p v-if="editing && editing.provider.models.length > 1" class="form-desc">
              {{ $t('nexusModels.sharedKeyHint', { count: editing.provider.models.length }) }}
            </p>
          </div>
          <div v-if="!editing" class="form-item">
            <label class="form-label">{{ $t('nexusModels.scopeLabel') }}</label>
            <t-radio-group v-model="form.scope">
              <t-radio-button value="personal">{{ $t('nexusModels.scope.personal') }}</t-radio-button>
              <t-radio-button value="tenant" :disabled="!settings.can_manage_tenant">{{ $t('nexusModels.scope.tenant') }}</t-radio-button>
            </t-radio-group>
          </div>
        </template>

        <div class="form-item">
          <label class="form-label required">{{ $t('model.modelName') }}</label>
          <t-input v-model="form.model_name" :maxlength="160" :placeholder="$t('nexusModels.modelNamePlaceholder')"
            clearable autocomplete="off" spellcheck="false" />
        </div>
      </section>

      <section v-if="form.model_type === 'chat'" class="setting-drawer__section">
        <h4 class="setting-drawer__section-title">{{ $t('model.editor.sectionAdvanced') }}</h4>
        <div class="form-item">
          <label class="form-label">{{ $t('nexusModels.protocol') }}</label>
          <t-select v-model="form.protocol">
            <t-option value="openai_chat_completions" label="OpenAI Chat Completions" />
            <t-option value="openai_responses" label="OpenAI Responses" />
            <t-option value="anthropic_messages" label="Anthropic Messages" />
          </t-select>
        </div>
        <div class="form-item">
          <label class="form-label">{{ $t('nexusModels.contextWindowLabel') }}</label>
          <t-input-number v-model="form.context_window_k" :min="1" :max="2000" :step="1" theme="column">
            <template #suffix> K</template>
          </t-input-number>
          <p class="form-desc">{{ $t('nexusModels.contextWindowDesc') }}</p>
        </div>
      </section>
    </t-form>
  </SettingDrawer>
</template>

<script setup lang="ts">
/**
 * Props: `visible` (v-model), `tenantId`, `settings` (current model-settings view), `editing`
 * (card being edited, or null), `initialType` (type preselected when adding). Emits `saved`.
 *
 * The API Key lives only in this component's state until submit and is cleared afterwards.
 * A provider created by a failed attempt is remembered so a retry does not create another (R5).
 */
import { computed, reactive, ref, watch, onBeforeUnmount } from 'vue'
import type { ModelFormDraft } from '@/stores/pageDrafts'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import {
  addModel, createProvider, editModel, testDraftConnection, updateProvider,
  type ModelSettingsView, type NexusModelType,
} from '@nexus-web/core/api/nexus-models'
import { manageableProviders, modelOptionsFor, NEXUS_TYPES, planSave, type ModelCard, type ModelEditorForm } from './nexusModelCards'

const props = defineProps<{
  visible: boolean
  tenantId: string
  settings: ModelSettingsView
  editing: ModelCard | null
  initialType: NexusModelType
  draft?: ModelFormDraft | null
}>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void; (e: 'saved'): void }>()
const { t } = useI18n()

let epoch = 0, alive = true
onBeforeUnmount(() => { alive = false; epoch++; form.api_key = '' })
const saving = ref(false)
const checking = ref(false)
const tested = ref(false)
const testOk = ref(false)
const testMessage = ref('')
const createdProviderId = ref('')
const form = reactive<ModelEditorForm>(emptyForm())

const providers = computed(() => manageableProviders(props.settings))
/** Provider fields are shown for a custom provider (add) and always when editing. */
const editsProvider = computed(() => !!props.editing || !form.provider_id)

const TYPE_ICON: Record<NexusModelType, string> = {
  chat: 'chat', embedding: 'chart-bubble', rerank: 'filter-sort', vision: 'image', speech: 'sound',
}
function typeIcon(type: NexusModelType): string { return TYPE_ICON[type] }
function typeLabel(type: NexusModelType): string {
  return t(`modelSettings.typeShort.${type === 'vision' ? 'vllm' : type === 'speech' ? 'asr' : type}`)
}

function emptyForm(): ModelEditorForm {
  return { model_type: 'chat', model_name: '', provider_id: '', provider_name: '', base_url: '', api_key: '',
    scope: 'personal', protocol: 'openai_chat_completions', context_window_k: 200 }
}

watch(() => [props.visible, props.tenantId, props.draft, props.editing] as const, ([visible]) => {
  epoch++; saving.value = false; checking.value = false
  if (!visible) { form.api_key = ''; return }
  tested.value = false
  testMessage.value = ''
  createdProviderId.value = ''
  const card = props.editing
  Object.assign(form, emptyForm(), card ? {
    model_type: card.type, model_name: card.model.name, provider_id: card.provider.id,
    provider_name: card.provider.name, base_url: card.provider.base_url, scope: card.provider.scope,
    protocol: String(card.model.options.protocol || 'openai_chat_completions'),
    context_window_k: typeof card.model.options.context_window_k === 'number' ? card.model.options.context_window_k : 200,
  } : {
    model_type: props.draft ? (props.draft.type === 'vllm' ? 'vision' : props.draft.type === 'asr' ? 'speech' : props.draft.type) : props.initialType,
    model_name: props.draft?.model_name || '', provider_name: props.draft?.provider || '', base_url: props.draft?.base_url || '',
  })
}, { immediate: true })

// Any change to the tested fields invalidates the previous result.
watch(() => [form.base_url, form.model_name, form.api_key, form.provider_id, form.protocol], () => { tested.value = false })

function errorMessage(error: unknown, fallback: string): string {
  const message = error && typeof error === 'object' ? (error as { message?: unknown }).message : undefined
  return typeof message === 'string' && message ? message : fallback
}

function selectedProvider() {
  return props.editing?.provider || providers.value.find(provider => provider.id === form.provider_id)
}

async function testConnection() {
  if (checking.value || saving.value || !props.visible || !alive) return
  const current = epoch, tenant = props.tenantId
  checking.value = true
  try {
    const provider = selectedProvider()
    const result = await testDraftConnection(tenant, {
      scope: provider?.scope || form.scope,
      base_url: provider && !props.editing ? provider.base_url : form.base_url.trim(),
      model_name: form.model_name.trim(), model_type: form.model_type,
      options: modelOptionsFor(form, props.editing?.model.options), provider_id: provider?.id, api_key: form.api_key || undefined,
    })
    if (current !== epoch || !alive) return
    testOk.value = result.ok
    // The code identifies the cause precisely when reporting problems; the message stays human-readable.
    testMessage.value = result.ok || !result.code ? result.message : `${result.message}（${result.code}）`
  } catch (error) {
    if (current !== epoch || !alive) return
    testOk.value = false
    testMessage.value = errorMessage(error, t('model.editor.connectionFailed'))
  } finally {
    if (current === epoch && alive) { tested.value = true; checking.value = false }
  }
}

function validate(): string {
  if (!form.model_name.trim()) return t('model.modelName')
  if (editsProvider.value && (!form.provider_name.trim() || !form.base_url.trim())) return t('nexusModels.providerName')
  if (!props.editing && !form.provider_id && !createdProviderId.value && !form.api_key) return t('nexusModels.apiKey')
  return ''
}

async function save() {
  if (saving.value || checking.value || !props.visible || !alive) return
  const current = epoch, tenant = props.tenantId
  const missing = validate()
  if (missing) { MessagePlugin.warning(missing); return }
  saving.value = true
  const model = { name: form.model_name.trim(), model_type: form.model_type, options: modelOptionsFor(form, props.editing?.model.options) }
  const providerBody = { name: form.provider_name.trim(), base_url: form.base_url.trim(), scope: form.scope, api_key: form.api_key }
  try {
    const plan = planSave(form, props.editing, createdProviderId.value)
    if (plan.kind === 'edit') {
      if (plan.updateProvider) await updateProvider(tenant, plan.providerId, providerBody)
      if (current !== epoch || !alive) return
      await editModel(tenant, plan.providerId, plan.profileId, model)
    } else {
      let providerId = plan.kind === 'add' ? plan.providerId : ''
      if (plan.kind === 'create-provider-then-add') {
        providerId = (await createProvider(tenant, providerBody)).id
        if (current !== epoch || !alive) return
        createdProviderId.value = providerId
      }
      await addModel(tenant, providerId, model)
    }
    if (current !== epoch || !alive) return
    form.api_key = ''
    MessagePlugin.success(t('nexusModels.saved'))
    emit('saved')
    emit('update:visible', false)
  } catch (error) {
    if (current === epoch && alive) MessagePlugin.error(errorMessage(error, t('nexusModels.saveFailed')))
  } finally {
    providerBody.api_key = ''
    if (current === epoch && alive) { saving.value = false; form.api_key = '' }
  }
}
</script>

<!-- Copied from WeKnora components/ModelEditorDialog.vue -->
<style lang="less" scoped>
.provider-doc-link {
  margin-top: 6px;
}

.provider-doc-link a,
.compat-doc-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--td-text-color-link);
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

// 原生 t-form-item 容器置空（本组件使用自定义 .form-item + 手写 label）
:deep(.t-form) {
  .t-form-item {
    display: none;
  }
}

// 表单项样式
.form-item {
  // No bottom margin — vertical rhythm is owned by the parent
  // .setting-drawer__section's `gap`. That keeps the spacing inside a section
  // tight and the gap between sections visually distinct.
  margin-bottom: 0;
}

.form-label {
  display: block;
  margin-bottom: 6px;
  font-size: var(--app-text-md);
  font-weight: 500;
  color: var(--td-text-color-primary);
  line-height: 1.4;

  // TDesign-style required marker: leading asterisk before the label text,
  // matching the rest of the app's <t-form-item required ...> appearance.
  &.required::before {
    content: '*';
    color: var(--td-error-color);
    margin-right: 4px;
    font-weight: 500;
    line-height: 1;
  }
}

.model-type-options,
.source-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

// 「模型类型」和「模型来源」都是单选，就用同一种按钮。模型来源原本是灰底轨道
// 的 segmented：#e7e7e7 的轨道在浅色表单里是一整块深灰，白色药丸又浮不起来，
// 而且紧挨着的模型类型是另一套长相。取消轨道后两组自然成为一族。
.model-type-option,
.source-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  padding: 6px 12px;
  min-height: 32px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-container);
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-md);
  line-height: 1.4;
  cursor: pointer;
  transition: border-color var(--app-motion-fast) ease, color var(--app-motion-fast) ease, background var(--app-motion-fast) ease;

  &__icon {
    font-size: var(--app-text-lg);
    flex-shrink: 0;
  }

  &__label {
    white-space: nowrap;
  }

  &:hover:not(.is-active) {
    border-color: var(--td-brand-color-3);
    color: var(--td-text-color-primary);
  }

  // 选中态与下面的「模型来源」分段一致：白底 + 主题色描边 + 主题色文字。
  // 原先还铺了一层 10% 的主题色底，五个按钮里那一块是整屏最重的色块，而且
  // 和下拉里刚去掉的整行绿底是同一个毛病。
  &.is-active {
    border-color: var(--td-brand-color);
    background: var(--td-bg-color-container);
    color: var(--td-brand-color);
    font-weight: 500;
  }

  &:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 2px;
  }
}



.source-option {
  // 外观来自上面那条共用规则；这里只补禁用态（Ollama 未就绪 / rerank 不支持）。
  &.is-disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
}

// 输入框样式：只在最外层 .t-input 上调字号，避免在内部 wrap/inner 上重复加边
// 与 border-radius，造成视觉上"嵌套圆角容器"的错觉
:deep(.t-input),
:deep(.t-select),
:deep(.t-textarea),
:deep(.t-input-number) {
  width: 100%;
  font-size: var(--app-text-md);
}

// 厂商选择器样式 — 移至非 scoped 块，因为 t-select popup 渲染到 body 下
// .provider-option 样式见文件末尾

// 复选框
:deep(.t-checkbox) {
  font-size: var(--app-text-md);

  .t-checkbox__label {
    font-size: var(--app-text-md);
    color: var(--td-text-color-primary);
  }
}

// API Key 输入：前置 lock 图标 + 后置可点击的"显示/隐藏"小眼睛。
// TDesign 默认会让 prefix-icon 显示成灰色，这里没动；suffix 上的眼睛
// 用 placeholder 色，hover 时切到主文本色，避免抢戏。
.api-key-input {
  :deep(.t-input__prefix) {
    color: var(--td-text-color-placeholder);
  }

  :deep(.t-input__suffix) {
    color: var(--td-text-color-placeholder);
  }

}

// API 测试区域 — 弱卡片化：用浅底 + dashed 边把"操作 + 反馈"框成一块，
// 让用户视觉上把它当成一个独立的"动作单元"，而不是又一个普通字段。
// （历史样式保留：仅当某个分支仍以 inline 方式渲染测试块时使用；当前 RemoteAPI
// 测试已上移到 SettingDrawer footer-left 槽，主流程不再走这块。）
.api-test-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--td-bg-color-container-hover);
  border: 1px dashed var(--td-component-stroke);
  border-radius: var(--app-radius-md);

  .test-message {
    font-size: var(--app-text-md);
    line-height: 1.5;
    flex: 1;

    &.success {
      color: var(--td-brand-color-active);
    }

    &.error {
      color: var(--td-error-color);
    }
  }

  :deep(.t-button) {
    min-width: 88px;
    height: 32px;
    font-size: var(--app-text-md);
    border-radius: var(--app-radius-sm);
    flex-shrink: 0;
  }

  .status-icon {
    font-size: var(--app-text-xl);
    flex-shrink: 0;

    &.available {
      color: var(--td-brand-color);
    }

    &.unavailable {
      color: var(--td-error-color);
    }
  }
}

.connection-status {
  font-size: var(--app-text-sm);
  &.success { color: var(--td-brand-color-active); }
  &.error { color: var(--td-error-color); }
}

.connection-hint {
  margin: 0 0 8px;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-sm);
  line-height: 1.5;
}

.connection-result {
  margin-bottom: 8px;
  padding: 10px 12px;
  border: 1px solid var(--td-error-color-3);
  border-radius: var(--td-radius-default);
  background: var(--td-error-color-1);
  color: var(--td-error-color);
  font-size: var(--app-text-sm);
  text-align: left;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  &__details {
    max-height: min(160px, 20vh);
    overflow: auto;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    line-height: 1.5;
    user-select: text;
  }
}

// Status icon variant used inside the footer button.
.status-icon {
  font-size: var(--app-text-xl);
  flex-shrink: 0;

  &.available {
    color: var(--td-brand-color);
  }

  &.unavailable {
    color: var(--td-error-color);
  }
}

// WeKnoraCloud 提示信息
.weknoracloud-hint {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: var(--app-radius-md);
  font-size: var(--app-text-md);
  color: var(--td-text-color-secondary);
  line-height: 1.5;

  // Theming via tokens so the warn/ok states track light/dark switches
  // instead of fighting hardcoded `#fff7ed` etc.
  &--ok {
    background: var(--td-success-color-light);
    border: 1px solid var(--td-success-color-focus);
  }

  &--warn {
    background: var(--td-warning-color-light);
    border: 1px solid var(--td-warning-color-focus);
    border-left: 3px solid var(--td-warning-color);
  }

  .hint-icon {
    font-size: var(--app-text-xl);
    flex-shrink: 0;
    margin-top: 2px;

    &--ok {
      color: var(--td-success-color);
    }

    &--warn {
      color: var(--td-warning-color);
    }

    &--loading {
      color: var(--td-text-color-placeholder);
    }
  }
}

// Ollama 模型选择器样式
.model-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 4px 0;

  .downloaded-icon {
    font-size: var(--app-text-base);
    color: var(--td-brand-color);
    flex-shrink: 0;
  }

  .download-icon {
    font-size: var(--app-text-base);
    color: var(--td-brand-color);
    flex-shrink: 0;
  }

  .model-name {
    flex: 1;
    font-size: var(--app-text-md);
    color: var(--td-text-color-primary);
  }

  .model-size {
    font-size: var(--app-text-sm);
    color: var(--td-text-color-placeholder);
    margin-left: auto;
  }

  &.download {
    .model-name {
      color: var(--td-brand-color);
      font-weight: 500;
    }
  }
}

// 下载进度后缀样式
.download-suffix {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 4px;

  .spinning {
    animation: wk-spin 1s linear infinite;
    font-size: var(--app-text-base);
    color: var(--td-brand-color);
  }

  .progress-text {
    font-size: var(--app-text-sm);
    font-weight: 500;
    color: var(--td-brand-color);
  }
}

// 下载中的选择框进度条效果
:deep(.t-select.downloading) {
  .t-input {
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: var(--progress, 0%);
      background: linear-gradient(90deg, color-mix(in srgb, var(--td-brand-color) 8%, transparent), color-mix(in srgb, var(--td-brand-color) 15%, transparent));
      transition: width var(--app-motion-slow) ease;
      z-index: 0;
      border-radius: var(--app-radius-sm) 0 0 var(--app-radius-sm);
    }

    .t-input__inner,
    input {
      position: relative;
      z-index: 1;
      background: transparent !important;
    }
  }
}

.model-select-row {
  display: flex;
  align-items: center;
  gap: 8px;

  .t-select {
    flex: 1;
  }
}

.refresh-btn {
  flex-shrink: 0;
}

// 维度控制样式
.dimension-control {
  display: flex;
  align-items: center;
  gap: 8px;

  :deep(.t-input) {
    flex: 1;
  }
}

.dimension-check-btn {
  flex-shrink: 0;
}

.dimension-hint {
  margin: 8px 0 0 0;
  font-size: var(--app-text-md);
  line-height: 1.5;
  color: var(--td-error-color);

  &.success {
    color: var(--td-brand-color);
  }
}

// 自定义 HTTP Header 区域
.custom-headers-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.custom-headers-desc {
  margin: 0 0 10px 0;
  font-size: var(--app-text-sm);
  line-height: 1.5;
  color: var(--td-text-color-placeholder);
}

.custom-headers-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.custom-header-row {
  display: flex;
  align-items: center;
  gap: 8px;

  .custom-header-key {
    flex: 0 0 38%;
  }

  .custom-header-value {
    flex: 1;
  }

  // Ghost icon button — matches the model-card "more" affordance: invisible
  // until hover/focus, then a subtle background pops in. Avoids painting a
  // permanent red splotch next to every header row.
  .custom-header-remove {
    flex-shrink: 0;
    width: 32px;
    height: 32px;
    padding: 0;
    color: var(--td-text-color-placeholder);
    border-radius: var(--app-radius-sm);
    transition: all var(--app-motion-base) ease;

    &:hover {
      background: var(--td-error-color-light);
      color: var(--td-error-color);
    }
  }
}

.form-desc {
  margin: 4px 0 0 0;
  font-size: var(--app-text-sm);
  line-height: 1.5;
  color: var(--td-text-color-placeholder);

  // Inline with switches/checkboxes — drops the top margin so the label and
  // helper text sit on the same baseline.
  &--inline {
    margin: 0;
  }

  &--recommend {
    color: var(--td-brand-color);
  }

  &--warn {
    color: var(--td-warning-color);
  }

  &--error {
    color: var(--td-error-color);
  }
}

// 已选厂商：图标 + 名称，嵌在 t-select 的 valueDisplay 里
.provider-value {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;

  &__name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.provider-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: var(--app-radius-xs);
  object-fit: contain;

  &--placeholder {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--app-text-xs);
    font-weight: 600;
    color: var(--td-text-color-secondary);
    background: var(--td-bg-color-secondarycontainer);
  }
}

// 目录内 / 推理 / 视觉 等弱化徽标（与卡片上的 chip 同调）
.catalog-badge {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  height: 18px;
  border-radius: var(--app-radius-xs);
  background: var(--td-bg-color-secondarycontainer);
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-xs);
  line-height: 18px;
  white-space: nowrap;

  & + & {
    margin-left: 4px;
  }

  &--accent {
    background: var(--td-brand-color-light);
    color: var(--td-brand-color);
  }
}

// 接入诊断面板：只读、浅底，避免与可编辑字段混淆
.resolved-panel {
  padding: 10px 12px;
  border: 1px dashed var(--td-component-stroke);
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-container-hover);

  &__header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }

  &__icon {
    font-size: var(--app-text-base);
    color: var(--td-text-color-secondary);
  }

  &__title {
    font-size: var(--app-text-sm);
    font-weight: 500;
    color: var(--td-text-color-secondary);
  }

  &__loading {
    font-size: var(--app-text-md);
    color: var(--td-text-color-placeholder);
    animation: spin 1s linear infinite;
  }

  &__grid {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    column-gap: 12px;
    row-gap: 4px;
    margin: 0;
    font-size: var(--app-text-sm);

    dt {
      color: var(--td-text-color-placeholder);
      white-space: nowrap;
      line-height: 18px;
    }

    dd {
      margin: 0;
      min-width: 0;
      color: var(--td-text-color-primary);
      line-height: 18px;
      overflow-wrap: anywhere;
    }

    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: var(--app-text-sm);
    }
  }
}

// 高级折叠：与知识库分块设置里的 advanced-toggle 保持同一视觉
.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  margin: 0;
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-size: var(--app-text-md);
  font-weight: 500;
  color: var(--td-text-color-secondary);
  user-select: none;

  &:hover {
    color: var(--td-text-color-primary);
  }

  &:focus-visible {
    outline: 2px solid var(--td-brand-color-focus);
    outline-offset: 2px;
    border-radius: var(--app-radius-xs);
  }

  .toggle-arrow {
    font-size: var(--app-text-base);
    transition: transform var(--app-motion-fast) ease;

    &.open {
      transform: rotate(90deg);
    }
  }
}

.compat-textarea {
  :deep(textarea) {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: var(--app-text-sm);
  }
}

.vision-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

// Ollama不可用提示样式
.ollama-unavailable-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 12px;
  background: var(--td-error-color-light);
  border: 1px solid var(--td-error-color-focus);
  border-radius: var(--app-radius-md);
  font-size: var(--app-text-md);

  .tip-icon {
    color: var(--td-error-color);
    font-size: var(--app-text-xl);
    flex-shrink: 0;
    margin-right: 2px;

    &.info {
      color: var(--td-brand-color);
    }
  }

  .tip-text {
    color: var(--td-error-color);
    flex: 1;
    line-height: 1.5;
  }

  :deep(.tip-link) {
    color: var(--td-brand-color);
    font-size: var(--app-text-md);
    font-weight: 500;
    padding: 4px 6px 4px 10px !important;
    min-height: auto !important;
    height: auto !important;
    line-height: 1.4 !important;
    text-decoration: none;
    white-space: nowrap;
    display: inline-flex !important;
    align-items: center !important;
    gap: 1px;
    border-radius: var(--app-radius-xs);
    transition: all var(--app-motion-base) ease;

    &:hover {
      background: color-mix(in srgb, var(--td-brand-color) 8%, transparent) !important;
      color: var(--td-brand-color-active) !important;
    }

    &:active {
      background: color-mix(in srgb, var(--td-brand-color) 12%, transparent) !important;
    }

    .t-icon {
      font-size: var(--app-text-base) !important;
      margin: 0 !important;
      line-height: 1 !important;
      display: inline-flex !important;
      align-items: center !important;
    }
  }
}

// Destructive-action checkbox for "Remove this credential". Styled to match
// the pattern used in McpServiceDialog so the two dialogs read identically.
.clear-credential {
  display: inline-flex;
  margin-top: 8px;

  :deep(.t-checkbox__label) {
    color: var(--td-error-color);
    font-size: var(--app-text-md);
  }
}
</style>

<style lang="less">
.catalog-model-select-popup {
  padding: 4px;

  .t-select-option {
    height: auto !important;
    padding: 8px 10px;
    border-radius: var(--app-radius-sm);
    margin: 2px 0;
  }
}

.catalog-model-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  width: 100%;

  &__name {
    font-size: var(--app-text-md);
    color: var(--td-text-color-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__id {
    font-size: var(--app-text-xs);
    color: var(--td-text-color-placeholder);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__badges {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
    flex-shrink: 0;

    .catalog-badge {
      display: inline-flex;
      align-items: center;
      padding: 0 6px;
      height: 18px;
      border-radius: var(--app-radius-xs);
      background: var(--td-bg-color-secondarycontainer);
      color: var(--td-text-color-secondary);
      font-size: var(--app-text-xs);
      line-height: 18px;
      white-space: nowrap;

      &--accent {
        background: var(--td-brand-color-light);
        color: var(--td-brand-color);
      }
    }
  }
}

.provider-select-popup {
  // 容器留点呼吸：避免选项贴着 popup 圆角
  padding: 4px;

  // TDesign 给 select 浮层写死 max-height: 300px，而这里的选项是双行的
  // （约 56px），正好只露出五条——下面还有二十多家厂商，但 macOS 的悬浮滚
  // 动条不滚不显形，看上去就像"只有这几个"。放高到一屏能看到八九条，滚动
  // 条也常驻，列表还有后续这件事才成立。&.wk-popover 只是为了压过 TDesign
  // 自己那条同样两级的选择器。
  &.wk-popover .t-popup__content {
    max-height: min(480px, 60vh);
    // Scrolling itself is restored for every skinned select in
    // assets/theme/tdesign-overrides.less; this only makes the bar visible,
    // because macOS overlay scrollbars stay hidden until something moves and
    // a capped list then looks complete.
    scrollbar-color: var(--td-component-border) transparent;
    scrollbar-width: thin;
  }

  // TDesign 默认会在 t-select-option 上挂一个 overflow tooltip（浮在右侧
  // 显示完整 label）。我们的选项排版是「主名称 + 次描述」两行，永远不会
  // 触发省略，tooltip 反而成了视觉噪音 → 直接隐藏 popup 自带的提示。
  + .t-popup .t-tooltip,
  ~ .t-popup .t-tooltip {
    display: none !important;
  }

  .t-select-option {
    height: auto !important;
    padding: 8px 10px;
    border-radius: var(--app-radius-sm);
    margin: 2px 0;
    outline: none;
    transition: background-color var(--app-motion-fast) ease;

    &:focus,
    &:focus-visible {
      outline: none;
    }


  }

  // 命中态不在这里定义：assets/theme/tdesign-overrides.less 已经把 TDesign
  // 默认那条整行铺满的 --td-brand-color-light 换成了中性底色 + 一个主题色小
  // 对勾，全站一致。这里再写一版只会让这个下拉跟「模型类型 / 模型来源」那两
  // 排筛选对不上。选中行的主名称仍然点一下主题色，作为双行排版里的锚点。
  .t-select-option.t-is-selected .provider-name {
    color: var(--td-brand-color);
  }

  .provider-option {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-width: 0;

    .provider-icon {
      width: 18px;
      height: 18px;
      flex-shrink: 0;
      border-radius: var(--app-radius-xs);
      object-fit: contain;

      &--placeholder {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: var(--app-text-xs);
        font-weight: 600;
        color: var(--td-text-color-secondary);
        background: var(--td-bg-color-secondarycontainer);
      }
    }

    &__text {
      display: flex;
      flex-direction: column;
      gap: 2px;
      // 允许收缩，描述才能在浮层宽度内省略（浮层宽度由 matchTriggerWidth 钉死）。
      min-width: 0;
      flex: 1;
    }

    .provider-name {
      font-size: var(--app-text-md);
      font-weight: 500;
      color: var(--td-text-color-primary);
      line-height: 20px;
    }

    .provider-desc {
      font-size: var(--app-text-sm);
      color: var(--td-text-color-placeholder);
      line-height: 18px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }
}
</style>
