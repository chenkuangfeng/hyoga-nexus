<template>
  <!--
    Agent picker for the Nexus composer. Template, positioning and styles copied from WeKnora
    `components/AgentSelector.vue`. Platform agents are all user-created, so they appear in the
    "custom agents" group; WeKnora's built-in and shared groups and capability checks have no
    platform data and are omitted. Reads nothing from WeKnora stores or endpoints.
  -->
  <Teleport to="body">
    <div v-if="visible" class="agent-selector-overlay" @click="$emit('close')">
      <div class="agent-selector-dropdown" :style="dropdownStyle" data-testid="agent-selector" @click.stop>
        <div class="agent-selector-header">
          <span>{{ t('agent.selectAgent') }}</span>
          <router-link to="/platform/agents" class="agent-selector-add" @click="$emit('close')">
            <span class="add-icon">+</span>
            <span class="add-text">{{ t('agent.manageAgents') }}</span>
          </router-link>
        </div>
        <div class="agent-selector-content" @scroll="hideDetailPanel">
          <div v-if="agents.length > 0" class="agent-group">
            <div class="agent-group-title">{{ t('agent.customAgents') }}</div>
            <div v-for="agent in agents" :key="agent.id" class="agent-option"
              :class="{ selected: agent.id === currentAgentId }" @mouseenter="onOptionEnter(agent, $event)"
              @mouseleave="onOptionLeave" @click="selectAgent(agent)">
              <AgentAvatar :name="agent.name" size="small" />
              <span class="agent-option-name">{{ agent.name }}</span>
            </div>
          </div>
          <div v-else class="agent-option empty">{{ t('agent.noAgents') }}</div>
        </div>
      </div>
    </div>
    <div v-if="visible && activeDetail" ref="detailPanelRef" class="agent-detail-panel" :style="detailPanelStyle"
      @mouseenter="clearDetailHideTimer" @mouseleave="onOptionLeave" @click.stop>
      <div class="agent-detail-panel-inner">
        <div class="agent-detail-content">
          <div class="detail-header">
            <AgentAvatar :name="activeDetail.name" size="small" />
            <div class="detail-title-wrap">
              <div class="detail-title-row">
                <span class="detail-name">{{ activeDetail.name }}</span>
              </div>
              <span v-if="activeDetail.id === currentAgentId" class="detail-current">{{ t('agent.selector.current') }}</span>
            </div>
          </div>
          <p class="detail-desc">{{ activeDetail.description || t('agent.noDescription') }}</p>
          <div class="detail-tags">
            <span class="detail-tag">{{ t('agent.type.agent') }}</span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * Props: `visible`, `anchorEl` (the agent button), `currentAgentId`, `agents` ({ id, name, description }).
 * Emits `close` and `select(agentId)`.
 */
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AgentAvatar from '@/components/AgentAvatar.vue'
import { cssViewportSize, getRootZoom, rectToCssPx } from '@/utils/zoom'
import type { NexusAgentOption } from '@/composables/nexusChatActions'

const props = defineProps<{
  visible: boolean
  anchorEl?: HTMLElement | null
  currentAgentId: string
  agents: NexusAgentOption[]
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'select', agentId: string): void }>()
const { t } = useI18n()

const DETAIL_PANEL_WIDTH = 200
const DETAIL_PANEL_GAP = 8
const DETAIL_HIDE_DELAY_MS = 400

const dropdownStyle = ref<Record<string, string>>({})
const activeDetail = ref<NexusAgentOption | null>(null)
const detailAnchorEl = ref<HTMLElement | null>(null)
const detailPanelRef = ref<HTMLElement | null>(null)
const detailPanelStyle = ref<Record<string, string>>({})
let detailHideTimer: ReturnType<typeof setTimeout> | null = null

function clearDetailHideTimer() {
  if (detailHideTimer) {
    clearTimeout(detailHideTimer)
    detailHideTimer = null
  }
}

function updateDetailPanelPosition() {
  const el = detailAnchorEl.value
  if (!el || !activeDetail.value) return
  const zoom = getRootZoom()
  const rowRect = rectToCssPx(el.getBoundingClientRect(), zoom)
  const { width: vw, height: vh } = cssViewportSize(zoom)
  let left = rowRect.right + DETAIL_PANEL_GAP
  if (left + DETAIL_PANEL_WIDTH > vw - 8) left = Math.max(8, vw - DETAIL_PANEL_WIDTH - 8)
  const panelHeight = detailPanelRef.value?.offsetHeight || 180
  const top = Math.max(8, Math.min(rowRect.top + rowRect.height / 2 - panelHeight / 2, vh - panelHeight - 8))
  detailPanelStyle.value = {
    position: 'fixed', left: `${Math.round(left)}px`, top: `${Math.round(top)}px`,
    width: `${DETAIL_PANEL_WIDTH}px`, zIndex: '10002',
  }
}

function onOptionEnter(agent: NexusAgentOption, event: MouseEvent) {
  clearDetailHideTimer()
  detailAnchorEl.value = event.currentTarget as HTMLElement
  activeDetail.value = agent
  void nextTick(() => {
    updateDetailPanelPosition()
    requestAnimationFrame(updateDetailPanelPosition)
  })
}

function onOptionLeave() {
  detailHideTimer = setTimeout(() => {
    activeDetail.value = null
    detailAnchorEl.value = null
  }, DETAIL_HIDE_DELAY_MS)
}

function hideDetailPanel() {
  clearDetailHideTimer()
  activeDetail.value = null
  detailAnchorEl.value = null
}

function selectAgent(agent: NexusAgentOption) {
  emit('select', agent.id)
  emit('close')
}

/** Same placement rule as WeKnora: below the button when there is room, otherwise above it. */
function updateDropdownPosition() {
  if (!props.anchorEl) return
  const zoom = getRootZoom()
  const rect = rectToCssPx(props.anchorEl.getBoundingClientRect(), zoom)
  const { width: vw, height: vh } = cssViewportSize(zoom)
  const dropdownWidth = 220
  const offsetY = 6
  const left = Math.max(16, Math.min(Math.max(16, vw - dropdownWidth - 16), Math.floor(rect.left)))
  const preferredDropdownHeight = 280
  const minDropdownHeight = 100
  const spaceBelow = vh - rect.bottom
  if (spaceBelow >= minDropdownHeight + offsetY) {
    dropdownStyle.value = {
      position: 'fixed', width: `${dropdownWidth}px`, left: `${left}px`, top: `${Math.floor(rect.bottom + offsetY)}px`,
      maxHeight: `${Math.min(preferredDropdownHeight, spaceBelow - offsetY - 16)}px`, zIndex: '10001',
    }
  } else {
    const availableHeight = rect.top - offsetY - 20
    const height = availableHeight >= preferredDropdownHeight ? preferredDropdownHeight : Math.max(minDropdownHeight, availableHeight)
    dropdownStyle.value = {
      position: 'fixed', width: `${dropdownWidth}px`, left: `${left}px`, bottom: `${vh - rect.top + offsetY}px`,
      maxHeight: `${height}px`, zIndex: '10001',
    }
  }
}

watch(() => props.visible, (visible) => {
  if (visible) void nextTick(updateDropdownPosition)
  else hideDetailPanel()
})
</script>

<!-- Copied from WeKnora components/AgentSelector.vue -->
<style scoped lang="less">
.agent-selector-overlay,
.agent-selector-overlay *,
.agent-selector-overlay *::before,
.agent-selector-overlay *::after {
  box-sizing: border-box;
}

.agent-selector-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: transparent;
  touch-action: none;
}

.agent-selector-dropdown {
  position: fixed !important;
  background: var(--td-bg-color-container);
  border: .5px solid var(--td-component-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--td-shadow-2);
  display: flex;
  flex-direction: column;
  z-index: 10001;
  margin: 0;
  transform-origin: top left;
  animation: agentSelectorFadeIn 0.15s ease-out;
}

@keyframes agentSelectorFadeIn {
  from {
    opacity: 0;
    transform: scale(0.98);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

.agent-selector-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 36px;
  padding: 8px 12px;
  border-bottom: .5px solid var(--td-component-stroke);
  font-size: var(--app-text-sm);
  font-weight: 500;
  line-height: 1;
  color: var(--td-text-color-secondary);
}

.agent-selector-add {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 22px;
  padding: 0 6px;
  border-radius: var(--app-radius-sm);
  color: var(--td-brand-color);
  font-size: var(--app-text-sm);
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  text-decoration: none;
  flex-shrink: 0;

  &:hover {
    background: var(--td-bg-color-secondarycontainer);
  }
}

.agent-selector-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: 6px 4px 8px;
}

.agent-group {
  &:not(:last-child) {
    margin-bottom: 4px;
    padding-bottom: 4px;
    border-bottom: .5px solid var(--td-component-stroke);
  }
}

.agent-group-title {
  font-size: var(--app-text-xs);
  color: var(--td-text-color-placeholder);
  padding: 8px 12px 4px;
  font-weight: 600;
  line-height: 16px;
}

.agent-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  margin: 0 4px;
  padding: 6px 8px;
  cursor: pointer;
  transition: background var(--app-motion-instant);
  border-radius: var(--app-radius-sm);

  &:hover,
  &.selected {
    background: var(--td-bg-color-secondarycontainer);
  }

  &.empty {
    color: var(--td-text-color-placeholder);
    cursor: default;
    text-align: center;
    padding: 16px 8px;
    min-height: auto;

    &:hover {
      background: transparent;
    }
  }

  :deep(.agent-avatar-small) {
    width: 22px;
    height: 22px;
    border-radius: var(--app-radius-sm);
  }
}

.agent-option-name {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 22px;
}

.shared-tag {
  font-size: var(--app-text-2xs);
  color: var(--td-text-color-placeholder);
  flex-shrink: 0;
  line-height: 22px;
}

.agent-option-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
}

.not-ready-icon {
  flex-shrink: 0;
  color: var(--td-warning-color);
  cursor: default;
  display: block;
  line-height: 1;
}

.builtin-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--app-radius-sm);
  flex-shrink: 0;
  line-height: 1;

  :deep(.t-icon) {
    display: block;
    line-height: 1;
  }

  &.normal {
    background: var(--td-brand-color-light);
    color: var(--td-brand-color-active);
  }

  &.agent {
    background: rgba(124, 77, 255, 0.1);
    color: var(--td-brand-color);
  }

  &.detail-icon {
    width: 28px;
    height: 28px;
  }
}

.builtin-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--app-radius-sm);
  flex-shrink: 0;
  font-size: var(--app-text-base);
  line-height: 1;
  background: var(--td-bg-color-secondarycontainer);
  overflow: hidden;

  &.detail-icon {
    width: 28px;
    height: 28px;
    font-size: var(--app-text-2xl);
  }
}

/* 详情浮层 */
.agent-detail-panel {
  box-sizing: border-box;
  position: relative;
  --detail-panel-gap: 8px;
  --detail-bridge-width: 8px;

  // 左侧透明桥接区：承接从选项移入的鼠标，避免经过间隙时浮层消失
  &::before {
    content: '';
    position: absolute;
    left: calc(-1 * (var(--detail-bridge-width) + var(--detail-panel-gap)));
    top: 0;
    width: calc(var(--detail-bridge-width) + var(--detail-panel-gap));
    height: 100%;
  }
}

.agent-detail-panel-inner {
  padding: 12px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-large);
  background: var(--td-bg-color-container);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.1), 0 2px 8px rgba(0, 0, 0, 0.04);
}

.agent-detail-content {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-primary);
  line-height: 1.5;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.detail-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.detail-name {
  font-weight: 600;
  font-size: var(--app-text-md);
  line-height: 18px;
  word-break: break-word;
  min-width: 0;
  flex: 1;
}

.detail-settings-icon,
.detail-header-action {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: var(--app-radius-xs);
  background: transparent;
  color: var(--td-text-color-placeholder);
  cursor: pointer;

  &:hover {
    background: var(--td-bg-color-component-hover);
    color: var(--td-text-color-secondary);
  }

  &--warn {
    color: var(--td-warning-color);

    &:hover {
      background: rgba(237, 123, 47, 0.1);
      color: var(--td-warning-color);
    }
  }
}

.detail-current {
  font-size: var(--app-text-xs);
  color: var(--td-text-color-placeholder);
}

.detail-not-ready {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 1px;
}

.detail-not-ready-icon {
  flex-shrink: 0;
  color: var(--td-warning-color);
  opacity: 0.85;
}

.detail-not-ready-label {
  font-size: var(--app-text-xs);
  line-height: 16px;
  color: var(--td-text-color-secondary);
}

.detail-not-ready-item {
  display: inline-flex;
  align-items: center;
  padding: 0 5px;
  border: 1px solid rgba(237, 123, 47, 0.28);
  border-radius: var(--app-radius-xs);
  font-size: var(--app-text-2xs);
  line-height: 16px;
  color: var(--td-text-color-secondary);
  background: var(--td-bg-color-container);
}

.detail-not-ready-shared-hint {
  display: block;
  width: 100%;
  margin-top: 2px;
  font-size: var(--app-text-2xs);
  line-height: 1.4;
  color: var(--td-text-color-placeholder);
}

.detail-desc {
  margin: 0 0 8px;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 8px;
  border-top: .5px solid var(--td-component-stroke);

  &--capabilities {
    padding-top: 0;
    border-top: none;
  }
}

.detail-tag-group {
  margin-top: 8px;
  padding-top: 8px;
  border-top: .5px solid var(--td-component-stroke);
}

.detail-tag-group-title {
  font-size: var(--app-text-xs);
  font-weight: 600;
  line-height: 16px;
  color: var(--td-text-color-placeholder);
  margin-bottom: 6px;
}

.detail-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-medium);
  font-size: var(--app-text-xs);
  line-height: 18px;
  color: var(--td-text-color-secondary);
  background: var(--td-bg-color-secondarycontainer);
}

.detail-capability-tag {
  gap: 5px;
  max-width: 100%;
  padding: 3px 7px 3px 5px;

  .detail-capability-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--td-text-color-secondary);
    font-weight: 500;
  }

  .detail-capability-state {
    flex-shrink: 0;
    font-size: var(--app-text-2xs);
    line-height: 14px;
    color: var(--td-text-color-placeholder);
  }
}

.detail-capability-tag--on {
  border-color: rgba(0, 168, 112, 0.2);
  background: rgba(0, 168, 112, 0.06);

  .detail-capability-icon-wrap {
    color: var(--td-success-color);
    background: rgba(0, 168, 112, 0.12);
  }

  .detail-capability-icon {
    color: var(--td-success-color);
  }

  .detail-capability-state {
    color: var(--td-success-color);
  }
}

.detail-capability-tag--warning {
  border-color: rgba(237, 123, 47, 0.22);
  background: rgba(237, 123, 47, 0.06);

  .detail-capability-icon-wrap {
    color: var(--td-warning-color);
    background: rgba(237, 123, 47, 0.12);
  }

  .detail-capability-icon,
  .detail-capability-state {
    color: var(--td-warning-color);
  }
}

.detail-capability-tag--off {
  border-color: var(--td-component-stroke);
  background: var(--td-bg-color-secondarycontainer);

  .detail-capability-icon-wrap {
    color: var(--td-text-color-placeholder);
    background: var(--td-bg-color-component);
  }

  .detail-capability-icon {
    color: var(--td-text-color-placeholder);
  }
}

.detail-capability-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  flex-shrink: 0;
}

.detail-capability-icon {
  display: inline-flex;
  flex-shrink: 0;
  line-height: 1;
}

.detail-meta {
  margin-top: 8px;
  padding-top: 8px;
  border-top: .5px solid var(--td-component-stroke);
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--app-text-xs);
  color: var(--td-text-color-placeholder);
}

.detail-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.detail-meta-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
</style>
