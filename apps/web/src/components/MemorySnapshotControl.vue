<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { memorySnapshotApi, type MemorySnapshot } from '../api/memorySnapshot'

/** Shows whether this session's memory index is frozen and offers an explicit refresh.
 * Only the session's owner can read or refresh it; for anyone else the control stays hidden.
 */
const props = defineProps<{ tenant: string; session: string; disabled: boolean }>()
const snapshot = ref<MemorySnapshot | null>(null), busy = ref(false), error = ref('')
let controller: AbortController | undefined, disposed = false

async function load() {
  snapshot.value = null; error.value = ''
  if (!props.tenant || !props.session) return
  controller?.abort(); controller = new AbortController()
  try { const result = await memorySnapshotApi.status(props.tenant, props.session, controller.signal); if (!disposed) snapshot.value = result }
  catch (e) { if (!disposed && !(e instanceof DOMException)) snapshot.value = null }
}
async function refresh() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await memorySnapshotApi.refresh(props.tenant, props.session); await load() }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '刷新失败' }
  finally { if (!disposed) busy.value = false }
}
watch(() => [props.tenant, props.session], () => void load(), { immediate: true })
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>

<template>
  <div v-if="snapshot" class="memory-snapshot" aria-live="polite">
    <p class="muted">
      <template v-if="!snapshot.exists">下一次运行时固定本会话的记忆索引。</template>
      <template v-else-if="snapshot.stale">记忆索引已固定，之后有记忆更新，刷新后下一次运行生效。</template>
      <template v-else>记忆索引已固定，与当前记忆一致。</template>
    </p>
    <el-button v-if="snapshot.exists" size="small" :disabled="disabled || busy" @click="refresh">刷新记忆快照</el-button>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.memory-snapshot { margin: 8px 0; font-size: 13px; }
.muted { color: var(--muted-text); line-height: 1.5; margin: 0 0 6px; }
.error { color: var(--el-color-danger); margin: 6px 0 0; }
</style>
