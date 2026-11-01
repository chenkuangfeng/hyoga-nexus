<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { modelSettingsApi } from '../api/modelSettings'
import { nativeApi } from '../api/native'
import { i18n } from '../i18n'
const props = defineProps<{ tenant: string; session: string; disabled: boolean }>()
const emit = defineEmits<{ created: [id: string] }>()
const opened = ref(false), busy = ref(false), error = ref(''), selected = ref(''), models = ref<{ id: string; label: string }[]>([])
let controller: AbortController | undefined, disposed = false
async function open() {
  opened.value = true; busy.value = true; error.value = ''; selected.value = ''; models.value = []
  controller?.abort(); controller = new AbortController()
  try { const rows = await modelSettingsApi.list(props.tenant, controller.signal); if (!disposed) models.value = rows.providers.flatMap(p => p.models.map(m => ({ id: m.version_id, label: `${p.name} / ${m.name}` }))) }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : i18n.global.t('chat.branch.modelsFailed') }
  finally { if (!disposed) busy.value = false }
}
async function branch() {
  if (busy.value || !selected.value) return
  busy.value = true; error.value = ''
  try { const result = await nativeApi.branch(props.tenant, props.session, selected.value); if (!disposed) { opened.value = false; emit('created', result.id) } }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : i18n.global.t('chat.branch.createFailed') }
  finally { if (!disposed) busy.value = false }
}
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template>
  <el-button :disabled="disabled || !session" @click="open">{{ $t('chat.branch.button') }}</el-button>
  <el-dialog v-model="opened" :title="$t('chat.branch.title')" width="min(520px, 94vw)" :close-on-click-modal="!busy">
    <p>{{ $t('chat.branch.intro') }}</p><label for="branch-model">{{ $t('chat.branch.targetModel') }}</label>
    <el-select id="branch-model" v-model="selected" :disabled="busy" :placeholder="$t('chat.branch.pick')"><el-option v-for="model in models" :key="model.id" :label="model.label" :value="model.id" /></el-select>
    <p v-if="error" role="alert">{{ error }}</p><el-button :loading="busy" :disabled="!selected" type="primary" @click="branch">{{ $t('chat.branch.create') }}</el-button>
  </el-dialog>
</template>
