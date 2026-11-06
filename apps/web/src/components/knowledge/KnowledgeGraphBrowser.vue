<script setup lang="ts">
/**
 * Read-only browser of a knowledge base's visible graph (openspec 2026-11-06-knowledge-base K2.6).
 *
 * Lists the best-connected entities, or the entities named in the search box with their neighbours, and the
 * relations between the shown entities, plus community reports. A banner says when the server cut the result.
 */
import { computed, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { fetchGraphOverview, type GraphOverview } from '@/api/nexus-knowledge'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ visible: boolean, kbId: string }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

const auth = useAuthStore()
const query = ref('')
const loading = ref(false)
const data = ref<GraphOverview | null>(null)

const names = computed(() => new Map((data.value?.nodes || []).map(node => [node.id, node.name])))

async function load() {
  loading.value = true
  try {
    const wanted = query.value.split(/[,，、\s]+/).filter(Boolean)
    data.value = await fetchGraphOverview(auth.effectiveTenantId || '', props.kbId, wanted, 1)
  } catch (error) {
    MessagePlugin.error((error as Error)?.message || '加载图谱失败')
  } finally { loading.value = false }
}

watch(() => props.visible, visible => { if (visible) void load() })
</script>

<template>
  <t-drawer :visible="visible" size="640px" header="知识图谱" :footer="false" @update:visible="(v: boolean) => emit('update:visible', v)">
    <div class="graph-browser">
      <t-input v-model="query" clearable placeholder="输入实体名称（逗号分隔），留空显示关联最多的实体" @enter="load" />
      <t-loading v-if="loading" size="small" />
      <template v-else-if="data">
        <p v-if="data.truncated" class="graph-browser__note">结果因数量上限被截断；没有出现的关系不代表不存在。</p>
        <p v-if="!data.nodes.length" class="graph-browser__note">没有匹配的实体。</p>
        <section v-if="data.communities.length">
          <h4>社区报告</h4>
          <div v-for="item in data.communities" :key="item.id" class="graph-browser__card">
            <strong>{{ item.title }}</strong><span class="muted"> · {{ item.size }} 个实体</span>
            <p>{{ item.summary }}</p>
          </div>
        </section>
        <section v-if="data.nodes.length">
          <h4>实体（{{ data.nodes.length }}）</h4>
          <div v-for="node in data.nodes" :key="node.id" class="graph-browser__card">
            <strong>{{ node.name }}</strong><span class="muted"> · {{ node.type || '未分类' }} · 关联 {{ node.degree }}</span>
            <p>{{ node.description }}</p>
          </div>
        </section>
        <section v-if="data.edges.length">
          <h4>关系（{{ data.edges.length }}）</h4>
          <div v-for="edge in data.edges" :key="edge.id" class="graph-browser__card">
            <strong>{{ names.get(edge.source) || '?' }}</strong> — <strong>{{ names.get(edge.target) || '?' }}</strong>
            <p>{{ edge.description }}</p>
          </div>
        </section>
      </template>
    </div>
  </t-drawer>
</template>

<style scoped>
.graph-browser { display: flex; flex-direction: column; gap: 12px; }
.graph-browser__note { color: var(--td-warning-color); }
.graph-browser__card { padding: 8px 10px; margin-bottom: 6px; border: 1px solid var(--td-component-border);
  border-radius: var(--app-radius-md); }
.graph-browser__card p { margin: 4px 0 0; color: var(--td-text-color-secondary); }
.muted { color: var(--td-text-color-secondary); }
</style>
