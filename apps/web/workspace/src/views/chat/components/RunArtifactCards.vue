<script setup lang="ts">
/**
 * Files a Run left under `/outputs`, shown under the answer it produced (openspec 2026-11-07-tool-expansion 4.6).
 *
 * The conversation page loads the session's artifacts and hands over the ones of this Run. A file that the preview
 * can render opens in a drawer (its bytes are fetched on opening, which the server audits as a download); every file
 * can be downloaded. The full library lives on the artifacts page.
 */
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { downloadArtifactFile, type ArtifactLibraryItem } from '@nexus-web/core/api/artifacts'
import { resolveFilePreviewExt, resolvePreviewKind } from '@/utils/filePreview'
import { formatArtifactSize } from '@/utils/sessionArtifacts'
import { COLLAPSED_LIMIT, visibleArtifacts } from '@/utils/runArtifacts'
import DocumentPreview from '@/components/document-preview.vue'
import ArtifactFileIcon from './ArtifactFileIcon.vue'

const props = defineProps<{ items: ArtifactLibraryItem[] }>()
const { t } = useI18n()
const router = useRouter()

const expanded = ref(false)
const downloading = reactive<Record<string, boolean>>({})
const previewItem = ref<ArtifactLibraryItem | null>(null)
const previewBlob = ref<Blob | null>(null)
const previewFailed = ref(false)
const previewVisible = ref(false)
const previewActions = ref<HTMLElement | null>(null)

const view = computed(() => visibleArtifacts(props.items, expanded.value))
const canCollapse = computed(() => expanded.value && props.items.length > COLLAPSED_LIMIT)
const previewFileType = computed(() => {
  const item = previewItem.value
  return item ? resolveFilePreviewExt(item.file_name, item.file_type) : ''
})

function canPreview(item: ArtifactLibraryItem): boolean {
  return resolvePreviewKind(resolveFilePreviewExt(item.file_name, item.file_type)) !== 'unsupported'
}

async function openPreview(item: ArtifactLibraryItem) {
  if (!canPreview(item)) return
  previewItem.value = item
  previewBlob.value = null
  previewFailed.value = false
  previewVisible.value = true
  try {
    const blob = await downloadArtifactFile(item)
    // The reader may have closed the drawer or opened another file while this was in flight.
    if (previewItem.value?.id === item.id) previewBlob.value = blob
  } catch (error) {
    console.error('[RunArtifactCards] preview failed:', error)
    if (previewItem.value?.id === item.id) previewFailed.value = true
  }
}

async function download(item: ArtifactLibraryItem) {
  if (downloading[item.id]) return
  downloading[item.id] = true
  try {
    const blob = await downloadArtifactFile(item)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = item.file_name || 'artifact'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    console.error('[RunArtifactCards] download failed:', error)
    MessagePlugin.error(t('artifactLibrary.downloadFailed'))
  } finally {
    downloading[item.id] = false
  }
}

function openLibrary() {
  void router.push('/platform/artifacts')
}

defineExpose({ openPreview, download, expanded, previewBlob, previewFailed, previewVisible, view })
</script>

<template>
  <div v-if="items.length" class="run-artifacts" data-testid="run-artifacts">
    <div class="run-artifacts__head">
      <span class="run-artifacts__title">{{ t('nexusChat.artifacts.title', { count: items.length }) }}</span>
      <button type="button" class="run-artifacts__library" @click="openLibrary">{{ t('nexusChat.artifacts.library') }}</button>
    </div>
    <ul class="run-artifacts__list">
      <li v-for="item in view.shown" :key="item.id" class="run-artifacts__item">
        <ArtifactFileIcon class="run-artifacts__icon" :file-name="item.file_name" />
        <button type="button" class="run-artifacts__open" :disabled="!canPreview(item)"
          :title="canPreview(item) ? t('artifactLibrary.preview') : item.file_name" @click="openPreview(item)">
          <span class="run-artifacts__name" :title="item.file_name">{{ item.file_name }}</span>
          <span class="run-artifacts__meta">{{ formatArtifactSize(item.file_size) }}</span>
        </button>
        <t-button variant="text" shape="square" size="small" :loading="!!downloading[item.id]"
          :title="t('artifactLibrary.download')" :aria-label="`${item.file_name} · ${t('artifactLibrary.download')}`"
          @click="download(item)">
          <template #icon><t-icon name="download" size="16px" /></template>
        </t-button>
      </li>
    </ul>
    <t-button v-if="view.hidden" variant="text" size="small" @click="expanded = true">
      {{ t('nexusChat.artifacts.showAll', { count: view.hidden }) }}
    </t-button>
    <t-button v-else-if="canCollapse" variant="text" size="small" @click="expanded = false">
      {{ t('nexusChat.artifacts.showLess') }}
    </t-button>

    <t-drawer v-model:visible="previewVisible" placement="right" size="min(880px, 92vw)" attach="body" :footer="false"
      :close-on-overlay-click="true" :close-on-esc-keydown="true" @closed="previewItem = null; previewBlob = null">
      <template #header>
        <div v-if="previewItem" class="run-artifacts__preview-head">
          <ArtifactFileIcon class="run-artifacts__icon" :file-name="previewItem.file_name" />
          <span class="run-artifacts__preview-title" :title="previewItem.file_name">{{ previewItem.file_name }}</span>
          <div ref="previewActions" class="run-artifacts__preview-actions" />
          <t-button variant="text" shape="square" size="small" :loading="!!downloading[previewItem.id]"
            :title="t('artifactLibrary.download')" :aria-label="t('artifactLibrary.download')" @click="download(previewItem)">
            <template #icon><t-icon name="download" size="16px" /></template>
          </t-button>
        </div>
      </template>
      <div v-if="previewItem" class="run-artifacts__preview-body">
        <DocumentPreview v-if="previewBlob" :key="previewItem.id" :toolbar-target="previewActions"
          :source-blob="previewBlob" :file-type="previewFileType" :file-name="previewItem.file_name"
          :active="previewVisible" fill-height />
        <div v-else-if="previewFailed" class="run-artifacts__state" role="alert">{{ t('artifactLibrary.downloadFailed') }}</div>
        <div v-else class="run-artifacts__state"><t-loading size="small" /></div>
      </div>
    </t-drawer>
  </div>
</template>

<style scoped>
.run-artifacts {
  display: flex; flex-direction: column; gap: 4px; margin: 8px 0 0; padding: 8px 10px; max-width: 560px;
  border: 1px solid var(--td-component-border); border-radius: var(--app-radius-md); background: var(--td-bg-color-container);
}
.run-artifacts__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.run-artifacts__title { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.run-artifacts__library {
  border: 0; background: transparent; padding: 0; cursor: pointer; color: var(--td-brand-color); font-size: var(--app-text-xs);
}
.run-artifacts__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.run-artifacts__item { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.run-artifacts__item .run-artifacts__icon,
.run-artifacts__preview-head .run-artifacts__icon { width: 24px; height: 28px; }
.run-artifacts__open {
  display: flex; flex: 1; min-width: 0; align-items: baseline; gap: 8px; padding: 2px 4px; border: 0; border-radius: var(--app-radius-sm);
  background: transparent; color: var(--td-text-color-primary); text-align: left; cursor: pointer;
}
.run-artifacts__open:disabled { cursor: default; }
.run-artifacts__open:not(:disabled):hover { background: var(--td-bg-color-container-hover); }
.run-artifacts__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--app-text-base); }
.run-artifacts__meta { flex-shrink: 0; color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.run-artifacts__preview-head { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; }
.run-artifacts__preview-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-artifacts__preview-actions { display: flex; align-items: center; }
.run-artifacts__preview-body { height: 100%; }
.run-artifacts__state { display: flex; align-items: center; justify-content: center; min-height: 160px; color: var(--td-text-color-secondary); }
</style>
