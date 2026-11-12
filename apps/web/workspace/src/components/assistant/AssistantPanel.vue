<template>
  <!-- Hidden with a class, not v-if, so a reply keeps streaming while closed. -->
  <aside class="assistant-panel" :class="[`is-${effectiveLayout}`, { 'is-open': assistant.visible, 'is-resizing': resizing }]"
    :style="{ width: `${panelWidth}px` }" role="complementary" :aria-label="assistantName"
    :aria-hidden="!assistant.visible">
    <PanelResizeHandle edge="left" :label="t('assistant.resize')" :value="panelWidth"
      :min="ASSISTANT_PANEL_MIN_WIDTH" :max="ASSISTANT_PANEL_MAX_WIDTH"
      @start="startResize" @resize="resize" @end="resizing = false" />

    <header class="assistant-panel__header">
      <span class="assistant-panel__header-icon" aria-hidden="true"><t-icon name="compass" /></span>
      <span class="assistant-panel__title">{{ assistantName }}</span>
      <t-tooltip :content="t('assistant.newConversation')" placement="bottom">
        <button type="button" class="assistant-panel__action" :disabled="!assistant.sessionId"
          :aria-label="t('assistant.newConversation')" @click="startNewConversation">
          <t-icon name="chat-add" size="16px" />
        </button>
      </t-tooltip>
      <t-tooltip :content="t('assistant.history')" placement="bottom">
        <button type="button" class="assistant-panel__action" :aria-label="t('assistant.history')"
          :aria-pressed="showHistory" @click="toggleHistory">
          <t-icon name="history" size="16px" />
        </button>
      </t-tooltip>
      <t-tooltip v-if="canDock" :content="layoutToggleLabel" placement="bottom">
        <button type="button" class="assistant-panel__action" :aria-label="layoutToggleLabel"
          :aria-pressed="assistant.layout === 'docked'" @click="toggleLayout">
          <t-icon :name="assistant.layout === 'docked' ? 'pin-filled' : 'pin'" size="16px" />
        </button>
      </t-tooltip>
      <t-tooltip :content="t('common.close')" placement="bottom">
        <button type="button" class="assistant-panel__action" :aria-label="t('common.close')"
          @click="assistant.close()">
          <t-icon name="close" size="16px" />
        </button>
      </t-tooltip>
    </header>

    <div class="assistant-panel__body">
      <div v-if="showHistory" class="assistant-history">
        <div v-for="session in history" :key="session.id" class="assistant-history__row"
          :class="{ 'is-current': session.id === assistant.sessionId }">
          <button type="button" class="assistant-history__select" @click="selectSession(session.id)">
            <span>{{ session.title || t('assistant.untitledConversation') }}</span>
            <small>{{ t(`time.${classifyDateBucket(session.updated_at || session.created_at)}`) }}</small>
          </button>
        </div>
        <p v-if="historyError" role="alert">{{ t('assistant.historyFailed') }}</p>
        <p v-else-if="!historyLoading && !history.length">{{ t('assistant.historyEmpty') }}</p>
        <t-button v-if="historyError" variant="text" block :loading="historyLoading" @click="loadHistory">
          {{ t('common.retry') }}
        </t-button>
        <t-loading v-else-if="historyLoading" size="small" />
      </div>
      <!-- 对话区复用主对话页：会话由 assistant.sessionId 决定，空值即欢迎态。 -->
      <div v-show="!showHistory" class="assistant-panel__conversation">
        <NexusChatPage ref="chatRef" compact :session-id="assistant.sessionId"
          @session-created="onSessionCreated" />
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import NexusChatPage from '@/views/chat/NexusChatPage.vue'
import PanelResizeHandle from '@/components/PanelResizeHandle.vue'
import { listSessions, type SessionView } from '@nexus-web/core/api/native-runs'
import { classifyDateBucket } from '@/components/sessionGrouping'
import {
  ASSISTANT_PANEL_MAX_WIDTH,
  ASSISTANT_PANEL_MIN_WIDTH,
  useAssistantStore,
} from '@/stores/assistant'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAssistantDataChange } from '@nexus-web/core/utils/assistantDataChange'

const { t } = useI18n()
const assistant = useAssistantStore()
const auth = useAuthStore()
useAssistantDataChange(() => { void auth.refreshFromAuthMe() }, { areas: ['workspace'] })
const conversationOwner = computed(() => `${auth.user?.id}:${auth.effectiveTenantId}`)
const assistantName = computed(() => assistant.displayName || t('assistant.title'))

// Below this the page would be too cramped beside a docked panel, so the
// panel floats instead whatever the preference.
const DOCK_MIN_VIEWPORT = 1100
// The page keeps at least this much room beside a docked panel.
const DOCK_MIN_PAGE_WIDTH = 720
const FLOATING_MARGIN = 12

const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth || 0 : 0)
const onViewportResize = () => { viewportWidth.value = window.innerWidth }
const canDock = computed(() => viewportWidth.value >= DOCK_MIN_VIEWPORT)
const effectiveLayout = computed(() => assistant.layout === 'docked' && canDock.value ? 'docked' : 'floating')
const docked = computed(() => assistant.visible && effectiveLayout.value === 'docked')

const panelWidth = computed(() => {
  const room = effectiveLayout.value === 'docked'
    ? viewportWidth.value - DOCK_MIN_PAGE_WIDTH
    : viewportWidth.value - 2 * FLOATING_MARGIN
  return Math.max(ASSISTANT_PANEL_MIN_WIDTH, Math.min(assistant.width, room || assistant.width))
})

const layoutToggleLabel = computed(() => assistant.layout === 'docked'
  ? t('assistant.layout.float') : t('assistant.layout.dock'))
const toggleLayout = () => assistant.setLayout(assistant.layout === 'docked' ? 'floating' : 'docked')

const resizing = ref(false)
let resizeStartWidth = 0
const startResize = () => {
  resizeStartWidth = panelWidth.value
  resizing.value = true
}
const resize = (delta: number) => assistant.setWidth(resizeStartWidth - delta)

// Page overlays (drawers, dialogs, side panels) stop at a docked panel's edge
// instead of covering it: TDesign's in the unscoped styles below, ours by
// reading --assistant-dock-width in their own styles.
watch([docked, panelWidth], ([isDocked, width]) => {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('has-assistant-dock', isDocked)
  root.style.setProperty('--assistant-dock-width', isDocked ? `${width}px` : '0px')
}, { immediate: true })


const chatRef = ref<{ sendText: (text: string) => Promise<void> } | null>(null)

/**
 * 「询问助手」请求：有打开的会话就发送到该会话；没有则由欢迎态创建新会话。
 * 请求可能在面板挂载前到达，因此挂载后也会消费一次。
 */
async function consumePendingRequest() {
  const request = assistant.takePendingRequest()
  assistant.restorePageContext()
  const query = request?.query?.trim()
  if (!query) return
  await nextTick()
  showHistory.value = false
  await chatRef.value?.sendText(query)
}

watch(() => [assistant.visible, assistant.pendingRequest] as const, ([visible, request]) => {
  if (visible && request) void consumePendingRequest()
})

function onSessionCreated(id: string) {
  showHistory.value = false
  assistant.setSession(id)
}

const showHistory = ref(false)
const history = ref<SessionView[]>([])
const historyLoading = ref(false)
const historyError = ref(false)
let historyGeneration = 0

async function loadHistory() {
  const generation = ++historyGeneration
  const owner = conversationOwner.value
  const tenantId = auth.effectiveTenantId
  if (!tenantId) {
    history.value = []
    return
  }
  historyLoading.value = true
  historyError.value = false
  try {
    const rows = await listSessions(tenantId)
    if (generation !== historyGeneration || owner !== conversationOwner.value) return
    history.value = [...rows].sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
  } catch {
    if (generation === historyGeneration && owner === conversationOwner.value) historyError.value = true
  } finally {
    if (generation === historyGeneration && owner === conversationOwner.value) historyLoading.value = false
  }
}

function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) void loadHistory()
}

function startNewConversation() {
  showHistory.value = false
  assistant.startNewConversation()
}

function selectSession(id: string) {
  assistant.setSession(id)
  showHistory.value = false
}

/**
 * 面板保存的会话 ID 可能已经失效（例如旧的 WeKnora 会话），挂载时对照平台会话列表校正，
 * 失效则回到欢迎态，避免对话区加载一个打不开的会话。
 */
async function validateStoredSession() {
  const id = assistant.sessionId
  const tenantId = auth.effectiveTenantId
  if (!id || !tenantId) return
  try {
    const rows = await listSessions(tenantId)
    if (id === assistant.sessionId && !rows.some(row => row.id === id)) assistant.setSession('')
  } catch {
    // 列表读取失败时保留会话，由对话区自行报告加载错误。
  }
}

watch(conversationOwner, () => {
  ++historyGeneration
  history.value = []
  historyLoading.value = false
  historyError.value = false
  showHistory.value = false
})

onMounted(() => {
  window.addEventListener('resize', onViewportResize)
  void validateStoredSession()
  if (assistant.visible && assistant.pendingRequest) void consumePendingRequest()
})
onUnmounted(() => {
  window.removeEventListener('resize', onViewportResize)
  if (typeof document !== 'undefined') {
    document.documentElement.classList.remove('has-assistant-dock')
    document.documentElement.style.removeProperty('--assistant-dock-width')
  }
})
</script>

<style lang="less" scoped>
.assistant-panel {
  display: none;
  position: relative;
  flex-direction: column;
  min-height: 0;
  box-sizing: border-box;
  background: var(--td-bg-color-container);

  &.is-open {
    display: flex;
  }

  // A column of the platform layout: the page to its left narrows.
  &.is-docked {
    flex-shrink: 0;
    height: 100%;
    border-left: 1px solid var(--td-component-stroke);
  }

  // Above page drawers (1500), below dialogs and the settings shell; no mask.
  &.is-floating {
    position: fixed;
    top: 12px;
    right: 12px;
    bottom: 12px;
    z-index: 1600;
    border: 1px solid var(--td-component-stroke);
    border-radius: var(--app-radius-lg);
    box-shadow: var(--td-shadow-3);
    overflow: hidden;

    &.is-open {
      animation: assistant-panel-in var(--app-motion-base) cubic-bezier(0.22, 0.61, 0.36, 1);
    }
  }

  &.is-resizing {
    user-select: none;

    .assistant-panel__body {
      pointer-events: none;
    }
  }
}

@keyframes assistant-panel-in {
  from {
    opacity: 0;
    transform: translateX(16px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

.assistant-composer-context {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
  height: 28px;
  flex: 0 0 100%;

  :deep(.assistant-selection-chip) {
    flex: 0 1 auto;
    max-width: 100%;
    height: 26px;
  }
}

.assistant-panel__header {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 var(--app-chat-header-height);
  min-width: 0;
  padding: 0 12px 0 16px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--td-component-stroke);
}

.assistant-panel__header-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  margin-right: 4px;
  border-radius: var(--app-radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--td-brand-color) 10%, transparent);
  color: var(--td-brand-color);
  font-size: var(--app-text-lg);
}

.assistant-panel__title {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--app-text-base);
  font-weight: 500;
  line-height: 20px;
  color: var(--td-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-panel__action {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-md);
  background: transparent;
  color: var(--td-text-color-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--app-motion-fast) ease, color var(--app-motion-fast) ease;

  &:hover:not(:disabled) {
    background: var(--td-bg-color-container-hover);
    color: var(--td-text-color-primary);
  }

  &:disabled {
    cursor: not-allowed;
    color: var(--td-text-color-disabled);
  }

  &[aria-pressed='true'] {
    color: var(--td-text-color-primary);
  }
}

.assistant-panel__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.assistant-panel__conversation {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;

  // Align the assistant composer with the main conversation composer.
  :deep(.input-container.is-embedded) {
    padding-bottom: max(8px, env(safe-area-inset-bottom));
  }
}

.assistant-history {
  overflow-y: auto;
  padding: 12px;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-sm);
}

.assistant-history__row {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: var(--app-radius-md);

  &:hover, &.is-current {
    background: var(--td-bg-color-container-hover);
  }

  &.is-current {
    color: var(--td-brand-color);
  }
}

.assistant-history__select {
  flex: 1;
  min-width: 0;
  padding: 10px 8px;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;

  span, small {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  small {
    margin-top: 4px;
    color: var(--td-text-color-placeholder);
  }
}

.assistant-welcome {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.assistant-welcome-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 24px;
  text-align: center;
}

.assistant-welcome-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--app-radius-md, 8px);
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--td-brand-color) 10%, transparent);
  color: var(--td-brand-color);
}

.assistant-welcome-title {
  margin: 4px 0 0;
  font-size: var(--app-text-lg);
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.assistant-welcome-desc {
  margin: 0;
  max-width: 420px;
  font-size: var(--app-text-md);
  line-height: 1.6;
  color: var(--td-text-color-secondary);
}

.assistant-starters {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
}

.assistant-starter {
  padding: 6px 12px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-medium);
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
  font-family: inherit;
  font-size: var(--app-text-sm);
  line-height: 18px;
  cursor: pointer;
  transition: background var(--app-motion-fast), border-color var(--app-motion-fast);

  &:hover:not(:disabled) {
    background: var(--td-bg-color-container-hover);
    border-color: var(--td-component-border);
  }

  &:disabled {
    cursor: not-allowed;
    color: var(--td-text-color-disabled);
  }
}

// Same inset as the composer inside a conversation.
.assistant-welcome-composer {
  flex-shrink: 0;
  padding: 12px 16px max(8px, env(safe-area-inset-bottom));
}
</style>

<style lang="less">
html.has-assistant-dock {
  .t-drawer:not(.t-drawer--attach):not(.chat-artifacts-drawer),
  .t-dialog__ctx--fixed .t-dialog__mask,
  .t-dialog__ctx--fixed .t-dialog__wrap {
    width: calc(100% - var(--assistant-dock-width));
  }

  .t-drawer--right:not(.t-drawer--attach):not(.chat-artifacts-drawer) {
    right: var(--assistant-dock-width);
  }
}
</style>
