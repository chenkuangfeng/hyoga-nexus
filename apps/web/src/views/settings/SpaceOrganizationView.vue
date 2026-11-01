<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../api/chat'
import { orgApi } from '../../api/orgs'
import { roleApi } from '../../api/roles'
import type { Tenant } from '../../types/chat'
import type { SpaceBinding, SpaceBindingNode, SpaceOrganization } from '../../types/orgs'

/** Space page: the organizations bound to this space, their subtrees, and the people in them.
 * Seeing a person does not make them a member; joining is an explicit action that needs members:manage.
 */
const tenants = ref<Tenant[]>([]), tenant = ref('')
const data = ref<SpaceOrganization>({ bindings: [], people: [] })
const canJoin = ref(false), role = ref<'admin' | 'member'>('member'), picked = ref<string[]>([])
const loading = ref(false), busy = ref(false), error = ref(''), feedback = ref('')

const message = (err: unknown) => (err instanceof Error ? err.message : '请求未完成')

/** Indentation for a binding's subtree: depth is the number of ancestors inside the same subtree. */
function flatNodes(binding: SpaceBinding): { node: SpaceBindingNode; depth: number }[] {
  const byId = new Map(binding.nodes.map(node => [node.id, node]))
  const depthOf = (node: SpaceBindingNode): number => {
    let depth = 0, parent = node.parent_id
    while (parent && byId.has(parent)) { depth += 1; parent = byId.get(parent)!.parent_id }
    return depth
  }
  return binding.nodes.map(node => ({ node, depth: depthOf(node) })).sort((a, b) => a.depth - b.depth)
}
const joinable = computed(() => canJoin.value && data.value.people.length > 0)

async function load() {
  if (!tenant.value) { data.value = { bindings: [], people: [] }; canJoin.value = false; return }
  loading.value = true; error.value = ''; feedback.value = ''
  try {
    const [organization, perms] = await Promise.all([orgApi.spaceOrganization(tenant.value), roleApi.myPermissions(tenant.value)])
    data.value = organization
    canJoin.value = perms.apis.includes('members:manage')
    picked.value = []
  } catch (err) { error.value = message(err); data.value = { bindings: [], people: [] } }
  finally { loading.value = false }
}
async function join() {
  if (!picked.value.length || !tenant.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try {
    const result = await orgApi.joinFromOrganization(tenant.value, picked.value, role.value)
    picked.value = []
    await load()
    // load() clears the feedback line, so the result message is set after the reload.
    feedback.value = `已加入 ${result.added.length} 人${result.skipped.length ? `，${result.skipped.length} 人已是成员` : ''}`
  } catch (err) { error.value = message(err) }
  finally { busy.value = false }
}
watch(tenant, () => void load())
onMounted(async () => {
  try {
    tenants.value = await api.tenants()
    tenant.value = tenants.value[0]?.id || ''
  } catch (err) { error.value = message(err) }
})
</script>

<template>
  <main class="space-org" v-loading="loading" :aria-busy="loading || busy">
    <header>
      <div><p class="eyebrow">HYOGA NEXUS / 空间管理</p><h1>空间组织</h1></div>
    </header>
    <p class="intro">这里显示绑定到当前空间的组织节点、子树结构和其中的人员。人员只能看到、不会自动成为成员；需要加入时，请在下方勾选并选择角色。</p>
    <label for="org-tenant">空间</label>
    <el-select id="org-tenant" v-model="tenant" :disabled="loading || busy" placeholder="选择空间">
      <el-option v-for="item in tenants" :key="item.id" :label="item.name" :value="item.id" />
    </el-select>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notice" role="alert" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>

    <el-empty v-if="tenant && !loading && !data.bindings.length" description="该空间尚未绑定任何组织" />

    <section v-for="binding in data.bindings" :key="binding.unit_id" class="panel" :aria-labelledby="`bind-${binding.unit_id}`">
      <h2 :id="`bind-${binding.unit_id}`">{{ binding.organization_name }} › {{ binding.unit_name }}</h2>
      <p v-if="binding.status === 'disabled'" class="muted">该节点已停用，子树仅供查看。</p>
      <ul class="tree" :aria-label="`${binding.unit_name} 的子树`">
        <li v-for="item in flatNodes(binding)" :key="item.node.id" :style="{ paddingLeft: `${item.depth * 20 + 8}px` }">
          {{ item.node.name }}
          <span v-if="item.node.status === 'disabled'" class="tag disabled">已停用</span>
        </li>
      </ul>
    </section>

    <section v-if="data.people.length" class="panel" aria-labelledby="people-title">
      <h2 id="people-title">组织人员（{{ data.people.length }}）</h2>
      <p v-if="!canJoin" class="muted">你没有成员管理权限，只能查看。</p>
      <el-checkbox-group v-model="picked" :disabled="!canJoin || busy" aria-label="选择要加入空间的人员" class="people">
        <el-checkbox v-for="person in data.people" :key="person.user_id" :value="person.user_id" class="person">
          <span class="person-name">{{ person.display_name || '未命名用户' }}</span>
          <span class="person-units">{{ person.units.map(u => u.unit_name + (u.is_primary ? '（主）' : '')).join('、') }}</span>
        </el-checkbox>
      </el-checkbox-group>
      <form v-if="canJoin" class="join-form" @submit.prevent="join">
        <label for="join-role">加入后的角色</label>
        <el-select id="join-role" v-model="role" :disabled="busy" class="role-select">
          <el-option label="普通成员" value="member" />
          <el-option label="管理员" value="admin" />
        </el-select>
        <el-button type="primary" native-type="submit" :disabled="busy || !picked.length || !joinable">加入空间（{{ picked.length }}）</el-button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.space-org { max-width: 960px; margin: 0 auto; padding: 24px; }
header h1 { margin: 0; }
.intro, .muted { color: var(--muted-text); line-height: 1.6; font-size: 14px; }
.notice { margin-top: 12px; }
.feedback { min-height: 22px; color: var(--muted-text); font-size: 14px; }
label { display: block; margin-top: 12px; font-size: 14px; font-weight: 600; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-top: 16px; }
.tree { list-style: none; padding: 0; margin: 0; }
.tree li { padding: 6px 0; border-bottom: 1px solid var(--el-border-color-lighter); overflow-wrap: anywhere; }
.tag { display: inline-block; margin-left: 6px; padding: 2px 8px; border-radius: 999px; font-size: 12px; background: var(--el-fill-color); color: var(--muted-text); }
.people { display: grid; gap: 8px; margin-top: 8px; }
.person { height: auto; min-height: 44px; align-items: center; }
.person-name { font-weight: 600; margin-right: 8px; }
.person-units { color: var(--muted-text); font-size: 13px; }
.join-form { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-top: 16px; }
.join-form label { margin: 0; }
.role-select { width: 160px; }
</style>
