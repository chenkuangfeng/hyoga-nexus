<script setup lang="ts">
import { useModelSettings } from '../../composables/useModelSettings'
import { i18n } from '../../i18n'
const settings = useModelSettings()
const { tenants, tenant, loading, busy, error, feedback, data, models, providerDialog, modelDialog, form,
  editingProvider, modelName, modelProtocol, modelStream, modelTextTools, reasoningEffort, temperature, agentName, instructions, agentModel } = settings
</script>
<template>
  <main class="model-settings" v-loading="loading" :aria-busy="loading || busy">
    <header><div><p class="eyebrow">{{ $t('modelPage.eyebrow') }}</p><h1>{{ $t('modelPage.heading') }}</h1></div>
      <el-button :disabled="busy || loading || !tenant" @click="settings.editProvider()">{{ $t('modelPage.addProvider') }}</el-button></header>
    <p class="intro">{{ $t('modelPage.intro') }}</p>
    <el-button :disabled="busy || loading" @click="settings.initialize">{{ $t('modelPage.refresh') }}</el-button>
    <p v-if="!tenants.length && !loading">{{ $t('modelPage.noSpaces') }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="error" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>
    <section v-if="tenant" class="settings-section" aria-labelledby="defaults-title">
      <h2 id="defaults-title">{{ $t('modelPage.defaults') }}</h2>
      <div class="defaults-grid">
        <div><label for="personal-default">{{ $t('modelPage.personalDefault') }}</label>
          <el-select id="personal-default" :model-value="data.defaults.personal || ''" clearable :disabled="busy || loading" :placeholder="$t('modelPage.useSpaceDefault')" @change="(value: string) => settings.setDefault('personal', value || null)">
            <el-option v-for="model in models" :key="model.version_id" :label="model.label" :value="model.version_id" />
          </el-select></div>
        <div><label for="tenant-default">{{ $t('modelPage.spaceDefault') }}</label>
          <el-select id="tenant-default" :model-value="data.defaults.tenant || ''" clearable :disabled="busy || loading || !data.can_manage_tenant" :placeholder="$t('modelPage.notSet')" @change="(value: string) => settings.setDefault('tenant', value || null)">
            <el-option v-for="model in models.filter(item => item.scope === 'tenant')" :key="model.version_id" :label="model.label" :value="model.version_id" />
          </el-select></div>
      </div>
      <p class="intro">{{ $t('modelPage.priorityIntro') }}</p>
    </section>
    <section class="settings-section" aria-labelledby="providers-title">
      <h2 id="providers-title">{{ $t('modelPage.providers') }}</h2>
      <el-empty v-if="!data.providers.length && !loading" :description="$t('modelPage.noProviders')" />
      <article v-for="provider in data.providers" :key="provider.id" class="provider-card">
        <header><h3>{{ provider.name }} <el-tag>{{ provider.scope === 'personal' ? $t('modelPage.scopePersonal') : $t('modelPage.scopeShared') }}</el-tag></h3>
          <div v-if="provider.scope === 'personal' || data.can_manage_tenant" class="actions">
            <el-button :disabled="busy" @click="settings.editProvider(provider)">{{ $t('modelPage.editProvider') }}</el-button>
            <el-button :disabled="busy" type="danger" plain @click="settings.confirmRemove(provider)">{{ $t('modelPage.disableProvider') }}</el-button></div></header>
        <p class="provider-address">{{ provider.base_url }}</p><p>API Key：{{ provider.key_configured ? $t('modelPage.keyConfigured') : $t('modelPage.keyMissing') }} · {{ $t('modelPage.protocolCompat') }}</p>
        <p v-if="!provider.models.length">{{ $t('modelPage.noModels') }}</p>
        <ul class="model-list"><li v-for="model in provider.models" :key="model.id">
          <div><strong>{{ model.name }}</strong><span class="model-version">{{ $t('modelPage.version', { n: model.version }) }}</span>
            <el-tag v-if="data.defaults.personal === model.version_id">{{ $t('modelPage.personalDefault') }}</el-tag>
            <el-tag v-if="data.defaults.tenant === model.version_id">{{ $t('modelPage.spaceDefault') }}</el-tag></div>
          <div v-if="provider.scope === 'personal' || data.can_manage_tenant" class="actions">
            <el-button :disabled="busy" @click="settings.test(provider.id, model.id)">{{ $t('modelPage.test', { name: model.name }) }}</el-button>
            <el-button :disabled="busy" @click="settings.editModel(provider.id, model.id, model.name)">{{ $t('modelPage.editModel', { name: model.name }) }}</el-button>
            <el-button :disabled="busy" type="danger" plain @click="settings.confirmRemove(provider, model)">{{ $t('modelPage.disableModel', { name: model.name }) }}</el-button>
          </div>
        </li></ul>
        <el-button v-if="provider.scope === 'personal' || data.can_manage_tenant" :disabled="busy" @click="settings.editModel(provider.id)">{{ $t('modelPage.addModel') }}</el-button>
      </article>
      <p class="intro">{{ $t('modelPage.testIntro') }}</p>
    </section>
    <section v-if="tenant" class="settings-section" aria-labelledby="agent-title">
      <h2 id="agent-title">{{ $t('modelPage.agentTitle') }}</h2><p class="intro">{{ $t('modelPage.agentIntro') }}</p>
      <el-form label-position="top" @submit.prevent="settings.createAgent">
        <el-form-item :label="$t('modelPage.agentName')" label-for="settings-agent-name"><el-input id="settings-agent-name" v-model="agentName" maxlength="160" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.model')" label-for="settings-agent-model"><el-select id="settings-agent-model" v-model="agentModel" :disabled="busy" :placeholder="$t('modelPage.pickModel')">
          <el-option v-for="model in models" :key="model.version_id" :label="model.label" :value="model.version_id" /></el-select></el-form-item>
        <el-form-item :label="$t('modelPage.instructions')" label-for="settings-agent-instructions"><el-input id="settings-agent-instructions" v-model="instructions" type="textarea" :rows="3" maxlength="20000" :disabled="busy" /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!agentName.trim() || !agentModel || loading">{{ $t('modelPage.createAgent') }}</el-button>
      </el-form>
    </section>
    <el-dialog v-model="providerDialog" :title="editingProvider ? $t('modelPage.editProvider') : $t('modelPage.addProvider')" width="min(560px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @closed="form.api_key = ''">
      <el-form label-position="top" @submit.prevent="settings.saveProvider">
        <el-form-item :label="$t('modelPage.name')" label-for="provider-name"><el-input id="provider-name" v-model="form.name" maxlength="160" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.scope')" label-for="provider-scope"><el-select id="provider-scope" v-model="form.scope" :disabled="busy || !!editingProvider">
          :label="$t('modelPage.scopePersonal')" value="personal" /><el-option v-if="data.can_manage_tenant" :label="$t('modelPage.scopeShared')" value="tenant" /></el-select></el-form-item>
        <el-form-item :label="$t('modelPage.baseUrl')" label-for="provider-url"><el-input id="provider-url" v-model="form.base_url" maxlength="512" placeholder="https://api.example.com/v1" :disabled="busy" /></el-form-item>
        <el-form-item :label="editingProvider ? $t('modelPage.replaceKey') : 'API Key'" label-for="provider-key"><el-input id="provider-key" v-model="form.api_key" type="password" autocomplete="new-password" :disabled="busy" maxlength="8192" /></el-form-item>
        <p>{{ $t('modelPage.keyNote') }}</p>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!form.name.trim() || !form.base_url.trim() || (!editingProvider && !form.api_key)">{{ $t('modelPage.saveProvider') }}</el-button>
        <el-button :disabled="busy" @click="providerDialog = false; form.api_key = ''">{{ $t('common.cancel') }}</el-button>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p>
    </el-dialog>
    <el-dialog v-model="modelDialog" :title="$t('modelPage.configModel')" width="min(480px, 94vw)" :close-on-click-modal="!busy" :show-close="!busy" :close-on-press-escape="!busy">
      <el-form label-position="top" @submit.prevent="settings.saveModel">
        <el-form-item :label="$t('modelPage.modelName')" label-for="provider-model-name"><el-input id="provider-model-name" v-model="modelName" maxlength="160" :disabled="busy" :placeholder="$t('modelPage.modelNameHint')" /></el-form-item>
        <el-form-item :label="$t('modelPage.protocol')"><el-select v-model="modelProtocol" :disabled="busy"><el-option label="OpenAI Chat Completions" value="openai_chat_completions" /><el-option label="OpenAI Responses" value="openai_responses" /><el-option label="Anthropic Messages" value="anthropic_messages" /></el-select></el-form-item>
        <el-form-item :label="$t('modelPage.stream')"><el-switch v-model="modelStream" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.textTools')"><el-switch v-model="modelTextTools" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.temperature')"><el-input-number v-model="temperature" :min="0" :max="2" :step="0.1" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('modelPage.reasoning')"><el-select v-model="reasoningEffort" clearable :disabled="busy"><el-option v-for="value in ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']" :key="value" :label="value" :value="value" /></el-select></el-form-item>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!modelName.trim()">{{ $t('modelPage.saveModel') }}</el-button>
      </el-form><p v-if="error" role="alert">{{ error }}</p>
    </el-dialog>
  </main>
</template>
<style scoped>
.model-settings { max-width: 1050px; }
.settings-section { margin: 24px 0; padding: 24px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.defaults-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin-top: 20px; }
label { display: block; margin-bottom: 8px; }
.provider-card { margin-top: 20px; padding: 20px; border: 1px solid var(--border); border-radius: 8px; }
h3 { margin: 0; overflow-wrap: anywhere; }
.provider-address { overflow-wrap: anywhere; color: var(--muted-text); }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.actions .el-button + .el-button { margin-left: 0; }
.model-list { list-style: none; padding: 0; }
.model-list li { border-top: 1px solid var(--border); padding: 16px 0; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; overflow-wrap: anywhere; }
.model-version { margin: 0 12px; color: var(--muted-text); }
.feedback { min-height: 24px; color: var(--el-color-primary); }
@media (max-width: 700px) { .defaults-grid { grid-template-columns: 1fr; } .settings-section, .provider-card { padding: 16px; } header { align-items: flex-start; flex-direction: column; } }
</style>
