<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../../api/chat'
import { orgApi } from '../../api/orgs'
import type { Tenant } from '../../types/chat'
import type { BoundSpace, Org, OrgNode, OrgPerson, UserOption } from '../../types/orgs'

/** Platform-admin page: organization trees (group > subsidiary > department), people in nodes, space bindings. */
const orgs = ref<Org[]>([]), rootId = ref(''), nodes = ref<OrgNode[]>([])
const selectedId = ref(''), people = ref<OrgPerson[]>([]), bindings = ref<BoundSpace[]>([])
const tenants = ref<Tenant[]>([]), bindTenant = ref('')
const users = ref<UserOption[]>([]), usersLoading = ref(false), pickedUser = ref(''), pickPrimary = ref(false)
const loading = ref(false), busy = ref(false), error = ref(''), feedback = ref('')
const newOrgName = ref('')
const moveDialog = reactive({ open: false, unitId: '', target: '' })

const selected = computed(() => nodes.value.find(node => node.id === selectedId.value) || null)
const childrenOf = computed(() => {
  const map = new Map<string, OrgNode[]>()
  for (const node of nodes.value) if (node.parent_id) map.set(node.parent_id, [...(map.get(node.parent_id) || []), node])
  return map
})
/** Depth-first order with indentation; the tree is unlimited in depth. */
const flat = computed(() => {
  const out: { node: OrgNode; depth: number }[] = []
  const walk = (id: string, depth: number) => {
    for (const child of childrenOf.value.get(id) || []) { out.push({ node: child, depth }); walk(child.id, depth + 1) }
  }
  if (rootId.value) walk(rootId.value, 0)
  return out
})
function subtreeOf(id: string): Set<string> {
  const ids = new Set<string>([id])
  const walk = (current: string) => { for (const child of childrenOf.value.get(current) || []) { ids.add(child.id); walk(child.id) } }
  walk(id)
  return ids
}
const moveTargets = computed(() => {
  if (!moveDialog.unitId) return []
  const banned = subtreeOf(moveDialog.unitId)
  return nodes.value.filter(node => !banned.has(node.id) && node.status === 'active')
})
const userLabel = (user: UserOption) => `${user.display_name || '未命名'}${user.username ? `（${user.username}）` : ''}`
const message = (err: unknown) => (err instanceof Error ? err.message : '请求未完成')

async function loadOrgs() {
  orgs.value = await orgApi.orgs()
  if (!orgs.value.some(org => org.id === rootId.value)) rootId.value = orgs.value[0]?.id || ''
}
async function loadTree() {
  nodes.value = rootId.value ? await orgApi.tree(rootId.value) : []
  if (!nodes.value.some(node => node.id === selectedId.value)) selectedId.value = nodes.value[0]?.id || ''
}
async function loadDetail() {
  if (!selectedId.value) { people.value = []; bindings.value = []; return }
  const [peopleRows, bindRows] = await Promise.all([orgApi.people(selectedId.value), orgApi.bindings(selectedId.value)])
  people.value = peopleRows
  bindings.value = bindRows
}
/** Shared action wrapper: one busy flag, one error channel, reload after every write. */
async function run(action: () => Promise<unknown>, success: string) {
  busy.value = true; error.value = ''; feedback.value = ''
  try { await action(); feedback.value = success; await loadTree(); await loadDetail() }
  catch (err) { error.value = message(err) }
  finally { busy.value = false }
}
async function initialize() {
  loading.value = true; error.value = ''
  try {
    await loadOrgs()
    tenants.value = await api.tenants()
    await loadTree()
    await loadDetail()
    await searchUsers('')
  } catch (err) { error.value = message(err) }
  finally { loading.value = false }
}
async function searchUsers(query: string) {
  usersLoading.value = true
  try { users.value = await orgApi.users(query) } catch (err) { error.value = message(err) } finally { usersLoading.value = false }
}
async function selectOrg(id: string) { rootId.value = id; selectedId.value = ''; await loadTree(); await loadDetail() }
async function createOrg() {
  const name = newOrgName.value.trim()
  if (!name) return
  await run(() => orgApi.createOrg(name), '组织已创建')
  newOrgName.value = ''
  await loadOrgs()
}
async function addChild(node: OrgNode) {
  try {
    const { value } = await ElMessageBox.prompt(`在“${node.name}”下新增子节点（子公司或部门）`, '新增子节点', {
      confirmButtonText: '新增', cancelButtonText: '取消', inputPattern: /\S/, inputErrorMessage: '名称不能为空' })
    await run(() => orgApi.createUnit(node.id, value.trim()), '子节点已新增')
  } catch { /* cancelled */ }
}
async function rename(node: OrgNode) {
  try {
    const { value } = await ElMessageBox.prompt('输入新的名称', '重命名', {
      confirmButtonText: '保存', cancelButtonText: '取消', inputValue: node.name, inputPattern: /\S/, inputErrorMessage: '名称不能为空' })
    await run(() => orgApi.updateUnit(node.id, { name: value.trim() }), '名称已更新')
  } catch { /* cancelled */ }
}
function openMove(node: OrgNode) {
  moveDialog.unitId = node.id
  moveDialog.target = node.parent_id || ''
  moveDialog.open = true
}
async function confirmMove() {
  const id = moveDialog.unitId, target = moveDialog.target
  moveDialog.open = false
  if (!id || !target) return
  await run(() => orgApi.updateUnit(id, { parent_id: target }), '节点已移动')
}
async function toggleStatus(node: OrgNode) {
  const next = node.status === 'active' ? 'disabled' : 'active'
  await run(() => orgApi.updateUnit(node.id, { status: next }), next === 'active' ? '节点已启用' : '节点已停用')
}
async function removeNode(node: OrgNode) {
  try {
    await ElMessageBox.confirm(`删除“${node.name}”。只能删除没有子节点、人员和空间绑定的节点。`, '确认删除', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
  } catch { return }
  await run(() => orgApi.deleteUnit(node.id), '节点已删除')
  if (selectedId.value === node.id) selectedId.value = ''
}
async function addPerson() {
  if (!selectedId.value || !pickedUser.value) return
  await run(() => orgApi.assign(selectedId.value, pickedUser.value, pickPrimary.value), '人员已加入节点')
  pickedUser.value = ''; pickPrimary.value = false
}
const setPrimary = (userId: string) => run(() => orgApi.assign(selectedId.value, userId, true), '已设为主节点')
const removePerson = (userId: string) => run(() => orgApi.unassign(selectedId.value, userId), '人员已移出节点')
async function bindSpace() {
  if (!selectedId.value || !bindTenant.value) return
  await run(() => orgApi.bind(bindTenant.value, selectedId.value), '空间已绑定')
  bindTenant.value = ''
}
async function unbindSpace(tenantId: string) {
  await run(() => orgApi.unbind(tenantId, selectedId.value), '绑定已解除')
}

watch(selectedId, () => { void loadDetail().catch(err => { error.value = message(err) }) })
onMounted(initialize)
</script>

<template>
  <main class="org-page" v-loading="loading" :aria-busy="loading || busy">
    <header>
      <div><p class="eyebrow">HYOGA NEXUS / 平台管理</p><h1>组织与人员</h1></div>
    </header>
    <p class="intro">组织是一棵树：集团为根，下面可以挂子公司和部门，层级不限。人员来自用户列表，可以属于多个节点，其中只有一个主节点。空间绑定节点后，空间成员可以看到该节点的整棵子树。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notice" role="alert" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>

    <section class="panel" aria-labelledby="org-list-title">
      <h2 id="org-list-title">组织</h2>
      <div class="org-picker" role="group" aria-label="选择组织">
        <button v-for="org in orgs" :key="org.id" type="button" class="org-chip"
          :aria-pressed="org.id === rootId" :disabled="busy" @click="selectOrg(org.id)">{{ org.name }}</button>
        <p v-if="!orgs.length && !loading" class="muted">尚未创建组织</p>
      </div>
      <form class="inline-form" @submit.prevent="createOrg">
        <label for="new-org-name">新组织名称</label>
        <el-input id="new-org-name" v-model="newOrgName" maxlength="160" :disabled="busy" />
        <el-button type="primary" native-type="submit" :disabled="busy || !newOrgName.trim()">新建组织</el-button>
      </form>
    </section>

    <div class="layout" v-if="rootId">
      <section class="panel tree-panel" aria-labelledby="tree-title">
        <h2 id="tree-title">组织树</h2>
        <ul class="tree" aria-label="组织节点">
          <li v-for="item in flat" :key="item.node.id" :style="{ paddingLeft: `${item.depth * 20}px` }"
            :class="{ selected: item.node.id === selectedId }">
            <button type="button" class="node-button" :aria-pressed="item.node.id === selectedId" :disabled="busy"
              @click="selectedId = item.node.id">
              <span class="node-name">{{ item.node.name }}</span>
              <span class="node-meta">{{ item.node.member_count }} 人</span>
              <span v-if="item.node.status === 'disabled'" class="tag disabled">已停用</span>
            </button>
            <div class="node-actions" role="group" :aria-label="`${item.node.name} 的操作`">
              <el-button size="small" :disabled="busy || item.node.status !== 'active'" @click="addChild(item.node)">添加下级</el-button>
              <el-button size="small" :disabled="busy" @click="rename(item.node)">重命名</el-button>
              <el-button v-if="item.node.parent_id" size="small" :disabled="busy" @click="openMove(item.node)">移动</el-button>
              <el-button size="small" :disabled="busy" @click="toggleStatus(item.node)">{{ item.node.status === 'active' ? '停用' : '启用' }}</el-button>
              <el-button size="small" type="danger" plain :disabled="busy" @click="removeNode(item.node)">删除</el-button>
            </div>
          </li>
        </ul>
      </section>

      <section class="panel detail-panel" aria-labelledby="detail-title">
        <template v-if="selected">
          <h2 id="detail-title">{{ selected.name }}</h2>
          <p class="muted">{{ selected.status === 'active' ? '节点有效' : '节点已停用，不能加入新人员或绑定空间' }}</p>

          <h3>人员</h3>
          <el-empty v-if="!people.length" description="此节点下尚无人员" :image-size="60" />
          <ul class="people" v-else>
            <li v-for="item in people" :key="item.user_id">
              <div>
                <strong>{{ item.display_name || '未命名用户' }}</strong>
                <span v-for="unit in item.units" :key="unit.unit_id" class="tag" :class="{ primary: unit.is_primary }">
                  {{ unit.unit_name }}<template v-if="unit.is_primary">（主节点）</template>
                </span>
              </div>
              <div class="person-actions">
                <el-button size="small" :disabled="busy" @click="setPrimary(item.user_id)">设为主节点</el-button>
                <el-button size="small" type="danger" plain :disabled="busy" @click="removePerson(item.user_id)">移出节点</el-button>
              </div>
            </li>
          </ul>

          <form class="inline-form" @submit.prevent="addPerson">
            <label for="pick-user">选择人员</label>
            <el-select id="pick-user" v-model="pickedUser" filterable remote reserve-keyword clearable
              :remote-method="searchUsers" :loading="usersLoading" :disabled="busy || selected.status !== 'active'"
              placeholder="输入姓名或账号搜索" class="picker">
              <el-option v-for="user in users" :key="user.user_id" :label="userLabel(user)" :value="user.user_id" />
            </el-select>
            <el-checkbox v-model="pickPrimary" :disabled="busy">设为主节点</el-checkbox>
            <el-button type="primary" native-type="submit" :disabled="busy || !pickedUser || selected.status !== 'active'">加入节点</el-button>
          </form>

          <h3>绑定的空间</h3>
          <p class="muted">绑定后，该空间的成员可以看到本节点及其子树。</p>
          <el-empty v-if="!bindings.length" description="尚未绑定空间" :image-size="60" />
          <ul class="bindings" v-else>
            <li v-for="space in bindings" :key="space.tenant_id">
              <span>{{ space.tenant_name }}</span>
              <el-button size="small" :disabled="busy" @click="unbindSpace(space.tenant_id)">解除绑定</el-button>
            </li>
          </ul>
          <form class="inline-form" @submit.prevent="bindSpace">
            <label for="bind-space">绑定到空间</label>
            <el-select id="bind-space" v-model="bindTenant" :disabled="busy" placeholder="选择空间" class="picker">
              <el-option v-for="item in tenants" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
            <el-button type="primary" native-type="submit" :disabled="busy || !bindTenant">绑定</el-button>
          </form>
        </template>
        <el-empty v-else description="选择左侧的一个节点" />
      </section>
    </div>

    <el-dialog v-model="moveDialog.open" title="移动节点" width="480px">
      <label for="move-target">移动到</label>
      <el-select id="move-target" v-model="moveDialog.target" class="picker" :disabled="busy">
        <el-option v-for="node in moveTargets" :key="node.id" :label="node.name" :value="node.id" />
      </el-select>
      <template #footer>
        <el-button @click="moveDialog.open = false">取消</el-button>
        <el-button type="primary" :disabled="!moveDialog.target" @click="confirmMove">移动</el-button>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped>
.org-page { max-width: 1200px; margin: 0 auto; padding: 24px; }
header h1 { margin: 0; }
.intro, .muted { color: var(--muted-text); line-height: 1.6; font-size: 14px; }
.notice { margin-top: 12px; }
.feedback { min-height: 22px; color: var(--muted-text); font-size: 14px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-top: 16px; min-width: 0; }
.org-picker { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.org-chip { min-height: 44px; padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); font: inherit; cursor: pointer; }
.org-chip[aria-pressed='true'] { background: var(--selected); border-color: var(--el-color-primary); }
.org-chip:focus-visible, .node-button:focus-visible { outline: 3px solid var(--el-color-primary); outline-offset: 2px; }
.inline-form { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-top: 12px; }
.inline-form label { font-size: 14px; font-weight: 600; }
.layout { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 16px; align-items: start; }
.tree { list-style: none; padding: 0; margin: 0; }
.tree li { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 6px 8px; border-bottom: 1px solid var(--el-border-color-lighter); }
.tree li.selected { background: var(--selected); }
.node-button { display: flex; gap: 8px; align-items: center; min-height: 44px; min-width: 160px; flex: 1 1 160px; padding: 6px 10px; border: 0; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.node-button[aria-pressed='true'] .node-name { font-weight: 700; }
.node-name { overflow-wrap: anywhere; }
.node-meta { color: var(--muted-text); font-size: 13px; }
.node-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { display: inline-block; margin: 2px 6px 2px 0; padding: 2px 8px; border-radius: 999px; background: var(--selected); font-size: 12px; }
.tag.primary { background: var(--el-color-primary); color: #fff; }
.tag.disabled { background: var(--el-fill-color); color: var(--muted-text); }
.people, .bindings { list-style: none; padding: 0; margin: 0; }
.people li, .bindings li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.person-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.picker { min-width: 240px; flex: 1 1 240px; }
h3 { margin-top: 20px; font-size: 16px; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } .picker { min-width: 0; } }
</style>
