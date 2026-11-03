<template>
  <div class="org-structure">
    <div class="org-intro">
      <p>{{ t('orgStructure.description') }}</p>
    </div>

    <t-alert v-if="loadError" theme="error" :message="loadError">
      <template #operation>
        <t-button size="small" @click="loadTree">{{ t('orgStructure.retry') }}</t-button>
      </template>
    </t-alert>

    <div v-else class="org-layout">
      <aside class="org-tree-pane">
        <div class="org-pane-head">
          <span class="org-pane-title">{{ t('orgStructure.treeTitle') }}</span>
          <t-button v-if="!rootExists && !loading" size="small" theme="primary" @click="openCreate(null)">
            {{ t('orgStructure.createRoot') }}
          </t-button>
        </div>
        <div v-if="loading" class="org-loading"><t-loading size="small" /></div>
        <div v-else-if="rows.length === 0" class="org-empty">{{ t('orgStructure.emptyTree') }}</div>
        <ul v-else class="org-tree">
          <li v-for="row in rows" :key="row.node.id"
            :class="['org-row', { 'is-selected': row.node.id === selectedId, 'is-disabled': row.node.status !== 'active' }]"
            :style="{ paddingLeft: `${12 + row.depth * 18}px` }" @click="selectUnit(row.node.id)">
            <span class="org-row-name">{{ row.node.name }}</span>
            <span class="org-row-count">{{ row.node.member_count }}</span>
          </li>
        </ul>
      </aside>

      <section v-if="selected" class="org-detail-pane">
        <header class="org-detail-head">
          <h3>{{ selected.name }}</h3>
          <t-tag size="small" :theme="selected.status === 'active' ? 'success' : 'default'" variant="light">
            {{ selected.status === 'active' ? t('orgStructure.statusActive') : t('orgStructure.statusDisabled') }}
          </t-tag>
        </header>
        <p class="org-meta">
          {{ t('orgStructure.parent') }}：{{ parentName }}
          <span class="org-meta-sep">·</span>
          {{ t('orgStructure.memberCount', { count: selected.member_count }) }}
        </p>
        <t-space size="small" class="org-actions">
          <t-button size="small" @click="openCreate(selected.id)">{{ t('orgStructure.addChild') }}</t-button>
          <t-button size="small" @click="openEdit">{{ t('orgStructure.editUnit') }}</t-button>
          <t-button size="small" @click="toggleStatus">
            {{ selected.status === 'active' ? t('orgStructure.disable') : t('orgStructure.enable') }}
          </t-button>
          <t-button size="small" theme="danger" variant="outline" @click="confirmDelete">
            {{ t('orgStructure.delete') }}
          </t-button>
        </t-space>

        <h4 class="org-section-title">{{ t('orgStructure.membersTitle') }}</h4>
        <t-space size="small" class="org-add-member">
          <t-select v-model="addUserId" :options="candidateOptions" filterable clearable
            :placeholder="t('orgStructure.pickMember')" style="min-width: 220px" />
          <t-checkbox v-model="addAsPrimary">{{ t('orgStructure.asPrimary') }}</t-checkbox>
          <t-button theme="primary" size="small" :disabled="!addUserId || busy" @click="addMember">
            {{ t('orgStructure.addMember') }}
          </t-button>
        </t-space>
        <t-table row-key="user_id" size="small" :data="unitMembers" :columns="memberColumns" :loading="membersLoading">
          <template #display_name="{ row }">{{ row.display_name || row.user_id }}</template>
          <template #is_primary="{ row }">
            <t-tag v-if="row.is_primary" size="small" theme="success" variant="light">
              {{ t('orgStructure.primary') }}
            </t-tag>
            <span v-else class="org-secondary">{{ t('orgStructure.secondary') }}</span>
          </template>
          <template #operation="{ row }">
            <t-button size="small" theme="danger" variant="text" @click="removeMember(row)">
              {{ t('orgStructure.removeMember') }}
            </t-button>
          </template>
        </t-table>
      </section>
    </div>

    <t-dialog v-model:visible="editVisible" :header="editTitle" width="460px" :confirm-btn="{ content: t('common.save'), loading: busy }"
      :cancel-btn="t('common.cancel')" @confirm="submitEdit">
      <t-form label-align="top">
        <t-form-item :label="t('orgStructure.nameLabel')">
          <t-input v-model="editName" maxlength="160" :placeholder="t('orgStructure.namePlaceholder')" />
        </t-form-item>
        <t-form-item v-if="editMode !== 'create-root'" :label="t('orgStructure.parentLabel')">
          <t-select v-model="editParentId" :options="parentOptions" clearable
            :placeholder="t('orgStructure.parentPlaceholder')" />
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
// 企业设置 → 部门架构：左侧为部门树，右侧为所选部门的信息、成员与操作。
// 权限与规则由后端判定（org:manage；每个企业一个根部门；仍有子部门或成员时不能删除）。
// 个人空间没有部门架构，页面只在企业空间中出现。
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import { listMembers, type TenantMember } from '@/api/tenant/members'
import {
  assignOrgUnitMember,
  createOrgUnit,
  deleteOrgUnit,
  getOrgUnitTree,
  listOrgUnitMembers,
  unassignOrgUnitMember,
  updateOrgUnit,
  type OrgUnitMember,
  type OrgUnitNode,
} from '@/api/tenant/org-units'

const { t } = useI18n()
const authStore = useAuthStore()

const tenantId = computed(() => String(authStore.currentTenantId ?? ''))
const units = ref<OrgUnitNode[]>([])
const loading = ref(false)
const loadError = ref('')
const selectedId = ref<string | null>(null)
const unitMembers = ref<OrgUnitMember[]>([])
const membersLoading = ref(false)
const candidates = ref<TenantMember[]>([])
const addUserId = ref<string | undefined>(undefined)
const addAsPrimary = ref(false)
const busy = ref(false)

const editVisible = ref(false)
const editMode = ref<'create' | 'create-root' | 'edit'>('create')
const editUnitId = ref<string | null>(null)
const editName = ref('')
const editParentId = ref<string | undefined>(undefined)

const memberColumns = computed(() => [
  { colKey: 'display_name', title: t('orgStructure.columns.name'), ellipsis: true },
  { colKey: 'is_primary', title: t('orgStructure.columns.primary'), width: 110 },
  { colKey: 'operation', title: t('orgStructure.columns.operation'), width: 90 },
])

const rootExists = computed(() => units.value.some((u) => u.parent_id === null))
const unitById = computed(() => new Map(units.value.map((u) => [u.id, u])))
const selected = computed(() => (selectedId.value ? unitById.value.get(selectedId.value) ?? null : null))
const parentName = computed(() => {
  const parent = selected.value?.parent_id ? unitById.value.get(selected.value.parent_id) : undefined
  return parent ? parent.name : t('orgStructure.noParent')
})

/** 深度优先展开成行，子部门紧跟父部门并按深度缩进。 */
const rows = computed(() => {
  const children = new Map<string | null, OrgUnitNode[]>()
  for (const unit of units.value) {
    const key = unit.parent_id ?? null
    children.set(key, [...(children.get(key) ?? []), unit])
  }
  const out: Array<{ node: OrgUnitNode; depth: number }> = []
  const walk = (parent: string | null, depth: number) => {
    for (const node of children.get(parent) ?? []) {
      out.push({ node, depth })
      walk(node.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

const candidateOptions = computed(() => {
  const inUnit = new Set(unitMembers.value.map((m) => m.user_id))
  return candidates.value
    .filter((m) => !inUnit.has(m.user_id))
    .map((m) => ({ label: m.display_name || m.username || m.email, value: m.user_id }))
})

const parentOptions = computed(() =>
  units.value
    .filter((u) => u.id !== editUnitId.value)
    .map((u) => ({ label: u.name, value: u.id })),
)

const editTitle = computed(() => {
  if (editMode.value === 'edit') return t('orgStructure.editTitle')
  if (editMode.value === 'create-root') return t('orgStructure.createRootTitle')
  return t('orgStructure.addChildTitle')
})

function errorText(error: unknown): string {
  return (error as { message?: string })?.message || t('orgStructure.failed')
}

async function loadTree() {
  loading.value = true
  loadError.value = ''
  try {
    units.value = await getOrgUnitTree(tenantId.value)
    if (selectedId.value && !unitById.value.has(selectedId.value)) selectedId.value = null
    if (!selectedId.value && units.value.length > 0) selectedId.value = units.value[0].id
  } catch (error) {
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function loadUnitMembers() {
  if (!selectedId.value) {
    unitMembers.value = []
    return
  }
  membersLoading.value = true
  try {
    unitMembers.value = await listOrgUnitMembers(tenantId.value, selectedId.value)
  } catch (error) {
    unitMembers.value = []
    MessagePlugin.error(errorText(error))
  } finally {
    membersLoading.value = false
  }
}

async function loadCandidates() {
  try {
    const resp = await listMembers(tenantId.value)
    candidates.value = resp.data?.members ?? []
  } catch {
    candidates.value = []
  }
}

function selectUnit(id: string) {
  selectedId.value = id
  addUserId.value = undefined
}

function openCreate(parentId: string | null) {
  editMode.value = parentId === null ? 'create-root' : 'create'
  editUnitId.value = null
  editName.value = ''
  editParentId.value = parentId ?? undefined
  editVisible.value = true
}

function openEdit() {
  if (!selected.value) return
  editMode.value = 'edit'
  editUnitId.value = selected.value.id
  editName.value = selected.value.name
  editParentId.value = selected.value.parent_id ?? undefined
  editVisible.value = true
}

async function submitEdit() {
  const name = editName.value.trim()
  if (!name) {
    MessagePlugin.warning(t('orgStructure.nameRequired'))
    return
  }
  busy.value = true
  try {
    if (editMode.value === 'edit' && editUnitId.value) {
      await updateOrgUnit(tenantId.value, editUnitId.value, {
        name,
        parent_id: editParentId.value ?? null,
      })
    } else {
      const created = await createOrgUnit(tenantId.value, {
        name,
        ...(editMode.value === 'create-root' ? {} : { parent_id: editParentId.value ?? null }),
      })
      selectedId.value = created.id
    }
    editVisible.value = false
    MessagePlugin.success(t('orgStructure.saved'))
    await loadTree()
    await loadUnitMembers()
  } catch (error) {
    MessagePlugin.error(errorText(error))
  } finally {
    busy.value = false
  }
}

async function toggleStatus() {
  if (!selected.value) return
  const next = selected.value.status === 'active' ? 'disabled' : 'active'
  busy.value = true
  try {
    await updateOrgUnit(tenantId.value, selected.value.id, { status: next })
    MessagePlugin.success(t('orgStructure.saved'))
    await loadTree()
  } catch (error) {
    MessagePlugin.error(errorText(error))
  } finally {
    busy.value = false
  }
}

function confirmDelete() {
  if (!selected.value) return
  const unit = selected.value
  DialogPlugin.confirm({
    header: t('orgStructure.deleteTitle'),
    body: t('orgStructure.deleteBody', { name: unit.name }),
    theme: 'danger',
    confirmBtn: { content: t('orgStructure.delete'), theme: 'danger' },
    cancelBtn: t('common.cancel'),
    onConfirm: async () => {
      try {
        await deleteOrgUnit(tenantId.value, unit.id)
        MessagePlugin.success(t('orgStructure.deleted'))
        selectedId.value = null
        await loadTree()
      } catch (error) {
        MessagePlugin.error(errorText(error))
      }
    },
  })
}

async function addMember() {
  if (!selected.value || !addUserId.value) return
  busy.value = true
  try {
    await assignOrgUnitMember(tenantId.value, selected.value.id, addUserId.value, addAsPrimary.value)
    addUserId.value = undefined
    addAsPrimary.value = false
    await loadUnitMembers()
    await loadTree()
  } catch (error) {
    MessagePlugin.error(errorText(error))
  } finally {
    busy.value = false
  }
}

async function removeMember(row: OrgUnitMember) {
  if (!selected.value) return
  try {
    await unassignOrgUnitMember(tenantId.value, selected.value.id, row.user_id)
    await loadUnitMembers()
    await loadTree()
  } catch (error) {
    MessagePlugin.error(errorText(error))
  }
}

onMounted(async () => {
  await Promise.all([loadTree(), loadCandidates()])
  await loadUnitMembers()
})

watch(selectedId, () => {
  void loadUnitMembers()
})
</script>

<style scoped lang="less">
.org-intro p {
  margin: 0 0 16px;
  color: var(--td-text-color-secondary);
  line-height: 1.6;
}

.org-layout {
  display: grid;
  grid-template-columns: minmax(220px, 280px) 1fr;
  gap: 16px;
  align-items: start;
}

.org-tree-pane,
.org-detail-pane {
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-lg);
  background: var(--td-bg-color-container);
  padding: 12px;
  min-height: 320px;
}

.org-pane-head,
.org-detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.org-pane-title {
  font-weight: 600;
}

.org-tree {
  list-style: none;
  margin: 0;
  padding: 0;
}

.org-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  color: var(--td-text-color-primary);
}

.org-row:hover {
  background: var(--td-bg-color-container-hover);
}

.org-row.is-selected {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
}

.org-row.is-disabled .org-row-name {
  color: var(--td-text-color-disabled);
  text-decoration: line-through;
}

.org-row-count,
.org-meta,
.org-secondary,
.org-empty {
  color: var(--td-text-color-secondary);
  font-size: 12px;
}

.org-meta {
  margin: 0 0 12px;
}

.org-meta-sep {
  margin: 0 6px;
}

.org-actions {
  margin-bottom: 16px;
}

.org-section-title {
  margin: 16px 0 8px;
}

.org-add-member {
  margin-bottom: 12px;
}

.org-loading,
.org-empty {
  padding: 16px 0;
  text-align: center;
}

@media (max-width: 800px) {
  .org-layout {
    grid-template-columns: 1fr;
  }
}
</style>
