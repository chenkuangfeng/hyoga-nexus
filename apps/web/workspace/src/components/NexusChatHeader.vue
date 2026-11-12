<template>
  <!--
    Nexus chat header. Template and styles copied from WeKnora `components/ChatHeader.vue`.
    "Copy as Markdown" is implemented on the page; rename, pin, grants and delete have no platform
    session API yet and show the "not available yet" notice (openspec 2026-11-04-weknora-chat-dialog).
  -->
  <header class="chat-header">
    <h1 class="chat-header__title" :title="displayTitle" data-testid="chat-title" @dblclick="planned('renameSession')">
      <span class="chat-header__title-text">{{ displayTitle }}</span>
    </h1>
    <t-popup v-model:visible="menuVisible" :overlay-class-name="menuOverlayClass" trigger="click" destroy-on-close
      placement="bottom-left" :disabled="!sessionId" @visible-change="onMenuVisibleChange">
      <button type="button" class="chat-header__menu-btn" :disabled="!sessionId" :aria-label="t('chatHeader.moreActions')"
        data-testid="chat-header-menu" @click.stop>
        <t-icon name="ellipsis" size="16px" />
      </button>
      <template #content>
        <div class="card-menu" @click.stop>
          <template v-if="menuMode === 'menu'">
            <button type="button" class="card-menu-item" @click="menuPlanned('renameSession')">
              <t-icon class="icon" name="edit-1" />
              <span>{{ t('menu.renameSession') }}</span>
            </button>
            <button type="button" class="card-menu-item" @click="menuPlanned('sessionGrants')">
              <t-icon class="icon" name="lock-on" />
              <span>{{ t('chatHeader.grants.menu') }}</span>
            </button>
            <button type="button" class="card-menu-item" data-testid="chat-copy-markdown" @click="copyMarkdown">
              <t-icon class="icon" name="file-copy" />
              <span>{{ t('chatHeader.copyMarkdown') }}</span>
            </button>
            <button type="button" class="card-menu-item danger" @click="menuMode = 'confirm'">
              <t-icon class="icon" name="delete" />
              <span>{{ t('chatHeader.deleteSession') }}</span>
            </button>
          </template>
          <div v-else class="chat-header-confirm">
            <div class="chat-header-confirm__title">{{ t('chatHeader.deleteConfirmTitle') }}</div>
            <div class="chat-header-confirm__body">{{ t('chatHeader.deleteConfirmBody') }}</div>
            <div class="chat-header-confirm__footer">
              <button type="button" class="chat-header-confirm__btn" @click="menuMode = 'menu'">{{ t('common.cancel') }}</button>
              <button type="button" class="chat-header-confirm__btn is-danger" @click="menuPlanned('deleteSession')">
                {{ t('common.delete') }}
              </button>
            </div>
          </div>
        </div>
      </template>
    </t-popup>
  </header>
</template>

<script setup lang="ts">
/** Props: `title` (empty shows the default title) and `sessionId`. Emits `copy-markdown`. */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useNexusChatActions } from '@/composables/nexusChatActions'

const props = defineProps<{ title: string; sessionId: string }>()
const emit = defineEmits<{ (e: 'copy-markdown'): void }>()
const { t } = useI18n()
const actions = useNexusChatActions()

const menuVisible = ref(false)
const menuMode = ref<'menu' | 'confirm'>('menu')
const displayTitle = computed(() => props.title || t('createChat.newSessionTitle'))
const menuOverlayClass = computed(() => (
  menuMode.value === 'menu' ? 'card-more chat-header-menu-popup' : 'card-more chat-header-menu-popup is-confirm'
))

function planned(feature: string) {
  actions?.planned(feature)
}

function menuPlanned(feature: string) {
  menuVisible.value = false
  planned(feature)
}

function onMenuVisibleChange(visible: boolean) {
  if (!visible) menuMode.value = 'menu'
}

function copyMarkdown() {
  menuVisible.value = false
  emit('copy-markdown')
}
</script>

<!-- Copied from WeKnora components/ChatHeader.vue -->
<style scoped lang="less">
.chat-header {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  max-width: min(520px, calc(100% - 36px));
  min-width: 0;
  box-sizing: border-box;
}

.chat-header__edit {
  flex: 1 1 auto;
  min-width: 0;
  width: 240px;
  max-width: 100%;
}

.chat-header__edit-input {
  width: 100%;
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--td-brand-color);
  border-radius: var(--app-radius-sm);
  color: var(--td-text-color-primary);
  background: var(--td-bg-color-container);
  font-size: var(--app-text-base);
  line-height: 26px;
  outline: none;
  box-sizing: border-box;
  box-shadow: 0 0 0 2px var(--td-brand-color-light);

  &:disabled {
    opacity: 0.7;
  }
}

.chat-header__title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  margin: 0;
  padding: 0;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-base);
  font-weight: 500;
  line-height: 20px;
  cursor: default;
}

.chat-header__title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-header__automation {
  display: inline-flex;
  flex: 0 1 auto;
  align-items: center;
  gap: 4px;
  min-width: 0;
  max-width: 160px;
  margin-left: 6px;
  padding: 0 8px;
  height: 22px;
  border-radius: var(--app-radius-sm);
  background: var(--td-bg-color-secondarycontainer);
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-xs);
  line-height: 22px;
  text-decoration: none;
  white-space: nowrap;

  span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &:hover {
    color: var(--td-brand-color);
    background: var(--td-bg-color-secondarycontainer-hover);
  }
}

.chat-header__workspace {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 6px;
  color: var(--td-text-color-placeholder);
  font-size: var(--app-text-xs);
  font-weight: 400;
  line-height: 20px;
}

.chat-header__pin {
  flex: 0 0 auto;
  color: var(--td-text-color-placeholder);
}

.chat-header__menu-btn {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-sm);
  color: var(--td-text-color-placeholder);
  background: transparent;
  cursor: pointer;
  transition: background-color var(--app-motion-fast) ease, color var(--app-motion-fast) ease;

  &:hover:not(:disabled) {
    color: var(--td-text-color-primary);
    background: var(--td-bg-color-container-hover);
  }

  &:active:not(:disabled) {
    background: var(--td-bg-color-container-active);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  &.is-loading {
    cursor: wait;
  }
}

.chat-header__menu-loading {
  animation: wk-spin 0.8s linear infinite;
}

</style>

<style lang="less">
.card-more.chat-header-menu-popup.is-confirm .t-popup__content {
  padding: 12px !important;
  width: 260px !important;
  min-width: 260px !important;
}

.chat-header-confirm {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 236px;
}

.chat-header-confirm__title {
  margin: 0;
  color: var(--td-text-color-primary);
  font-size: var(--app-text-base);
  font-weight: 600;
  line-height: 20px;
}

.chat-header-confirm__body {
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-base);
  line-height: 1.5;
  word-break: break-word;
}

.chat-header-grants {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 240px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.chat-header-grants__item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-header-grants__label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--td-text-color-primary);
  font-size: var(--app-text-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-header-grants__empty {
  color: var(--td-text-color-placeholder);
  font-size: var(--app-text-sm);
}

.chat-header-confirm__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 2px;
}

.chat-header-confirm__btn {
  min-width: 60px;
  height: 30px;
  padding: 0 12px;
  border: 0.5px solid var(--td-component-stroke);
  border-radius: var(--app-radius-sm);
  color: var(--td-text-color-primary);
  background: var(--td-bg-color-container);
  font-size: var(--app-text-base);
  line-height: 28px;
  cursor: pointer;
  transition: background-color var(--app-motion-fast) ease, color var(--app-motion-fast) ease, border-color var(--app-motion-fast) ease;

  &:hover:not(:disabled) {
    background: var(--td-bg-color-container-hover);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  &.is-danger {
    border-color: transparent;
    color: #fff;
    background: var(--td-error-color-6);

    &:hover:not(:disabled) {
      background: var(--td-error-color-5);
    }
  }
}

</style>
