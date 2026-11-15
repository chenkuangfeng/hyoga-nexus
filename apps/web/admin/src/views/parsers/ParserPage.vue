<script setup lang="ts">
/** 既有解析配置的企业治理：全量替换保留快照，密钥只写，异步结果绑定当前身份。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from '../../stores/context'
import { getEnterpriseParserConfig, listEnterpriseParserEngines, saveEnterpriseParserConfig, parserConfigPayload, PARSER_GROUPS, PARSER_SECRET_KEYS, PARSER_SECRET_MASK, type ParserConfig, type ParserEngine } from '@nexus-web/core/api/enterprise-parsers'
const auth = useAuthStore(), context = useAdminContext(), { t } = useI18n()
const allowed = computed(() => context.ready && ['owner', 'admin'].includes(auth.currentTenantRole || ''))
const snapshot = ref<ParserConfig | null>(null), draft = ref<ParserConfig>({}), cleared = ref<string[]>([]), engines = ref<ParserEngine[]>([])
const loading = ref(false), busy = ref(false), error = ref(''), success = ref('')
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const payload = computed(() => snapshot.value ? parserConfigPayload(snapshot.value, draft.value, cleared.value) : {})
const dirty = computed(() => !!snapshot.value && JSON.stringify(payload.value) !== JSON.stringify(snapshot.value))
function accept(config: ParserConfig) {
  snapshot.value = config; draft.value = { ...config }; cleared.value = []
  for (const key of PARSER_SECRET_KEYS) draft.value[key] = ''
}
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; snapshot.value = null; draft.value = {}; cleared.value = []; engines.value = []; loading.value = false; busy.value = false; error.value = ''; success.value = '' }
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
  <section class="parser-page">
    <header class="section-header"><div><h2>{{ t('adminParsers.title') }}</h2><p>{{ t('adminParsers.description') }}</p></div><t-button variant="outline" :disabled="busy" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!allowed" theme="warning" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" /><t-alert v-if="success" theme="success" :message="success" />
      <t-loading :loading="loading"><template v-if="snapshot">
        <div class="engine-list"><article v-for="engine in engines" :key="engine.name"><strong>{{ engine.description }}</strong> <t-tag :theme="engine.configured ? 'success' : 'warning'">{{ t(engine.configured ? 'adminParsers.configured' : 'adminParsers.unavailable') }}</t-tag><p>{{ engine.file_types.join(', ') }}</p><p v-if="engine.reason">{{ engine.reason }}</p></article></div>
        <t-form :disabled="busy" layout="vertical" @submit="save">
          <section v-for="group in PARSER_GROUPS" :key="group.name" class="parser-group"><h3>{{ group.name }}</h3>
            <div class="parser-fields"><t-form-item v-for="field in group.fields" :key="field.key" :label="field.label.startsWith('settings.') ? t(field.label) : field.label">
              <t-select v-if="field.boolean" :value="draft[field.key] === true ? 'true' : draft[field.key] === false ? 'false' : 'default'" :options="[{value:'default',label:t('adminParsers.default')},{value:'true',label:t('adminParsers.on')},{value:'false',label:t('adminParsers.off')}]" @change="(value: unknown) => flag(field.key, value)" />
              <div v-else-if="field.secret"><t-input :value="String(draft[field.key] || '')" type="password" autocomplete="new-password" :placeholder="snapshot[field.key] === PARSER_SECRET_MASK ? t('adminParsers.keepSecret') : ''" @change="(value: unknown) => secret(field.key, value)" /><t-checkbox v-if="snapshot[field.key] === PARSER_SECRET_MASK" :checked="cleared.includes(field.key)" @change="(value: unknown) => clearSecret(field.key, value)">{{ t('adminParsers.clearSecret') }}</t-checkbox></div>
              <t-input v-else :value="String(draft[field.key] || '')" :maxlength="1024" @change="(value: unknown) => draft[field.key] = String(value ?? '')" />
            </t-form-item></div>
          </section>
          <div class="parser-actions"><t-button type="submit" theme="primary" :loading="busy" :disabled="!dirty || busy || loading">{{ t('common.save') }}</t-button><t-button variant="outline" :disabled="busy || !dirty" @click="reset">{{ t('adminConsole.reset') }}</t-button></div>
        </t-form>
      </template></t-loading>
    </template>
  </section>
</template>
<style scoped>
.parser-page { display: grid; gap: 20px; min-width: 0; }
.section-header,.parser-actions { display: flex; gap: 12px; justify-content: space-between; flex-wrap: wrap; }
p { color: var(--td-text-color-secondary); overflow-wrap: anywhere; }
.engine-list,.parser-fields { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,280px),1fr)); gap: 16px; }
.engine-list article,.parser-group { padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); }
.parser-group { margin: 20px 0; } .parser-fields :deep(.t-form__label) { white-space: normal; }
.parser-fields :deep(.t-input__wrap),.parser-fields :deep(.t-select__wrap) { width: 100%; }
.parser-actions { justify-content: flex-start; }
</style>
