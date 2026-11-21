<script setup lang="ts">
/** 既有解析配置的企业治理：全量替换保留快照，密钥只写，异步结果绑定当前身份。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useEnterpriseContext } from '../../stores/context'
import { getEnterpriseParserConfig, listEnterpriseParserEngines, saveEnterpriseParserConfig, parserConfigPayload, PARSER_GROUPS, PARSER_SECRET_KEYS, PARSER_SECRET_MASK, type ParserConfig, type ParserEngine } from '@nexus-web/core/api/enterprise-parsers'
const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const allowed = computed(() => context.ready && ['owner', 'admin'].includes(auth.currentTenantRole || ''))
const snapshot = ref<ParserConfig | null>(null), draft = ref<ParserConfig>({}), cleared = ref<string[]>([]), engines = ref<ParserEngine[]>([])
const loading = ref(false), busy = ref(false), error = ref(''), success = ref('')
const drawerVisible = ref(false), activeEngine = ref('')
const groupIds = ['mineru', 'mineru_cloud', 'paddleocr_vl', 'paddleocr_vl_cloud']
const activeGroup = computed(() => PARSER_GROUPS[groupIds.indexOf(activeEngine.value)])
/** 原版按解析器显示一张配置卡；没有额外配置的内置引擎只读展示。 */
const cards = computed(() => [
  ...PARSER_GROUPS.map((group, index) => ({ name: groupIds[index]!, title: group.name, engine: engines.value.find(engine => engine.name === groupIds[index]) })),
  ...engines.value.filter(engine => !groupIds.includes(engine.name)).map(engine => ({ name: engine.name, title: engine.description || engine.name, engine })),
])
function openEngine(name: string) { if (!busy.value && snapshot.value) { activeEngine.value = name; drawerVisible.value = true } }
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const payload = computed(() => snapshot.value ? parserConfigPayload(snapshot.value, draft.value, cleared.value) : {})
const dirty = computed(() => !!snapshot.value && JSON.stringify(payload.value) !== JSON.stringify(snapshot.value))
function accept(config: ParserConfig) {
  snapshot.value = config; draft.value = { ...config }; cleared.value = []
  for (const key of PARSER_SECRET_KEYS) draft.value[key] = ''
}
function invalidate() { drawerVisible.value = false; activeEngine.value = ''; epoch++; confirmation?.hide(); confirmation = undefined; snapshot.value = null; draft.value = {}; cleared.value = []; engines.value = []; loading.value = false; busy.value = false; error.value = ''; success.value = '' }
async function load() {
  invalidate()
  if (!allowed.value || !auth.effectiveTenantId) return
  const current = epoch, tenant = String(auth.effectiveTenantId); loading.value = true
  try {
    const [config, catalog] = await Promise.all([getEnterpriseParserConfig(tenant), listEnterpriseParserEngines(tenant)])
    if (current === epoch) { accept(config); engines.value = catalog }
  } catch { if (current === epoch) error.value = t('adminParsers.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
function reset() { if (!busy.value && snapshot.value) { accept(snapshot.value); error.value = ''; success.value = '' } }
function flag(key: string, value: unknown) { if (!busy.value) draft.value[key] = value === 'true' ? true : value === 'false' ? false : undefined }
function secret(key: string, value: unknown) { if (!busy.value && typeof value === 'string') { draft.value[key] = value; if (value) cleared.value = cleared.value.filter(k => k !== key) } }
function clearSecret(key: string, value: unknown) { if (!busy.value) { cleared.value = cleared.value.filter(k => k !== key); if (value === true) { cleared.value.push(key); draft.value[key] = '' } } }
function save() {
  if (!allowed.value || !snapshot.value || busy.value || loading.value || !dirty.value || confirmation) return
  const current = epoch, tenant = String(auth.effectiveTenantId)
  const dialog = DialogPlugin.confirm({ header: t('common.confirm'), body: t('adminParsers.confirm'),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      confirmation = undefined; dialog.hide()
      if (current !== epoch || !allowed.value || busy.value) return
      const body = parserConfigPayload(snapshot.value!, draft.value, cleared.value)
      for (const key of PARSER_SECRET_KEYS) draft.value[key] = ''
      busy.value = true; error.value = ''; success.value = ''
      try {
        const result = await saveEnterpriseParserConfig(tenant, body)
        if (current !== epoch) return
        accept(result); success.value = t('adminParsers.saved')
        try { const catalog = await listEnterpriseParserEngines(tenant); if (current === epoch) engines.value = catalog }
        catch { if (current === epoch) error.value = t('adminParsers.refreshFailed') }
      } catch { if (current === epoch) error.value = t('adminParsers.saveFailed') }
      finally { for (const key of PARSER_SECRET_KEYS) delete body[key]; if (current === epoch) busy.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  }); confirmation = dialog
}
watch(() => JSON.stringify([auth.effectiveTenantId, auth.user?.id, auth.currentTenantRole, context.revision, allowed.value]), () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(invalidate)
</script>
<template>
  <section class="parser-engine-settings">
    <header class="section-header"><div><h2>{{ t('settings.parser.title') }}</h2><p>{{ t('adminParsers.description') }}</p></div><t-button variant="outline" :disabled="busy" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!allowed" theme="warning" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" /><t-alert v-if="success" theme="success" :message="success" />
      <t-loading :loading="loading">
        <div v-if="snapshot" class="engine-cards">
          <button v-for="card in cards" :key="card.name" type="button" class="engine-card"
            :class="[`engine-card--${card.name}`, { 'engine-card--active': drawerVisible && activeEngine === card.name }]" :disabled="busy" @click="openEngine(card.name)">
            <span class="engine-card__badge">{{ card.title.charAt(0).toUpperCase() }}</span>
            <span class="engine-card__body"><span class="engine-card__header"><span class="engine-card__title">{{ card.title }}</span>
              <span class="engine-card__status" :class="card.engine?.configured ? 'engine-card__status--on' : 'engine-card__status--err'"><span class="engine-card__status-dot" />{{ t(card.engine?.configured ? 'adminParsers.configured' : 'adminParsers.unavailable') }}</span>
            </span><span class="engine-card__desc">{{ card.engine?.reason || card.engine?.file_types.join(', ') || card.title }}</span></span>
          </button>
        </div>
      </t-loading>
    </template>
    <SettingDrawer v-model:visible="drawerVisible" :title="activeGroup?.name || activeEngine" :hide-footer="!activeGroup"
      :confirm-loading="busy" :confirm-disabled="!dirty || busy || loading" :cancel-disabled="busy" @confirm="save" @cancel="drawerVisible = false">
      <template #headerIcon>{{ (activeGroup?.name || activeEngine).charAt(0).toUpperCase() }}</template>
      <t-alert v-if="error" theme="error" :message="error" /><t-alert v-if="success" theme="success" :message="success" />
      <t-form v-if="activeGroup && snapshot" :disabled="busy" layout="vertical" @submit="save">
        <section class="parser-group"><div class="parser-fields">
          <t-form-item v-for="field in activeGroup.fields" :key="field.key" :label="field.label.startsWith('settings.') ? t(field.label) : field.label">
            <t-select v-if="field.boolean" :value="draft[field.key] === true ? 'true' : draft[field.key] === false ? 'false' : 'default'" :options="[{value:'default',label:t('adminParsers.default')},{value:'true',label:t('adminParsers.on')},{value:'false',label:t('adminParsers.off')}]" @change="(value: unknown) => flag(field.key, value)" />
            <div v-else-if="field.secret"><t-input :value="String(draft[field.key] || '')" type="password" autocomplete="new-password" :placeholder="snapshot[field.key] === PARSER_SECRET_MASK ? t('adminParsers.keepSecret') : ''" @change="(value: unknown) => secret(field.key, value)" /><t-checkbox v-if="snapshot[field.key] === PARSER_SECRET_MASK" :checked="cleared.includes(field.key)" @change="(value: unknown) => clearSecret(field.key, value)">{{ t('adminParsers.clearSecret') }}</t-checkbox></div>
            <t-input v-else :value="String(draft[field.key] || '')" :maxlength="1024" @change="(value: unknown) => draft[field.key] = String(value ?? '')" />
          </t-form-item>
        </div></section>
      </t-form>
      <p v-else>{{ engines.find(engine => engine.name === activeEngine)?.reason || engines.find(engine => engine.name === activeEngine)?.description }}</p>
      <template #footer-left><t-button variant="text" :disabled="busy || !dirty" @click="reset">{{ t('adminConsole.reset') }}</t-button></template>
    </SettingDrawer>
  </section>
</template>
<style scoped lang="less">
@import './ParserPage.reference.less';
.parser-fields { display: grid; gap: 4px; }
.parser-fields :deep(.t-form__label) { white-space: normal; }
.parser-fields :deep(.t-input__wrap), .parser-fields :deep(.t-select__wrap) { width: 100%; }
</style>
