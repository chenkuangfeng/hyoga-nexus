<script setup lang="ts">
import { useModelSettings } from '../../composables/useModelSettings'
import ModelEditorDrawer from '../../components/ModelEditorDrawer.vue'
import { MODEL_TYPES, type ModelType } from '../../types/modelSettings'
const settings = useModelSettings()
const { tenants, tenant, loading, busy, error, feedback, data, cards, typeCounts, chatModels, activeType,
  candidatesFor, defaultFor, canManage, manageableProviders, presets, testMessage,
  providerDialog, editingProvider, form, drawerOpen, drawerTest, drawerTesting, drawer, agentName, instructions, agentModel } = settings
const typeFilters = ['all', ...MODEL_TYPES] as const
</script>
<template>
  <main class="model-settings" v-loading="loading" :aria-busy="loading || busy">
    <header>
      <div><p class="eyebrow">{{ $t('modelPage.eyebrow') }}</p><h1>{{ $t('modelPage.heading') }}</h1></div>
      <el-button :disabled="busy || loading || !tenant" @click="settings.editProvider()">{{ $t('modelPage.addProvider') }}</el-button>
    </header>
    <p class="intro">{{ $t('modelPage.intro') }}</p>
    <el-button :disabled="busy || loading" @click="settings.initialize">{{ $t('modelPage.refresh') }}</el-button>
    <p v-if="!tenants.length && !loading">{{ $t('modelPage.noSpaces') }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="error" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>

    <section v-if="tenant" class="settings-section" aria-labelledby="models-title">
      <h2 id="models-title">{{ $t('modelPage.modelsTitle') }}</h2>
      <el-radio-group v-model="activeType" class="type-tabs" :aria-label="$t('modelPage.modelsTitle')">
        <el-radio-button v-for="filter in typeFilters" :key="filter" :value="filter">
          {{ filter === 'all' ? $t('modelPage.typeAll') : $t(`modelPage.types.${filter}`) }} ({{ typeCounts[filter] }})
        </el-radio-button>
      </el-radio-group>
      <div class="card-grid">
        <article v-for="card in cards" :key="card.model.id" class="model-card">
          <header>
            <div class="title"><strong>{{ card.model.name }}</strong><el-tag size="small">{{ $t(`modelPage.types.${card.model.model_type}`) }}</el-tag></div>
            <span class="model-version">{{ card.provider.name }} · {{ $t('modelPage.version', { n: card.model.version }) }}</span>
          </header>
          <div class="tags">
            <el-tag v-if="defaultFor('personal', card.model.model_type) === card.model.version_id" size="small" type="success">{{ $t('modelPage.personalDefault') }}</el-tag>
            <el-tag v-if="defaultFor('tenant', card.model.model_type) === card.model.version_id" size="small" type="success">{{ $t('modelPage.spaceDefault') }}</el-tag>
            <el-tag v-if="card.model.model_type !== 'chat'" size="small" type="info">{{ $t('modelPage.tagPending') }}</el-tag>
          </div>
          <div v-if="canManage(card.provider)" class="actions">
            <el-button size="small" :disabled="busy" @click="settings.test(card.provider.id, card.model.id)">{{ $t('modelPage.test', { name: card.model.name }) }}</el-button>
            <el-button size="small" :disabled="busy" @click="settings.openDrawer(card)">{{ $t('modelPage.editModel', { name: card.model.name }) }}</el-button>
            <el-button size="small" :disabled="busy" type="danger" plain @click="settings.confirmRemove(card.provider, card.model)">{{ $t('modelPage.disableModel', { name: card.model.name }) }}</el-button>
          </div>
        </article>
        <button type="button" class="model-card add-card" :disabled="busy || loading" @click="settings.openDrawer(undefined, activeType === 'all' ? undefined : (activeType as ModelType))">
          <span aria-hidden="true">+</span>{{ $t('modelPage.addModel') }}
        </button>
      </div>
      <el-empty v-if="!cards.length && !loading" :description="$t('modelPage.noModels')" />
      <p class="intro">{{ $t('modelPage.testIntro') }}</p>
    </section>

    <section v-if="tenant" class="settings-section" aria-labelledby="defaults-title">
      <h2 id="defaults-title">{{ $t('modelPage.defaults') }}</h2>
      <p class="intro">{{ $t('modelPage.defaultsIntro') }}</p>
      <table class="defaults-table">
        <thead><tr><th scope="col">{{ $t('modelPage.modelType') }}</th><th scope="col">{{ $t('modelPage.personalDefault') }}</th><th scope="col">{{ $t('modelPage.spaceDefault') }}</th></tr></thead>
        <tbody>
          <tr v-for="type in MODEL_TYPES" :key="type">
            <th scope="row">{{ $t(`modelPage.types.${type}`) }}</th>
            <td>
              <el-select :id="`personal-default-${type}`" :model-value="defaultFor('personal', type) || ''" clearable :disabled="busy || loading" :placeholder="$t('modelPage.useSpaceDefault')" :aria-label="$t('modelPage.personalDefault')" @change="(value: string) => settings.setDefault('personal', type as ModelType, value || null)">
                <el-option v-for="card in candidatesFor('personal', type)" :key="card.model.version_id" :label="card.label" :value="card.model.version_id" />
              </el-select>
            </td>
            <td>
              <el-select :id="`tenant-default-${type}`" :model-value="defaultFor('tenant', type) || ''" clearable :disabled="busy || loading || !data.can_manage_tenant" :placeholder="$t('modelPage.notSet')" :aria-label="$t('modelPage.spaceDefault')" @change="(value: string) => settings.setDefault('tenant', type as ModelType, value || null)">
                <el-option v-for="card in candidatesFor('tenant', type)" :key="card.model.version_id" :label="card.label" :value="card.model.version_id" />
              </el-select>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="intro">{{ $t('modelPage.priorityIntro') }}</p>
    </section>

    <section class="settings-section" aria-labelledby="providers-title">
      <h2 id="providers-title">{{ $t('modelPage.providers') }}</h2>
      <el-empty v-if="!data.providers.length && !loading" :description="$t('modelPage.noProviders')" />
      <article v-for="provider in data.providers" :key="provider.id" class="provider-row">
        <div>
          <h3>{{ provider.name }} <el-tag>{{ provider.scope === 'personal' ? $t('modelPage.scopePersonal') : $t('modelPage.scopeShared') }}</el-tag></h3>
          <p class="provider-address">{{ provider.base_url }}</p>
          <p class="muted">API Key：{{ provider.key_configured ? $t('modelPage.keyConfigured') : $t('modelPage.keyMissing') }} · {{ $t('modelPage.protocolCompat') }}</p>
        </div>
        <div v-if="canManage(provider)" class="actions">
          <el-button :disabled="busy" @click="settings.editProvider(provider)">{{ $t('modelPage.editProvider') }}</el-button>
          <el-button :disabled="busy" type="danger" plain @click="settings.confirmRemove(provider)">{{ $t('modelPage.disableProvider') }}</el-button>
        </div>
      </article>
    </section>

    <section v-if="tenant" class="settings-section" aria-labelledby="agent-title">
      <h2 id="agent-title">{{ $t('modelPage.agentTitle') }}</h2><p class="intro">{{ $t('modelPage.agentIntro') }}</p>
      <el-form label-position="top" @submit.prevent="settings.createAgent">
        <el-form-item :label="$t('modelPage.agentName')" label-for="settings-agent-name"><el-input id="settings-agent-name" v-model="agentName" maxlength="160" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.model')" label-for="settings-agent-model"><el-select id="settings-agent-model" v-model="agentModel" :disabled="busy" :placeholder="$t('modelPage.pickModel')">
          <el-option v-for="card in chatModels" :key="card.model.version_id" :label="card.label" :value="card.model.version_id" /></el-select></el-form-item>
        <el-form-item :label="$t('modelPage.instructions')" label-for="settings-agent-instructions"><el-input id="settings-agent-instructions" v-model="instructions" type="textarea" :rows="3" maxlength="20000" :disabled="busy" /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!agentName.trim() || !agentModel || loading">{{ $t('modelPage.createAgent') }}</el-button>
      </el-form>
    </section>

    <el-dialog v-model="providerDialog" :title="editingProvider ? $t('modelPage.editProvider') : $t('modelPage.addProvider')" width="min(560px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @closed="form.api_key = ''">
      <el-form label-position="top" @submit.prevent="settings.saveProvider">
        <el-form-item :label="$t('modelPage.name')" label-for="provider-name"><el-input id="provider-name" v-model="form.name" maxlength="160" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.scope')" label-for="provider-scope"><el-select id="provider-scope" v-model="form.scope" :disabled="busy || !!editingProvider">
          <el-option :label="$t('modelPage.scopePersonal')" value="personal" /><el-option v-if="data.can_manage_tenant" :label="$t('modelPage.scopeShared')" value="tenant" /></el-select></el-form-item>
        <el-form-item :label="$t('modelPage.baseUrl')" label-for="provider-url"><el-input id="provider-url" v-model="form.base_url" maxlength="512" placeholder="https://api.example.com/v1" :disabled="busy" /></el-form-item>
        <el-form-item :label="editingProvider ? $t('modelPage.replaceKey') : 'API Key'" label-for="provider-key"><el-input id="provider-key" v-model="form.api_key" type="password" autocomplete="new-password" :disabled="busy" maxlength="8192" /></el-form-item>
        <p>{{ $t('modelPage.keyNote') }}</p>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!form.name.trim() || !form.base_url.trim() || (!editingProvider && !form.api_key)">{{ $t('modelPage.saveProvider') }}</el-button>
        <el-button :disabled="busy" @click="providerDialog = false; form.api_key = ''">{{ $t('common.cancel') }}</el-button>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p>
    </el-dialog>

    <ModelEditorDrawer v-model="drawerOpen" :draft="drawer" :providers="manageableProviders" :presets="presets" :busy="busy" :testing="drawerTesting"
      :test-result="drawerTest ? { ...drawerTest, message: testMessage(drawerTest) } : null" :can-share-providers="data.can_manage_tenant"
      @save="settings.saveDrawer" @test="settings.testDraft" @preset="settings.applyPreset" />
  </main>
</template>
<style scoped>
.model-settings { max-width: 1050px; }
.settings-section { margin: 24px 0; padding: 24px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.type-tabs { margin: 16px 0; max-width: 100%; flex-wrap: wrap; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.model-card { display: grid; gap: 12px; align-content: start; padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); min-width: 0; }
.model-card header { display: grid; gap: 4px; min-width: 0; }
.model-card .title { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
.model-card strong { overflow-wrap: anywhere; }
.model-version { color: var(--muted-text); font-size: 13px; overflow-wrap: anywhere; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; min-height: 24px; }
.add-card { justify-content: center; align-items: center; border-style: dashed; color: var(--el-color-primary); font: inherit; cursor: pointer; min-height: 120px; background: transparent; }
.add-card:disabled { cursor: not-allowed; color: var(--muted-text); }
.add-card span { font-size: 24px; margin-right: 8px; }
.defaults-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
.defaults-table th, .defaults-table td { padding: 10px 8px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: middle; }
.defaults-table td .el-select { width: 100%; min-width: 0; }
.provider-row { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 16px 0; border-top: 1px solid var(--border); }
.provider-row h3 { margin: 0; overflow-wrap: anywhere; font-size: 16px; }
.provider-address { overflow-wrap: anywhere; color: var(--muted-text); margin: 4px 0; }
.muted { color: var(--muted-text); font-size: 13px; margin: 4px 0 0; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-start; }
.feedback { min-height: 24px; color: var(--el-color-primary); }
@media (max-width: 700px) { .settings-section { padding: 16px; } header { align-items: flex-start; flex-direction: column; } .defaults-table th:nth-child(1) { width: 30%; } }
</style>
