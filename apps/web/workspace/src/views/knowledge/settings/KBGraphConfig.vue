<script setup lang="ts">
/**
 * Graph settings of a knowledge base on the Nexus API (openspec 2026-11-06-knowledge-base K2.6).
 *
 * Replaces WeKnora's manual extraction playground: mode (entity / GraphRAG light / GraphRAG general), graph
 * store (builtin or Neo4j, the latter marked planned), the chat model used for extraction and reports, entity
 * and relation types and extra instructions. For a saved base it also shows the build state, lets the owner
 * rebuild, and opens a read-only browser of the visible graph.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import CapabilityBadge from '@/components/knowledge/CapabilityBadge.vue'
import KnowledgeGraphBrowser from '@/components/knowledge/KnowledgeGraphBrowser.vue'
import { listModels } from '@nexus-web/core/api/model/index'
import { createGraphStore, fetchGraphStatus, listGraphStores, rebuildGraph, testGraphStore, type GraphStatus, type GraphStoreItem } from '@nexus-web/core/api/nexus-knowledge'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useKnowledgeCapabilitiesStore } from '@/stores/knowledgeCapabilities'

export interface GraphForm {
  mode: string
  store: string
  model_id: string
  entity_types: string[]
  relation_types: string[]
  instructions: string
}

const props = defineProps<{ modelValue: GraphForm, kbId?: string, readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: GraphForm): void }>()

const auth = useAuthStore()
const capabilities = useKnowledgeCapabilitiesStore()
const models = ref<Array<{ id: string, name: string }>>([])
const stores = ref<GraphStoreItem[]>([])
const plannedEngines = ref<Array<{ engine: string, name: string, status: string }>>([])
const status = ref<GraphStatus | null>(null)
const showBrowser = ref(false)
const rebuilding = ref(false)
const registering = ref(false)
const draft = ref({ name: '', url: '', username: 'neo4j', password: '', database: 'neo4j' })
const draftBusy = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

const MODES = [
  { key: 'entity', label: '实体关系图谱', desc: '抽取实体与关系，按名称精确查询（query_knowledge_graph）' },
  { key: 'graphrag_light', label: 'GraphRAG Light', desc: '实体与关系检索，附带邻近实体' },
  { key: 'graphrag_general', label: 'GraphRAG General', desc: '再加社区划分与社区报告，适合总括性问题' },
]

const tenant = () => auth.effectiveTenantId || ''
const patch = (changes: Partial<GraphForm>) => emit('update:modelValue', { ...props.modelValue, ...changes })
const building = computed(() => ['pending', 'running'].includes(status.value?.latest?.state || ''))
const disabled = computed(() => !!props.readonly)

async function refresh() {
  if (!props.kbId || !tenant()) return
  try {
    status.value = await fetchGraphStatus(tenant(), props.kbId)
  } catch { status.value = null }
}

async function loadStores() {
  const listed = await listGraphStores(tenant())
  stores.value = listed.items
  plannedEngines.value = listed.engines.filter(item => item.status === 'planned')
}

function draftBody() {
  return { name: draft.value.name.trim(), engine: 'neo4j', connection_config: {
    url: draft.value.url.trim(), username: draft.value.username.trim(), password: draft.value.password,
    database: draft.value.database.trim() || 'neo4j' } }
}

async function testDraft() {
  draftBusy.value = true
  try {
    const result = await testGraphStore(tenant(), draftBody())
    if (result.ok) MessagePlugin.success('连接成功')
    else MessagePlugin.error(result.message || '连接失败')
  } catch (error) { MessagePlugin.error((error as Error)?.message || '连接失败') } finally { draftBusy.value = false }
}

async function saveDraft() {
  if (!draft.value.name.trim() || !draft.value.url.trim()) { MessagePlugin.warning('请填写名称和地址'); return }
  draftBusy.value = true
  try {
    const created: any = await createGraphStore(tenant(), draftBody())
    await loadStores()
    patch({ store: created.id })
    registering.value = false
    draft.value = { name: '', url: '', username: 'neo4j', password: '', database: 'neo4j' }
    MessagePlugin.success('已登记')
  } catch (error) { MessagePlugin.error((error as Error)?.message || '登记失败') } finally { draftBusy.value = false }
}

async function rebuild() {
  if (!props.kbId) return
  rebuilding.value = true
  try {
    await rebuildGraph(tenant(), props.kbId)
    MessagePlugin.success('已加入构建队列')
    await refresh()
  } catch (error) {
    MessagePlugin.error((error as Error)?.message || '重建失败')
  } finally { rebuilding.value = false }
}

function stateText(build: GraphStatus['latest']): string {
  if (!build) return ''
  const done = build.progress?.done, total = build.progress?.total
  const labels: Record<string, string> = { pending: '排队中', running: '构建中', failed: '失败', cancelled: '已取消' }
  const where = build.stage ? `（${build.stage}${total ? ` ${done}/${total}` : ''}）` : ''
  return `${labels[build.state] || build.state}${build.state === 'running' ? where : ''}`
}

onMounted(async () => {
  void capabilities.ensureLoaded()
  try { models.value = (await listModels('KnowledgeQA')).map(m => ({ id: m.id || '', name: m.display_name || m.name })) } catch { models.value = [] }
  try { await loadStores() } catch { stores.value = [] }
  await refresh()
  timer = setInterval(() => { if (building.value) void refresh() }, 5000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
watch(() => props.kbId, () => { void refresh() })

const typesText = (value: string[]) => value.join('、')
const parseTypes = (text: string) => text.split(/[、,，\n]/).map(item => item.trim()).filter(Boolean)
</script>

<template>
  <div class="kb-graph-config">
    <div class="section-header">
      <h2>知识图谱 <CapabilityBadge group="indexing" capability="graph" /></h2>
      <p class="section-description">
        从文档抽取实体与关系，检索时补充关联信息。构建使用创建者的对话模型，文档变化后自动重建（只对新增文本调用模型）。
      </p>
    </div>

    <div class="setting-row">
      <label>图谱模式</label>
      <t-radio-group :value="modelValue.mode" :disabled="disabled" @change="(v: string) => patch({ mode: v })">
        <t-radio v-for="item in MODES" :key="item.key" :value="item.key"
          :disabled="!capabilities.available('graph_mode', item.key)">
          {{ item.label }}<CapabilityBadge group="graph_mode" :capability="item.key" />
          <span class="mode-desc">{{ item.desc }}</span>
        </t-radio>
      </t-radio-group>
    </div>

    <div class="setting-row">
      <label>图存储</label>
      <t-select :value="modelValue.store" :disabled="disabled" style="max-width: 320px" @change="(v: string) => patch({ store: v })">
        <t-option v-for="item in stores" :key="item.id" :value="item.id" :label="item.name">
          {{ item.name }}<CapabilityBadge group="graph_store" :capability="item.engine" />
        </t-option>
        <t-option v-for="item in plannedEngines" :key="item.engine" :value="item.engine" :label="item.name" disabled>
          {{ item.name }}<CapabilityBadge group="graph_store" :capability="item.engine" />
        </t-option>
      </t-select>
      <p class="muted">外部图存储（Neo4j）由空间管理员登记，连接信息加密保存。
        <t-link theme="primary" @click="registering = true">登记 Neo4j</t-link></p>
      <t-dialog v-model:visible="registering" header="登记 Neo4j 图存储" :confirm-btn="{ content: '保存', loading: draftBusy }"
        @confirm="saveDraft">
        <t-form label-align="top">
          <t-form-item label="名称"><t-input v-model="draft.name" /></t-form-item>
          <t-form-item label="地址（HTTP）"><t-input v-model="draft.url" placeholder="http://host:7474" /></t-form-item>
          <t-form-item label="用户名"><t-input v-model="draft.username" /></t-form-item>
          <t-form-item label="密码"><t-input v-model="draft.password" type="password" /></t-form-item>
          <t-form-item label="数据库"><t-input v-model="draft.database" /></t-form-item>
          <t-button variant="outline" size="small" :loading="draftBusy" @click="testDraft">测试连接</t-button>
        </t-form>
      </t-dialog>
    </div>

    <div class="setting-row">
      <label>抽取模型</label>
      <t-select :value="modelValue.model_id" :disabled="disabled" placeholder="选择对话模型" style="max-width: 320px"
        @change="(v: string) => patch({ model_id: v })">
        <t-option v-for="m in models" :key="m.id" :value="m.id" :label="m.name" />
      </t-select>
    </div>

    <div class="setting-row">
      <label>实体类型</label>
      <t-textarea :value="typesText(modelValue.entity_types)" :disabled="disabled" :autosize="{ minRows: 1, maxRows: 3 }"
        placeholder="用顿号分隔，如：组织、人物、产品；留空则由模型决定"
        @change="(v: string) => patch({ entity_types: parseTypes(v) })" />
    </div>
    <div class="setting-row">
      <label>关系类型</label>
      <t-textarea :value="typesText(modelValue.relation_types)" :disabled="disabled" :autosize="{ minRows: 1, maxRows: 3 }"
        placeholder="用顿号分隔，如：任职、持股、供应；留空则由模型决定"
        @change="(v: string) => patch({ relation_types: parseTypes(v) })" />
    </div>
    <div class="setting-row">
      <label>补充说明</label>
      <t-textarea :value="modelValue.instructions" :disabled="disabled" :maxlength="4000" :autosize="{ minRows: 2, maxRows: 6 }"
        placeholder="对抽取的额外要求，例如只关注公司之间的股权关系"
        @change="(v: string) => patch({ instructions: v })" />
    </div>

    <div v-if="kbId" class="graph-status">
      <div class="graph-status__row">
        <span class="graph-status__title">构建状态</span>
        <span v-if="status?.ready">已就绪：{{ status.ready.entity_count }} 个实体 · {{ status.ready.relation_count }} 条关系
          <template v-if="status.ready.community_count"> · {{ status.ready.community_count }} 个社区</template></span>
        <span v-else class="muted">尚无可用图谱</span>
      </div>
      <div v-if="status?.latest" class="graph-status__row">
        <span class="graph-status__title">最近一次</span>
        <span :class="{ 'graph-status__fail': status.latest.state === 'failed' }">
          {{ stateText(status.latest) }}<template v-if="status.latest.error">：{{ status.latest.error }}</template>
        </span>
      </div>
      <div class="graph-status__actions">
        <t-button size="small" variant="outline" :loading="rebuilding" :disabled="disabled || building" @click="rebuild">重新构建</t-button>
        <t-button size="small" variant="outline" :disabled="!status?.ready" @click="showBrowser = true">查看图谱</t-button>
      </div>
    </div>
    <p v-else class="muted">保存知识库并上传文档后开始构建。</p>

    <KnowledgeGraphBrowser v-if="kbId" v-model:visible="showBrowser" :kb-id="kbId" />
  </div>
</template>

<style scoped>
.kb-graph-config { display: flex; flex-direction: column; gap: 16px; }
.setting-row { display: flex; flex-direction: column; gap: 6px; }
.setting-row > label { font-weight: 500; }
.mode-desc { margin-left: 8px; color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.muted { color: var(--td-text-color-secondary); }
.graph-status { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: var(--app-radius-md);
  background: var(--td-bg-color-secondarycontainer); }
.graph-status__row { display: flex; gap: 12px; }
.graph-status__title { min-width: 72px; color: var(--td-text-color-secondary); }
.graph-status__fail { color: var(--td-error-color); }
.graph-status__actions { display: flex; gap: 8px; }
</style>
