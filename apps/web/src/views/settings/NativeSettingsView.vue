<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { workspace } from '../../stores/workspace'
import { modelSettingsApi } from '../../api/modelSettings'
import { nativeApi, type NativePreferences, type MemoryData, type MemoryEntry, type MemoryDraft, type MemoryCapture } from '../../api/native'
import { i18n } from '../../i18n'
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
  } catch (e) { if (!signal.aborted && !disposed) error.value = e instanceof Error ? e.message : i18n.global.t('common.loadFailed') }
  finally { if (!signal.aborted && !disposed) loading.value = false }
}
async function act(action: () => Promise<void>, message: string) {
  if (busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try { await action(); if (!disposed) feedback.value = message }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : i18n.global.t('nativePage.actionFailed') }
  finally { if (!disposed) busy.value = false }
}
async function initialize() {
  try { if (!disposed) await load() }
  catch (e) { error.value = e instanceof Error ? e.message : i18n.global.t('common.spaceLoadFailed') }
}
// The space is chosen in the shell sidebar; a change reloads this page.
watch(tenant, () => { if (!disposed) void initialize() })
function review(draft: MemoryDraft) { selectedDraft.value = draft; selectedEntry.value = ''; title.value = ''; project.value = '' }
async function publish(approve: boolean) {
  const draft = selectedDraft.value
  if (!draft) return
  if (approve) { try { await ElMessageBox.confirm(i18n.global.t('nativePage.publishConfirm'), i18n.global.t('nativePage.publishTitle'), { confirmButtonText: i18n.global.t('nativePage.publishButton'), cancelButtonText: i18n.global.t('common.cancel') }) } catch { return } }
  await act(async () => { const entry = memories.value.entries.find(e => e.id === selectedEntry.value)
    await nativeApi.review(tenant.value, draft.id, { approve, title: title.value, project: project.value, ...(entry ? { entry_id: entry.id, expected_version: entry.version } : {}) }); await load()
  }, approve ? i18n.global.t('nativePage.published') : i18n.global.t('nativePage.rejected'))
}
async function inspect(entry: MemoryEntry, version?: number) {
  await act(async () => { const response = await nativeApi.readMemory(tenant.value, entry.id, version); detail.value = response.content; detailEntry.value = entry; detailVersion.value = response.version }, '')
}
async function archive(entry: MemoryEntry) {
  try { await ElMessageBox.confirm(i18n.global.t('nativePage.archiveConfirm', { title: entry.title }), i18n.global.t('nativePage.archiveTitle'), { confirmButtonText: i18n.global.t('nativePage.archiveButton'), cancelButtonText: i18n.global.t('common.cancel') }) } catch { return }
  await act(async () => { await nativeApi.archive(tenant.value, entry.id); await load() }, i18n.global.t('nativePage.archived'))
}
async function enableTool(name: string) { await act(async () => { await nativeApi.enableTool(tenant.value, name); await load() }, i18n.global.t('nativePage.toolRegistered')) }
async function savePreferences() { if (data.value) await act(async () => { data.value = await nativeApi.saveSettings(tenant.value, data.value!) }, i18n.global.t('nativePage.defaultsSaved')) }
async function saveCapture() {
  if (capture.value.enabled && !capture.value.model_profile_version_id) { error.value = i18n.global.t('nativePage.captureNeedsModel'); return }
  await act(async () => { capture.value = await nativeApi.saveCapture(tenant.value, capture.value) }, capture.value.enabled ? i18n.global.t('nativePage.captureOn') : i18n.global.t('nativePage.captureOff'))
}
async function restoreVersion() { if (detailEntry.value) await act(async () => { await nativeApi.restore(tenant.value, detailEntry.value!.id, detailVersion.value, detailEntry.value!.version); await load() }, i18n.global.t('nativePage.restored')) }
onMounted(initialize)
onBeforeUnmount(() => { disposed = true; controller?.abort() })
</script>
<template>
  <main class="native-settings" v-loading="loading" :aria-busy="busy || loading">
    <header><div><p class="eyebrow">{{ $t('modelPage.eyebrow') }}</p><h1>{{ $t('shell.titles.personalNative') }}</h1></div><el-button :disabled="loading || busy" @click="initialize">{{ $t('common.refresh') }}</el-button></header>
    <p class="intro">{{ $t('nativePage.intro') }}</p>
    <el-alert v-if="error" type="error" :title="error" :closable="false" /><p role="status" aria-live="polite">{{ feedback }}</p>
    <template v-if="data">
      <section v-for="(fields, group) in data.fields" :key="group" class="panel">
        <h2>{{ group === 'budgets' ? $t('nativePage.budgets') : $t('nativePage.policy') }}</h2>
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
      <div v-if="data.can_enable_tools" class="panel"><h2>{{ $t('nativePage.toolsTitle') }}</h2><p>{{ $t('nativePage.toolsIntro') }}</p><el-button v-for="tool in data.available_tools.filter(t => !t.enabled)" :key="tool.id" :disabled="busy" @click="enableTool(tool.id)">{{ $t('nativePage.enableTool', { name: tool.label }) }}</el-button></div>
      <el-button type="primary" :loading="busy" :disabled="loading" @click="savePreferences">{{ $t('nativePage.saveDefaults') }}</el-button>
    </template>
    <section class="panel" aria-labelledby="capture-title"><h2 id="capture-title">{{ $t('nativePage.captureTitle') }}</h2>
      <p class="intro">{{ $t('nativePage.captureIntro') }}</p>
      <el-form label-position="top" class="fields">
        <el-form-item :label="$t('nativePage.captureEnabled')" for="capture-enabled"><el-switch id="capture-enabled" v-model="capture.enabled" :disabled="busy || loading" /></el-form-item>
        <el-form-item :label="$t('nativePage.captureModel')" for="capture-model"><el-select id="capture-model" v-model="capture.model_profile_version_id" clearable :placeholder="$t('nativePage.pickModel')" :disabled="busy || loading"><el-option v-for="model in models" :key="model.id" :label="model.label" :value="model.id" /></el-select></el-form-item>
        <el-form-item :label="$t('nativePage.capacityPolicy')" for="capture-policy"><el-select id="capture-policy" v-model="capture.capacity_policy" :disabled="busy || loading">:label="$t('nativePage.rejectNew')" value="reject" /><el-option :label="$t('nativePage.evictAuto')" value="evict_auto" /></el-select></el-form-item>
      </el-form>
      <el-button type="primary" :loading="busy" :disabled="loading" @click="saveCapture">{{ $t('nativePage.captureSave') }}</el-button>
    </section>
    <section class="panel"><h2>{{ $t('nativePage.publishedTitle') }}</h2><p class="intro">{{ $t('nativePage.publishedIntro') }}</p>
      <el-empty v-if="!memories.entries.length" :description="$t('nativePage.noPublished')" />
      <article v-for="entry in memories.entries" :key="entry.id"><strong>{{ entry.title }}</strong> · {{ entry.kind }} · {{ $t('nativePage.versionLabel', { n: entry.version }) }}
        <el-button :disabled="busy" @click="inspect(entry)">{{ $t('nativePage.inspect', { title: entry.title }) }}</el-button><el-button :disabled="busy" @click="archive(entry)">{{ $t('nativePage.archive', { title: entry.title }) }}</el-button></article>
    </section>
    <section class="panel"><h2>{{ $t('nativePage.draftsTitle') }}</h2><el-empty v-if="!memories.drafts.length" :description="$t('nativePage.noDrafts')" />
      <article v-for="draft in memories.drafts" :key="draft.id"><span>{{ draft.kind }}</span><pre>{{ draft.diff }}</pre><el-button :disabled="busy" @click="review(draft)">{{ $t('nativePage.reviewDraft') }}</el-button></article>
    </section>
    <el-dialog :model-value="!!selectedDraft" :title="$t('nativePage.reviewTitle')" width="min(640px, 94vw)" :close-on-click-modal="!busy" @close="selectedDraft = null">
      <pre>{{ selectedDraft?.diff }}</pre><el-form label-position="top">
        <el-form-item :label="$t('nativePage.updateExisting')"><el-select v-model="selectedEntry" clearable><el-option v-for="entry in memories.entries.filter(e => e.kind === selectedDraft?.kind)" :key="entry.id" :label="entry.title" :value="entry.id" /></el-select></el-form-item>
        <el-form-item :label="$t('nativePage.titleField')"><el-input v-model="title" maxlength="160" /></el-form-item><el-form-item :label="$t('nativePage.projectField')"><el-input v-model="project" maxlength="160" /></el-form-item>
      </el-form><el-button type="primary" :disabled="busy || !title.trim()" @click="publish(true)">{{ $t('nativePage.confirmPublish') }}</el-button><el-button :disabled="busy" @click="publish(false)">{{ $t('nativePage.rejectDraft') }}</el-button>
    </el-dialog>
    <el-dialog :model-value="!!detailEntry" :title="$t('nativePage.versionsTitle')" width="min(700px, 94vw)" @close="detailEntry = null">
      <pre>{{ detail }}</pre><label for="memory-version">{{ $t('nativePage.historyVersion') }}</label><el-input-number id="memory-version" v-model="detailVersion" :min="1" :max="detailEntry?.version || 1" />
      <el-button :disabled="busy" @click="detailEntry && inspect(detailEntry, detailVersion)">{{ $t('nativePage.readVersion') }}</el-button>
      <el-button :disabled="busy || !detailEntry || detailVersion === detailEntry.version" @click="restoreVersion">{{ $t('nativePage.restoreVersion') }}</el-button>
    </el-dialog>
  </main>
</template>
<style scoped>
.native-settings { max-width: 1100px; }.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin: 24px 0; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin-top: 20px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; }
article { padding: 16px 0; border-bottom: 1px solid var(--border); }@media(max-width:700px) { .fields { grid-template-columns: 1fr; }.panel { padding: 16px; } }
</style>
