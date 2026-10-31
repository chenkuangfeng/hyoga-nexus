<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { modelSettingsApi } from '../api/modelSettings'
import { nativeApi } from '../api/native'
const props = defineProps<{ tenant: string; session: string; disabled: boolean }>()
const emit = defineEmits<{ created: [id: string] }>()
const opened = ref(false), busy = ref(false), error = ref(''), selected = ref(''), models = ref<{ id: string; label: string }[]>([])
let controller: AbortController | undefined, disposed = false
async function open() {
  opened.value = true; busy.value = true; error.value = ''; selected.value = ''; models.value = []
  controller?.abort(); controller = new AbortController()
  try { const rows = await modelSettingsApi.list(props.tenant, controller.signal); if (!disposed) models.value = rows.providers.flatMap(p => p.models.map(m => ({ id: m.version_id, label: `${p.name} / ${m.name}` }))) }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '模型加载失败' }
  finally { if (!disposed) busy.value = false }
}
async function branch() {
  if (busy.value || !selected.value) return
  busy.value = true; error.value = ''
  try { const result = await nativeApi.branch(props.tenant, props.session, selected.value); if (!disposed) { opened.value = false; emit('created', result.id) } }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '创建分支失败' }
  finally { if (!disposed) busy.value = false }
}
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template>
  <el-button :disabled="disabled || !session" @click="open">保留历史切换模型</el-button>
  <el-dialog v-model="opened" title="创建模型分支" width="min(520px, 94vw)" :close-on-click-modal="!busy">
    <p>当前会话与模型保持原样。新分支复制当前仍有权使用的历史与工具绑定，并记录来源。</p><label for="branch-model">目标模型</label>
    <el-select id="branch-model" v-model="selected" :disabled="busy" placeholder="选择已配置模型"><el-option v-for="model in models" :key="model.id" :label="model.label" :value="model.id" /></el-select>
    <p v-if="error" role="alert">{{ error }}</p><el-button :loading="busy" :disabled="!selected" type="primary" @click="branch">创建并打开分支</el-button>
  </el-dialog>
</template>
