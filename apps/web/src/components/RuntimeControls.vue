<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { nativeApi, type Approval } from '../api/native'
import type { Run } from '../types/chat'
import { i18n } from '../i18n'
const props = defineProps<{ tenant: string; run: Run }>()
const emit = defineEmits<{ resume: [] }>()
const correction = ref(''), approvals = ref<Approval[]>([]), busy = ref(false), feedback = ref(''), error = ref('')
let generation = 0, disposed = false, pendingKey = ''
watch(() => [props.tenant, props.run.id, props.run.status], async () => {
  const current = ++generation
  approvals.value = []; feedback.value = ''; error.value = ''; correction.value = ''; pendingKey = ''
  if (props.run.status === 'waiting_approval') {
    try { const rows = await nativeApi.approvals(props.tenant, props.run.id); if (!disposed && current === generation) approvals.value = rows }
    catch (e) { if (!disposed && current === generation) error.value = e instanceof Error ? e.message : i18n.global.t('chat.controls.approvalsFailed') }
  }
}, { immediate: true })
async function steer() {
  if (busy.value || !correction.value.trim()) return
  busy.value = true; error.value = ''; pendingKey ||= crypto.randomUUID(); const current = generation
  try { await nativeApi.steer(props.tenant, props.run.id, correction.value, pendingKey); if (!disposed && current === generation) { correction.value = ''; pendingKey = ''; feedback.value = i18n.global.t('chat.controls.steerQueued') } }
  catch (e) { if (!disposed && current === generation) error.value = e instanceof Error ? e.message : i18n.global.t('chat.controls.steerFailed') }
  finally { busy.value = false }
}
async function approve(id: string, value: boolean) {
  if (busy.value) return
  busy.value = true; error.value = ''; const current = generation
  try { await nativeApi.approve(props.tenant, props.run.id, id, value); if (!disposed && current === generation) { feedback.value = value ? i18n.global.t('chat.controls.approvedMsg') : i18n.global.t('chat.controls.rejectedMsg'); emit('resume') } }
  catch (e) { if (!disposed && current === generation) error.value = e instanceof Error ? e.message : i18n.global.t('chat.controls.approvalFailed') }
  finally { busy.value = false }
}
onBeforeUnmount(() => { disposed = true; generation++ })
</script>
<template>
  <section v-if="run.status === 'running' || run.status === 'waiting_approval'" class="runtime-controls" :aria-label="$t('chat.controls.runControls')">
    <form v-if="run.status === 'running'" @submit.prevent="steer">
      <label for="run-correction">{{ $t('chat.controls.steerLabel') }}</label><el-input id="run-correction" v-model="correction" type="textarea" :rows="2" :disabled="busy" maxlength="8000" @input="pendingKey = ''" />
      <el-button native-type="submit" :disabled="busy || !correction.trim()">{{ $t('chat.controls.steer') }}</el-button>
    </form>
    <article v-for="approval in approvals" :key="approval.id"><h3>{{ $t('chat.controls.approvalTitle', { name: approval.tool_name }) }}</h3><pre>{{ JSON.stringify(approval.arguments, null, 2) }}</pre>
      <el-button :disabled="busy" type="primary" @click="approve(approval.id, true)">{{ $t('chat.controls.approve') }}</el-button><el-button :disabled="busy" @click="approve(approval.id, false)">{{ $t('chat.controls.reject') }}</el-button>
    </article>
    <p v-if="error" role="alert">{{ error }}</p><p role="status" aria-live="polite">{{ feedback }}</p>
  </section>
</template>
<style scoped>
.runtime-controls { margin: 20px 0; padding-top: 16px; border-top: 1px solid var(--border); } pre { white-space: pre-wrap; overflow-wrap: anywhere; } label { display: block; margin-bottom: 8px; }
</style>
