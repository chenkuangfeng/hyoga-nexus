<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { workspace } from '../../stores/workspace'
import { modelSettingsApi } from '../../api/modelSettings'
import { nativeApi, type NativePreferences, type MemoryData, type MemoryEntry, type MemoryDraft, type MemoryCapture } from '../../api/native'
const tenant = computed(() => workspace.tenantId), data = ref<NativePreferences | null>(null)
const memories = ref<MemoryData>({ entries: [], drafts: [] }), models = ref<{ id: string; label: string }[]>([])
const capture = ref<MemoryCapture>({ enabled: false, model_profile_version_id: null, capacity_policy: 'reject' })
const loading = ref(false), busy = ref(false), error = ref(''), feedback = ref('')
const title = ref(''), project = ref(''), selectedEntry = ref(''), selectedDraft = ref<MemoryDraft | null>(null)
const detail = ref(''), detailEntry = ref<MemoryEntry | null>(null), detailVersion = ref(1)
let controller: AbortController | undefined, disposed = false
async function load() {
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  if (!tenant.value) return
  loading.value = true; error.value = ''; data.value = null; memories.value = { entries: [], drafts: [] }; selectedDraft.value = null; detailEntry.value = null
  try {
    const [preferences, memory, providers, captureRow] = await Promise.all([nativeApi.settings(tenant.value, signal), nativeApi.memory(tenant.value, signal), modelSettingsApi.list(tenant.value, signal), nativeApi.captureSettings(tenant.value, signal)])
    if (!signal.aborted && !disposed) { data.value = preferences; memories.value = memory; capture.value = captureRow; models.value = providers.providers.flatMap(p => p.models.map(m => ({ id: m.version_id, label: `${p.name} / ${m.name}` }))) }
  } catch (e) { if (!signal.aborted && !disposed) error.value = e instanceof Error ? e.message : '加载失败' }
  finally { if (!signal.aborted && !disposed) loading.value = false }
}
async function act(action: () => Promise<void>, message: string) {
  if (busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try { await action(); if (!disposed) feedback.value = message }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '操作失败' }
  finally { if (!disposed) busy.value = false }
}
async function initialize() {
  try { if (!disposed) await load() }
  catch (e) { error.value = e instanceof Error ? e.message : '空间加载失败' }
}
// The space is chosen in the shell sidebar; a change reloads this page.
watch(tenant, () => { if (!disposed) void initialize() })
function review(draft: MemoryDraft) { selectedDraft.value = draft; selectedEntry.value = ''; title.value = ''; project.value = '' }
async function publish(approve: boolean) {
  const draft = selectedDraft.value
  if (!draft) return
  if (approve) { try { await ElMessageBox.confirm('请确认内容已验证、可长期复用且不含密钥。发布后将进入模型可读取的记忆索引。', '确认发布记忆', { confirmButtonText: '发布', cancelButtonText: '取消' }) } catch { return } }
  await act(async () => { const entry = memories.value.entries.find(e => e.id === selectedEntry.value)
    await nativeApi.review(tenant.value, draft.id, { approve, title: title.value, project: project.value, ...(entry ? { entry_id: entry.id, expected_version: entry.version } : {}) }); await load()
  }, approve ? '记忆已发布' : '草稿已拒绝')
}
async function inspect(entry: MemoryEntry, version?: number) {
  await act(async () => { const response = await nativeApi.readMemory(tenant.value, entry.id, version); detail.value = response.content; detailEntry.value = entry; detailVersion.value = response.version }, '')
}
async function archive(entry: MemoryEntry) {
  try { await ElMessageBox.confirm(`归档“${entry.title}”后模型将无法继续读取，历史版本保留。`, '归档记忆', { confirmButtonText: '归档', cancelButtonText: '取消' }) } catch { return }
  await act(async () => { await nativeApi.archive(tenant.value, entry.id); await load() }, '记忆已归档')
}
async function enableTool(name: string) { await act(async () => { await nativeApi.enableTool(tenant.value, name); await load() }, '工具已登记，可选择绑定') }
async function savePreferences() { if (data.value) await act(async () => { data.value = await nativeApi.saveSettings(tenant.value, data.value!) }, '默认设置已保存') }
async function saveCapture() {
  if (capture.value.enabled && !capture.value.model_profile_version_id) { error.value = '开启自动捕获前请先选择捕获模型'; return }
  await act(async () => { capture.value = await nativeApi.saveCapture(tenant.value, capture.value) }, capture.value.enabled ? '自动捕获已开启' : '自动捕获已关闭')
}
async function restoreVersion() { if (detailEntry.value) await act(async () => { await nativeApi.restore(tenant.value, detailEntry.value!.id, detailVersion.value, detailEntry.value!.version); await load() }, '已创建恢复版本') }
onMounted(initialize)
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template>
  <main class="native-settings" v-loading="loading" :aria-busy="busy || loading">
    <header><div><p class="eyebrow">HYOGA NEXUS / 用户设置</p><h1>Native 执行与记忆</h1></div><el-button :disabled="loading || busy" @click="initialize">刷新</el-button></header>
    <p class="intro">个人默认设置只应用于之后创建的智能体，已有版本和会话保持原配置。工具仍需单独授权。</p>
    <el-alert v-if="error" type="error" :title="error" :closable="false" /><p role="status" aria-live="polite">{{ feedback }}</p>
    <template v-if="data">
      <section v-for="(fields, group) in data.fields" :key="group" class="panel">
        <h2>{{ group === 'budgets' ? '运行预算' : '执行策略与项目上下文' }}</h2>
        <el-form label-position="top" class="fields">
          <el-form-item v-for="field in fields" :key="field.name" :label="field.label" :for="'native-' + field.name">
            <el-switch v-if="field.type === 'boolean'" :id="'native-' + field.name" :model-value="Boolean(data.settings[group][field.name])" :disabled="busy" @update:model-value="(value: boolean | string | number) => data!.settings[group][field.name] = Boolean(value)" />
            <el-input-number v-else-if="field.type === 'number'" :id="'native-' + field.name" :model-value="Number(data.settings[group][field.name])" :min="0" :disabled="busy" @update:model-value="(value: number | undefined) => data!.settings[group][field.name] = value ?? 0" />
            <el-select v-else-if="field.type === 'tools'" :id="'native-' + field.name" :model-value="data.settings[group][field.name] as string[]" multiple :disabled="busy" @update:model-value="(value: string[]) => data!.settings[group][field.name] = value"><el-option v-for="tool in data.available_tools.filter(t => t.enabled)" :key="tool.id" :label="tool.label" :value="tool.id" /></el-select>
            <el-select v-else-if="field.type === 'models'" :id="'native-' + field.name" :model-value="data.settings[group][field.name] as string[]" multiple :disabled="busy" @update:model-value="(value: string[]) => data!.settings[group][field.name] = value"><el-option v-for="model in models" :key="model.id" :label="model.label" :value="model.id" /></el-select>
            <el-input v-else :id="'native-' + field.name" :model-value="String(data.settings[group][field.name])" :type="field.name === 'project_context' ? 'textarea' : 'text'" :disabled="busy" @update:model-value="(value: string) => data!.settings[group][field.name] = value" />
          </el-form-item>
        </el-form>
      </section>
      <div v-if="data.can_enable_tools" class="panel"><h2>空间工具登记</h2><p>登记后仍需选择绑定；登记本身不授予模型调用权限。</p><el-button v-for="tool in data.available_tools.filter(t => !t.enabled)" :key="tool.id" :disabled="busy" @click="enableTool(tool.id)">启用 {{ tool.label }}</el-button></div>
      <el-button type="primary" :loading="busy" :disabled="loading" @click="savePreferences">保存 Native 默认设置</el-button>
    </template>
    <section class="panel" aria-labelledby="capture-title"><h2 id="capture-title">自动捕获（默认关闭）</h2>
      <p class="intro">开启后，已完成的对话会由下方所选模型整理为待审核草稿；草稿必须人工确认才会进入模型提示。</p>
      <el-form label-position="top" class="fields">
        <el-form-item label="开启自动捕获" for="capture-enabled"><el-switch id="capture-enabled" v-model="capture.enabled" :disabled="busy || loading" /></el-form-item>
        <el-form-item label="捕获模型（每次捕获都会调用它）" for="capture-model"><el-select id="capture-model" v-model="capture.model_profile_version_id" clearable placeholder="请选择模型" :disabled="busy || loading"><el-option v-for="model in models" :key="model.id" :label="model.label" :value="model.id" /></el-select></el-form-item>
        <el-form-item label="记忆预算已满时" for="capture-policy"><el-select id="capture-policy" v-model="capture.capacity_policy" :disabled="busy || loading"><el-option label="拒绝新草稿（默认）" value="reject" /><el-option label="自动归档最旧的自动捕获条目（手写条目不会被归档）" value="evict_auto" /></el-select></el-form-item>
      </el-form>
      <el-button type="primary" :loading="busy" :disabled="loading" @click="saveCapture">保存自动捕获设置</el-button>
    </section>
    <section class="panel"><h2>已发布的个人记忆与 SOP</h2><p class="intro">只列出已人工确认的版本；草稿不会自动进入模型提示。</p>
      <el-empty v-if="!memories.entries.length" description="暂无已发布记忆" />
      <article v-for="entry in memories.entries" :key="entry.id"><strong>{{ entry.title }}</strong> · {{ entry.kind }} · 版本 {{ entry.version }}
        <el-button :disabled="busy" @click="inspect(entry)">查看 {{ entry.title }}</el-button><el-button :disabled="busy" @click="archive(entry)">归档 {{ entry.title }}</el-button></article>
    </section>
    <section class="panel"><h2>待审核草稿</h2><el-empty v-if="!memories.drafts.length" description="暂无待审核草稿" />
      <article v-for="draft in memories.drafts" :key="draft.id"><span>{{ draft.kind }}</span><pre>{{ draft.diff }}</pre><el-button :disabled="busy" @click="review(draft)">审核此草稿</el-button></article>
    </section>
    <el-dialog :model-value="!!selectedDraft" title="审核记忆草稿" width="min(640px, 94vw)" :close-on-click-modal="!busy" @close="selectedDraft = null">
      <pre>{{ selectedDraft?.diff }}</pre><el-form label-position="top">
        <el-form-item label="更新已有记忆（留空创建新条目）"><el-select v-model="selectedEntry" clearable><el-option v-for="entry in memories.entries.filter(e => e.kind === selectedDraft?.kind)" :key="entry.id" :label="entry.title" :value="entry.id" /></el-select></el-form-item>
        <el-form-item label="标题"><el-input v-model="title" maxlength="160" /></el-form-item><el-form-item label="项目（可选）"><el-input v-model="project" maxlength="160" /></el-form-item>
      </el-form><el-button type="primary" :disabled="busy || !title.trim()" @click="publish(true)">确认并发布</el-button><el-button :disabled="busy" @click="publish(false)">拒绝草稿</el-button>
    </el-dialog>
    <el-dialog :model-value="!!detailEntry" title="记忆内容与版本" width="min(700px, 94vw)" @close="detailEntry = null">
      <pre>{{ detail }}</pre><label for="memory-version">历史版本</label><el-input-number id="memory-version" v-model="detailVersion" :min="1" :max="detailEntry?.version || 1" />
      <el-button :disabled="busy" @click="detailEntry && inspect(detailEntry, detailVersion)">读取版本</el-button>
      <el-button :disabled="busy || !detailEntry || detailVersion === detailEntry.version" @click="restoreVersion">恢复为新版本</el-button>
    </el-dialog>
  </main>
</template>
<style scoped>
.native-settings { max-width: 1100px; }.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin: 24px 0; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin-top: 20px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; }
article { padding: 16px 0; border-bottom: 1px solid var(--border); }@media(max-width:700px) { .fields { grid-template-columns: 1fr; }.panel { padding: 16px; } }
</style>
