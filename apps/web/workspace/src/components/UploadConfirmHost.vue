<script setup lang="ts">
import UploadConfirmDialog from '@nexus-web/core/components/knowledge/documents/UploadConfirmDialog.vue'
import { useUploadConfirmStore } from '@/stores/uploadConfirm'
import { useUIStore } from '@/stores/ui'

const uploadConfirmStore = useUploadConfirmStore()
const uiStore = useUIStore()

const handleConfirm = (payload: Parameters<typeof uploadConfirmStore.resolveConfirm>[0]) => {
  uploadConfirmStore.resolveConfirm(payload)
}

const handleCancel = () => {
  uploadConfirmStore.rejectConfirm()
}
</script>

<template>
  <UploadConfirmDialog
    v-model:visible="uploadConfirmStore.visible"
    :mode="uploadConfirmStore.mode"
    :kb-info="uploadConfirmStore.kbInfo"
    :files="uploadConfirmStore.files"
    :urls="uploadConfirmStore.urls"
    :tag-ids="uploadConfirmStore.tagIds"
    :manual-preview="uploadConfirmStore.manual"
    :reparse-preview="uploadConfirmStore.reparse"
    :accept-file-types="uploadConfirmStore.acceptFileTypes"
    :supported-file-types="uploadConfirmStore.supportedFileTypes"
    :target-folder="uploadConfirmStore.targetFolder"
    :folder-options="uploadConfirmStore.folderOptions"
    @confirm="handleConfirm"
    @cancel="handleCancel"
    @open-model-settings="uiStore.openSettings('models', $event)"
  />
</template>
