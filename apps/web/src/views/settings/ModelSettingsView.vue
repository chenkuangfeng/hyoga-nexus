<script setup lang="ts">
import { useModelSettings } from '../../composables/useModelSettings'
const settings = useModelSettings()
const { workspaces, workspace, loading, busy, error, feedback, data, models, providerDialog, modelDialog, form,
  editingProvider, modelName, agentName, instructions, agentModel } = settings
</script>
<template>
  <main class="model-settings" v-loading="loading" :aria-busy="loading || busy">
    <header><div><p class="eyebrow">HYOGA NEXUS / 用户设置</p><h1>模型供应商</h1></div>
      <el-button :disabled="busy || loading || !workspace" @click="settings.editProvider()">添加供应商</el-button></header>
    <p class="intro">管理个人和空间共享模型。默认模型用于新建智能体，已有会话保持原来的模型版本。</p>
    <label for="settings-workspace">工作空间</label>
    <el-select id="settings-workspace" v-model="workspace" :disabled="busy || loading" @change="settings.load">
      <el-option v-for="item in workspaces" :key="item.id" :value="item.id" :label="item.name" />
    </el-select>
    <el-button :disabled="busy || loading" @click="settings.initialize">刷新设置</el-button>
    <p v-if="!workspaces.length && !loading">暂无可用空间，请先创建空间或联系管理员加入。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="error" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>
    <section v-if="workspace" class="settings-section" aria-labelledby="defaults-title">
      <h2 id="defaults-title">默认模型</h2>
      <div class="defaults-grid">
        <div><label for="personal-default">个人默认</label>
          <el-select id="personal-default" :model-value="data.defaults.personal || ''" clearable :disabled="busy || loading" placeholder="使用空间默认" @change="(value: string) => settings.setDefault('personal', value || null)">
            <el-option v-for="model in models" :key="model.version_id" :label="model.label" :value="model.version_id" />
          </el-select></div>
        <div><label for="workspace-default">空间默认</label>
          <el-select id="workspace-default" :model-value="data.defaults.workspace || ''" clearable :disabled="busy || loading || !data.can_manage_workspace" placeholder="尚未设置" @change="(value: string) => settings.setDefault('workspace', value || null)">
            <el-option v-for="model in models.filter(item => item.scope === 'workspace')" :key="model.version_id" :label="model.label" :value="model.version_id" />
          </el-select></div>
      </div>
      <p class="intro">优先使用明确选择的模型，其次为个人默认、空间默认。空间默认由管理员维护。</p>
    </section>
    <section class="settings-section" aria-labelledby="providers-title">
      <h2 id="providers-title">已配置供应商</h2>
      <el-empty v-if="!data.providers.length && !loading" description="还没有供应商，添加后可配置模型" />
      <article v-for="provider in data.providers" :key="provider.id" class="provider-card">
        <header><h3>{{ provider.name }} <el-tag>{{ provider.scope === 'personal' ? '仅本人' : '空间共享' }}</el-tag></h3>
          <div v-if="provider.scope === 'personal' || data.can_manage_workspace" class="actions">
            <el-button :disabled="busy" @click="settings.editProvider(provider)">编辑供应商</el-button>
            <el-button :disabled="busy" type="danger" plain @click="settings.confirmRemove(provider)">停用供应商</el-button></div></header>
        <p class="provider-address">{{ provider.base_url }}</p><p>API Key：{{ provider.key_configured ? '已配置 ••••••••' : '未配置' }} · OpenAI 兼容协议</p>
        <p v-if="!provider.models.length">尚未添加模型，请填写账号可用的模型名称。</p>
        <ul class="model-list"><li v-for="model in provider.models" :key="model.id">
          <div><strong>{{ model.name }}</strong><span class="model-version">版本 {{ model.version }}</span>
            <el-tag v-if="data.defaults.personal === model.version_id">个人默认</el-tag>
            <el-tag v-if="data.defaults.workspace === model.version_id">空间默认</el-tag></div>
          <div v-if="provider.scope === 'personal' || data.can_manage_workspace" class="actions">
            <el-button :disabled="busy" @click="settings.test(provider.id, model.id)">测试 {{ model.name }}</el-button>
            <el-button :disabled="busy" @click="settings.editModel(provider.id, model.id, model.name)">编辑 {{ model.name }}</el-button>
            <el-button :disabled="busy" type="danger" plain @click="settings.confirmRemove(provider, model)">停用 {{ model.name }}</el-button>
          </div>
        </li></ul>
        <el-button v-if="provider.scope === 'personal' || data.can_manage_workspace" :disabled="busy" @click="settings.editModel(provider.id)">添加模型</el-button>
      </article>
      <p class="intro">测试会发送少量模型请求，可能产生费用；测试通过不代表完整模型与工具能力已验收。</p>
    </section>
    <section v-if="workspace" class="settings-section" aria-labelledby="agent-title">
      <h2 id="agent-title">创建对话智能体</h2><p class="intro">选择模型并发布后，即可在对话工作台新建会话。</p>
      <el-form label-position="top" @submit.prevent="settings.createAgent">
        <el-form-item label="智能体名称" label-for="settings-agent-name"><el-input id="settings-agent-name" v-model="agentName" maxlength="160" :disabled="busy" /></el-form-item>
        <el-form-item label="模型" label-for="settings-agent-model"><el-select id="settings-agent-model" v-model="agentModel" :disabled="busy" placeholder="选择模型">
          <el-option v-for="model in models" :key="model.version_id" :label="model.label" :value="model.version_id" /></el-select></el-form-item>
        <el-form-item label="指令" label-for="settings-agent-instructions"><el-input id="settings-agent-instructions" v-model="instructions" type="textarea" :rows="3" maxlength="20000" :disabled="busy" /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!agentName.trim() || !agentModel || loading">创建并发布</el-button>
      </el-form>
    </section>
    <el-dialog v-model="providerDialog" :title="editingProvider ? '编辑供应商' : '添加供应商'" width="min(560px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @closed="form.api_key = ''">
      <el-form label-position="top" @submit.prevent="settings.saveProvider">
        <el-form-item label="名称" label-for="provider-name"><el-input id="provider-name" v-model="form.name" maxlength="160" :disabled="busy" /></el-form-item>
        <el-form-item label="可见范围" label-for="provider-scope"><el-select id="provider-scope" v-model="form.scope" :disabled="busy || !!editingProvider">
          <el-option label="仅本人" value="personal" /><el-option v-if="data.can_manage_workspace" label="空间共享" value="workspace" /></el-select></el-form-item>
        <el-form-item label="API 地址" label-for="provider-url"><el-input id="provider-url" v-model="form.base_url" maxlength="512" placeholder="https://api.example.com/v1" :disabled="busy" /></el-form-item>
        <el-form-item :label="editingProvider ? '替换 API Key（留空保留原值）' : 'API Key'" label-for="provider-key"><el-input id="provider-key" v-model="form.api_key" type="password" autocomplete="new-password" :disabled="busy" maxlength="8192" /></el-form-item>
        <p>Key 保存后不回显。修改 API 地址时需要同时填写新的 Key。同一地址的 Key 替换会应用于引用它的已有模型版本。</p>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!form.name.trim() || !form.base_url.trim() || (!editingProvider && !form.api_key)">保存供应商</el-button>
        <el-button :disabled="busy" @click="providerDialog = false; form.api_key = ''">取消</el-button>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p>
    </el-dialog>
    <el-dialog v-model="modelDialog" title="配置模型" width="min(480px, 94vw)" :close-on-click-modal="!busy" :show-close="!busy" :close-on-press-escape="!busy">
      <el-form label-position="top" @submit.prevent="settings.saveModel">
        <el-form-item label="模型名称" label-for="provider-model-name"><el-input id="provider-model-name" v-model="modelName" maxlength="160" :disabled="busy" placeholder="填写供应商实际支持的模型名" /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!modelName.trim()">保存模型</el-button>
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
