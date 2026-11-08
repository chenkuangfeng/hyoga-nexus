<template>
  <!--
    Nexus agent editor (openspec 2026-11-05-weknora-agent-tool-model-settings).
    Markup, classes and styles follow WeKnora `views/agent/AgentEditorModal.vue` for the sections Nexus
    supports: basic info, prompts, model, tools, skills and knowledge. Other WeKnora sections (web search,
    MCP, multimodal, suggestions, sharing) are omitted until their backends exist.
  -->
  <SettingsModalShell :visible="visible" :title="isEdit ? $t('agent.editor.editTitle') : $t('agent.editor.createTitle')"
    v-model="currentSection" :nav-groups="navGroups" :loading="loading" :z-index="1000" @close="requestClose">
    <div class="content-wrapper">
      <div v-if="loadError" class="section">
        <t-alert theme="error" :message="loadError" />
      </div>

      <!-- 基本信息 -->
      <div v-show="currentSection === 'basic'" class="section">
        <div class="section-header">
          <h2>{{ $t('agent.editor.basicInfo') }}</h2>
          <p class="section-description">{{ $t('nexusAgent.basicInfoDesc') }}</p>
        </div>
        <div class="settings-group">
          <div v-if="isEdit && agent" class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.agentId') }}</label>
              <p class="desc">{{ $t('agent.editor.agentIdDesc') }}</p>
            </div>
            <div class="setting-control">
              <div class="agent-id-field">
                <code class="agent-id-value" :title="agent.id">{{ agent.id }}</code>
                <t-tooltip :content="$t('common.copy')" placement="top">
                  <t-button theme="default" size="small" variant="text" class="agent-id-copy" @click="copyAgentId">
                    <t-icon name="file-copy" />
                  </t-button>
                </t-tooltip>
              </div>
            </div>
          </div>

          <div class="setting-row" :class="{ 'setting-row--field-highlight': errors.name }">
            <div class="setting-info">
              <label>{{ $t('agent.editor.name') }} <span class="required">*</span></label>
              <p class="desc">{{ $t('agentEditor.desc.name') }}</p>
            </div>
            <div class="setting-control">
              <div class="name-input-wrapper">
                <AgentAvatar :name="form.name || '?'" size="medium" />
                <t-input v-model="form.name" :maxlength="160" :placeholder="$t('agent.editor.namePlaceholder')"
                  class="name-input" :status="errors.name ? 'error' : 'default'" />
              </div>
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.description') }}</label>
              <p class="desc">{{ $t('agentEditor.desc.description') }}</p>
            </div>
            <div class="setting-control">
              <t-textarea v-model="form.description" :maxlength="2000"
                :placeholder="$t('agent.editor.descriptionPlaceholder')" :autosize="{ minRows: 2, maxRows: 4 }" />
            </div>
          </div>

          <!-- Long-term memory (openspec 2026-11-05-memory-switches; WeKnora AgentEditorModal basic section).
               The switch can only turn memory off: space or member settings that are off still win. -->
          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.memoryEnabled') }}</label>
              <p class="desc">{{ $t('agentEditor.desc.memoryEnabled') }}</p>
            </div>
            <div class="setting-control">
              <t-switch v-model="form.memory_enabled" />
            </div>
          </div>

          <div v-if="form.memory_enabled" class="setting-row">
            <div class="setting-info">
              <label>{{ $t('nexusMemory.agentRecall') }}</label>
              <p class="desc">{{ $t('nexusMemory.agentRecallDesc') }}</p>
            </div>
            <div class="setting-control">
              <t-switch v-model="form.memory_recall" />
            </div>
          </div>
        </div>
      </div>

      <!-- 提示词 -->
      <div v-show="currentSection === 'prompts'" class="section">
        <div class="section-header">
          <h2>{{ $t('agent.editor.promptsConfig') }}</h2>
          <p class="section-description">{{ $t('nexusAgent.promptsConfigDesc') }}</p>
        </div>
        <div class="settings-group">
          <div class="setting-row setting-row-vertical" :class="{ 'setting-row--field-highlight': errors.system_prompt }">
            <div class="setting-info">
              <label>{{ $t('agent.editor.systemPrompt') }} <span class="required">*</span></label>
              <p class="desc">{{ $t('agentEditor.desc.systemPrompt') }}</p>
            </div>
            <div class="setting-control setting-control-full">
              <div class="textarea-with-template">
                <t-textarea v-model="form.system_prompt" :maxlength="100000" :autosize="{ minRows: 10, maxRows: 25 }"
                  class="system-prompt-textarea" :status="errors.system_prompt ? 'error' : 'default'" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 模型配置 -->
      <div v-show="currentSection === 'model'" class="section">
        <div class="section-header">
          <h2>{{ $t('agent.editor.modelConfig') }}</h2>
          <p class="section-description">{{ $t('nexusAgent.modelConfigDesc') }}</p>
        </div>
        <div class="settings-group">
          <div class="setting-row" :class="{ 'setting-row--field-highlight': errors.model_id }">
            <div class="setting-info">
              <label>{{ $t('agent.editor.model') }} <span class="required">*</span></label>
              <p class="desc">{{ $t('agentEditor.desc.model') }}</p>
              <p v-if="!loading && chatModels.length === 0" class="desc">
                {{ $t('nexusAgent.noModels') }}
                <t-link theme="primary" @click="goModelSettings">{{ $t('nexusAgent.goModelSettings') }}</t-link>
              </p>
            </div>
            <div class="setting-control">
              <t-select v-model="form.model_id" :placeholder="$t('agent.editor.modelPlaceholder')" filterable
                :status="errors.model_id ? 'error' : 'default'">
                <t-option v-for="option in chatModels" :key="option.value" :value="option.value"
                  :label="`${option.label} · ${option.provider}`" />
              </t-select>
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.temperature') }}</label>
              <p class="desc">{{ $t('nexusAgent.temperatureDesc') }}</p>
            </div>
            <div class="setting-control">
              <div class="slider-wrapper">
                <t-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" />
                <span class="slider-value">{{ form.temperature }}</span>
              </div>
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.maxCompletionTokens') }}</label>
              <p class="desc">{{ $t('nexusAgent.maxTokensDesc', { count: DEFAULT_MAX_OUTPUT_TOKENS }) }}</p>
            </div>
            <div class="setting-control max-tokens-control">
              <t-radio-group v-model="maxTokensMode">
                <t-radio-button value="default">{{ $t('agent.editor.maxCompletionTokensDefault') }}</t-radio-button>
                <t-radio-button value="custom">{{ $t('agent.editor.maxCompletionTokensCustom') }}</t-radio-button>
              </t-radio-group>
              <span v-if="maxTokensMode === 'default'" class="max-tokens-value">{{ DEFAULT_MAX_OUTPUT_TOKENS }}</span>
              <t-input-number v-else v-model="form.max_completion_tokens" :min="100" :max="MAX_OUTPUT_TOKENS_LIMIT"
                :step="100" theme="column" />
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.thinking') }}</label>
              <p class="desc">{{ $t('nexusAgent.thinkingDesc') }}</p>
            </div>
            <div class="setting-control">
              <t-select v-model="form.reasoning_effort" class="reasoning-effort-select"
                :popup-props="{ overlayClassName: 'reasoning-level-select-popup' }">
                <t-option v-for="level in REASONING_EFFORTS" :key="level" :value="level"
                  :label="$t(levelLabelKey(level))" :show-overflow-tooltip="false">
                  <div class="reasoning-level-option">
                    <span class="reasoning-level-option__title">{{ $t(levelLabelKey(level)) }}</span>
                    <span class="reasoning-level-option__hint">{{ $t(levelDescriptionKey(level)) }}</span>
                  </div>
                </t-option>
              </t-select>
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agent.editor.maxIterations') }}</label>
              <p class="desc">{{ $t('nexusAgent.maxIterationsDesc', { max: MAX_ROUNDS_LIMIT }) }}</p>
            </div>
            <div class="setting-control">
              <t-input-number v-model="form.max_iterations" :min="1" :max="MAX_ROUNDS_LIMIT" theme="column" />
            </div>
          </div>

          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('agentEditor.llmCallTimeout.label') }}</label>
              <p class="desc">{{ $t('nexusAgent.llmCallTimeoutDesc', { seconds: DEFAULT_MODEL_TIMEOUT_SECONDS }) }}</p>
            </div>
            <div class="setting-control">
              <t-input-number v-model="timeoutInput" :min="1" :max="3600" theme="column"
                :placeholder="String(DEFAULT_MODEL_TIMEOUT_SECONDS)" clearable />
            </div>
          </div>
        </div>
      </div>

      <!-- 技能（openspec 2026-11-07-skill-evolution）：内置技能在所有空间可见、可分配；技能只提供步骤，不授予权限 -->
      <div v-show="currentSection === 'skills'" class="section">
        <div class="section-header">
          <h2>{{ $t('nexusAgent.skillBinding.navLabel') }}</h2>
          <p class="section-description">{{ $t('nexusAgent.skillBinding.desc') }}</p>
          <t-button size="small" variant="outline" class="skill-install-button" @click="mySkillsOpen = true">
            <template #icon><t-icon name="user" /></template>
            {{ $t('nexusAgent.mySkills.openButton') }}
          </t-button>
          <t-button v-if="canManageSpace" size="small" variant="outline" class="skill-install-button"
            @click="installOpen = true">
            <template #icon><t-icon name="upload" /></template>
            {{ $t('nexusAgent.skillInstall.openButton') }}
          </t-button>
        </div>
        <t-alert v-if="skillsError" theme="error" :message="skillsError" class="skill-alert">
          <template #operation>
            <t-link theme="primary" @click="loadSkills">{{ $t('nexusAgent.skillBinding.retry') }}</t-link>
          </template>
        </t-alert>
        <t-loading :loading="skillsLoading" size="small">
          <t-checkbox-group :value="form.skills.map(skill => skill.name)" class="skill-groups" @change="onSkillsChange">
            <section v-for="group in skillGroups" v-show="group.items.length" :key="group.key" class="skill-group">
              <header class="tool-group-header">
                <span class="tool-group-bar" />
                <span class="tool-group-title">{{ group.label }}</span>
                <span class="tool-group-count">{{ group.items.length }}</span>
              </header>
              <div class="skill-list">
                <div v-for="skill in group.items" :key="skill.name"
                  :class="['skill-row', { 'skill-row--off': skill.disabled }]">
                  <t-checkbox :value="skill.name" :disabled="!skillSelectable(skill)">
                    <span class="skill-name">{{ skill.name }}</span>
                    <span v-if="skill.version" class="skill-tag skill-tag--muted">
                      {{ $t('nexusAgent.skillBinding.version', { version: skill.version }) }}
                    </span>
                    <span v-if="skill.scope === 'builtin'" class="skill-tag skill-tag--muted">{{ $t('nexusAgent.builtin') }}</span>
                    <span v-if="skill.disabled" class="skill-tag">{{ $t('nexusAgent.disabledHere') }}</span>
                    <span v-if="skillIsOutdated(skill)" class="skill-tag">{{ $t('nexusAgent.skillBinding.newVersion') }}</span>
                    <span v-if="!skill.model_invocable" class="skill-tag skill-tag--muted">
                      {{ $t('nexusAgent.skillBinding.hiddenFromModel') }}
                    </span>
                    <span v-if="skill.execution === 'local'" class="skill-tag skill-tag--muted">
                      {{ $t('nexusAgent.skillBinding.runsOnHost') }}
                    </span>
                  </t-checkbox>
                  <p v-if="skill.description" class="skill-desc">{{ skill.description }}</p>
                  <p v-if="skill.run" :class="['skill-note', { 'skill-note--warn': !skill.run.ok }]">
                    <t-icon :name="skill.run.ok ? 'check-circle' : 'error-circle'" />
                    {{ skill.run.ok ? $t('nexusAgent.skillBinding.runOk')
                      : $t('nexusAgent.skillBinding.runBlocked', { reason: sandboxReasonLabel(skill.run.reason) }) }}
                  </p>
                  <p v-if="skill.disabled && !boundSkill(skill.name)" class="skill-note">
                    {{ $t('nexusAgent.skillBinding.notOffered') }}
                  </p>
                  <p v-if="boundSkill(skill.name) && skillMissingTools(skill).length" class="skill-note skill-note--warn">
                    <t-icon name="error-circle" />
                    {{ $t('nexusAgent.skillBinding.missingTools', { tools: skillMissingTools(skill).map(toolLabel).join('、') }) }}
                  </p>
                  <div v-if="skillIsOutdated(skill) || (skill.scope === 'builtin' && canManageSpace)" class="skill-actions">
                    <t-link v-if="skillIsOutdated(skill)" theme="primary" size="small" @click="updateSkill(skill)">
                      {{ $t('nexusAgent.skillBinding.update') }}
                    </t-link>
                    <template v-if="skill.scope === 'builtin' && canManageSpace">
                      <t-link v-if="skill.disabled" theme="primary" size="small" :disabled="switching === `skill:${skill.name}`"
                        @click="switchBuiltin('skill', skill.name, false)">{{ $t('nexusAgent.restore') }}</t-link>
                      <t-popconfirm v-else :content="$t('nexusAgent.disableHint')"
                        @confirm="switchBuiltin('skill', skill.name, true)">
                        <t-link theme="default" size="small" :disabled="switching === `skill:${skill.name}`">
                          {{ $t('nexusAgent.disableHere') }}
                        </t-link>
                      </t-popconfirm>
                    </template>
                  </div>
                </div>
              </div>
            </section>
          </t-checkbox-group>
          <div v-if="!skillsLoading && !skillsError && !skills.length" class="skill-empty">
            <p>{{ $t('nexusAgent.skillBinding.empty') }}</p>
            <p class="skill-empty-hint">{{ $t('nexusAgent.skillBinding.emptyHint') }}</p>
          </div>
        </t-loading>
      </div>

      <!-- 知识库（openspec 2026-11-06-knowledge-base K1.9）：绑定后智能体获得 search_knowledge 等工具 -->
      <div v-show="currentSection === 'knowledge'" class="section">
        <div class="section-header">
          <h2>知识库</h2>
          <p class="section-description">选择智能体可检索的知识库。保存时会一并绑定知识库检索工具；每次检索仍按使用者此刻的权限过滤。</p>
        </div>
        <t-checkbox-group :value="form.knowledge_bases.map(kb => kb.id)" class="kb-bind-list"
          @change="onKnowledgeChange">
          <t-checkbox v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
            {{ kb.name }}
            <span v-if="kb.shared" class="kb-bind-tag">共享</span>
            <span class="kb-bind-desc">{{ kb.description || `${kb.knowledge_count} 个文档` }}</span>
          </t-checkbox>
        </t-checkbox-group>
        <p v-if="!knowledgeBases.length" class="section-description">当前空间还没有知识库，可在「知识库」页面创建。</p>
      </div>

      <!-- 工具配置 -->
      <div v-show="currentSection === 'tools'" class="section">
        <div class="section-header">
          <h2>{{ $t('agent.editor.toolsConfig') }}</h2>
          <p class="section-description">{{ $t('agent.editor.toolsConfigDesc') }}</p>
        </div>

        <div v-if="inactiveSelected.length > 0" class="tools-overview">
          <div class="tools-overview-row">
            <div class="tools-status-chip tools-status-chip--warn">
              <t-icon name="error-circle" />
              <span>{{ $t('agentEditor.tools.statusInactive', { count: inactiveSelected.length }) }}</span>
            </div>
          </div>
        </div>

        <div class="settings-group">
          <!-- Access level (openspec 2026-11-06-tool-call-hardening D11): tightens what bound tools may do. -->
          <div class="setting-row">
            <div class="setting-info">
              <label>{{ $t('nexusAgent.toolAccess.label') }}</label>
              <p class="desc">{{ $t(`nexusAgent.toolAccess.${form.tool_access}Desc`) }}</p>
            </div>
            <div class="setting-control">
              <t-radio-group v-model="form.tool_access">
                <t-radio-button value="read_only">{{ $t('nexusAgent.toolAccess.read_only') }}</t-radio-button>
                <t-radio-button value="standard">{{ $t('nexusAgent.toolAccess.standard') }}</t-radio-button>
                <t-radio-button value="strict">{{ $t('nexusAgent.toolAccess.strict') }}</t-radio-button>
              </t-radio-group>
            </div>
          </div>

          <!-- Sandbox profile: defined by the operator; an agent only picks one by name (empty = the default). -->
          <div v-if="sandboxProfiles.length" class="setting-row">
            <div class="setting-info">
              <label>{{ $t('nexusAgent.sandboxProfile.label') }}</label>
              <p class="desc">{{ $t('nexusAgent.sandboxProfile.desc') }}</p>
            </div>
            <div class="setting-control sandbox-control">
              <t-select v-model="form.sandbox_profile" :options="sandboxOptions" :popup-props="{ overlayClassName: 'reasoning-level-select-popup' }" />
              <p v-if="chosenSandboxProfile && !chosenSandboxProfile.available" class="sandbox-note" role="status">
                <t-icon name="error-circle" />
                {{ $t('nexusAgent.sandboxProfile.unavailable', { reason: sandboxReasonLabel(chosenSandboxProfile.reason) }) }}
              </p>
              <p v-else-if="chosenSandboxProfile" class="sandbox-note sandbox-note--ok" role="status">
                <t-icon name="check-circle" />
                {{ $t('nexusAgent.sandboxProfile.available') }}
              </p>
            </div>
          </div>

          <div class="setting-row setting-row-vertical">
            <div class="setting-info">
              <label>{{ $t('agent.editor.allowedTools') }}</label>
              <p class="desc">{{ $t('nexusAgent.toolsDesc') }}</p>
            </div>
            <div class="setting-control setting-control-full">
              <t-checkbox-group v-model="form.allowed_tools" class="tool-groups">
                <section v-for="group in toolGroups" :key="group.key" :class="['tool-group', `tool-group--${group.key}`]">
                  <header class="tool-group-header">
                    <span class="tool-group-bar" />
                    <span class="tool-group-title">{{ group.label }}</span>
                    <span class="tool-group-count">{{ group.tools.length }}</span>
                  </header>
                  <div class="tool-grid">
                    <t-checkbox v-for="tool in group.tools" :key="tool.name" :value="tool.name"
                      :disabled="!tool.enabled_in_tenant && !form.allowed_tools.includes(tool.name)"
                      :class="['tool-card', { 'tool-card--disabled': !tool.enabled_in_tenant, 'tool-card--danger': tool.risk_level === 'high' }]">
                      <div class="tool-card-body">
                        <div class="tool-card-head">
                          <span class="tool-card-name">{{ toolLabel(tool.name) }}</span>
                          <span v-if="tool.side_effects || tool.risk_level === 'high'" class="tool-card-badge">
                            {{ $t('agentEditor.tools.dangerTag') }}
                          </span>
                          <span v-if="tool.requires_approval" class="tool-card-badge">{{ $t('nexusAgent.requiresApproval') }}</span>
                          <span v-if="tool.read_only" class="tool-card-badge tool-card-badge--muted">{{ $t('nexusAgent.readOnly') }}</span>
                          <span class="tool-card-badge tool-card-badge--muted">{{ $t(`nexusAgent.risk.${tool.risk || 'write'}`) }}</span>
                          <span v-if="tool.builtin" class="tool-card-badge tool-card-badge--muted">{{ $t('nexusAgent.builtin') }}</span>
                        </div>
                        <span class="tool-card-desc">{{ toolDescription(tool) }}</span>
                        <span v-if="tool.disabled" class="tool-card-hint">
                          {{ $t('nexusAgent.disabledHere') }}
                          <t-link v-if="canManageSpace" theme="primary" size="small" :disabled="switching === `tool:${tool.name}`"
                            @click.stop.prevent="switchBuiltin('tool', tool.name, false)">{{ $t('nexusAgent.restore') }}</t-link>
                        </span>
                        <span v-else-if="!tool.enabled_in_tenant" class="tool-card-hint">
                          <template v-if="catalog?.can_enable_tools">
                            {{ $t('nexusAgent.notEnabled') }}
                            <t-link theme="primary" size="small" :disabled="enabling === tool.name"
                              @click.stop.prevent="enableTool(tool.name)">{{ $t('nexusAgent.enable') }}</t-link>
                          </template>
                          <template v-else>{{ $t('nexusAgent.enableHint') }}</template>
                        </span>
                        <span v-else-if="tool.builtin && canManageSpace" class="tool-card-hint" @click.stop.prevent>
                          <t-popconfirm :content="$t('nexusAgent.disableHint')" @confirm="switchBuiltin('tool', tool.name, true)">
                            <t-link theme="default" size="small" :disabled="switching === `tool:${tool.name}`">
                              {{ $t('nexusAgent.disableHere') }}
                            </t-link>
                          </t-popconfirm>
                        </span>
                      </div>
                    </t-checkbox>
                  </div>
                </section>
              </t-checkbox-group>
            </div>
          </div>

          <div class="setting-row setting-row-vertical">
            <div class="setting-info">
              <label>{{ $t('agentEditor.tools.effectiveLabel') }}</label>
              <p class="desc">{{ $t('agentEditor.tools.effectiveDesc') }}</p>
            </div>
            <div class="setting-control setting-control-full">
              <div class="effective-tools">
                <div v-if="form.allowed_tools.length === 0" class="effective-tools-empty">
                  {{ $t('agentEditor.tools.effectiveEmpty') }}
                </div>
                <template v-else>
                  <span v-for="name in form.allowed_tools" :key="name"
                    :class="['effective-chip', { 'effective-chip--inactive': inactiveSelected.includes(name) }]">
                    <span class="effective-chip-label">{{ toolLabel(name) }}</span>
                    <span v-if="inactiveSelected.includes(name)" class="effective-chip-reason">{{ $t('nexusAgent.notEnabled') }}</span>
                  </span>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <t-button variant="outline" @click="requestClose">{{ $t('common.cancel') }}</t-button>
      <t-button theme="primary" :loading="saving" :disabled="loading || !!loadError" @click="save">
        {{ isEdit ? $t('agent.editor.buttons.saveAndClose') : $t('agent.editor.buttons.create') }}
      </t-button>
    </template>
  <NexusMySkillsDialog v-model:visible="mySkillsOpen" :tenant-id="tenantId" />
  <NexusSkillInstallDialog v-model:visible="installOpen" :tenant-id="tenantId" :sandbox-profile="form.sandbox_profile"
      @installed="loadSkills" />
  </SettingsModalShell>
</template>

<script setup lang="ts">
/**
 * Create or edit a Nexus agent. Saving writes the draft and publishes a new version at once
 * (proposal decision 3), so the agent is usable in chat right after saving. If publishing fails,
 * the draft is kept and the reason is shown; the modal stays open.
 *
 * Props: `visible`, `tenantId` and `agentId` (null to create). Emits `close` and `saved(agent)`.
 */
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import SettingsModalShell from '@/components/SettingsModalShell.vue'
import AgentAvatar from '@/components/AgentAvatar.vue'
import { copyWithToast } from '@/utils/clipboard'
import { levelDescriptionKey, levelLabelKey } from '@/utils/reasoningEffort'
import NexusSkillInstallDialog from './NexusSkillInstallDialog.vue'
import NexusMySkillsDialog from './NexusMySkillsDialog.vue'
import {
  createNexusAgent, disableBuiltinResource, enableTenantTool, getAgentToolCatalog, getNativeDefaults, getNexusAgent,
  listTenantSkills, publishNexusAgent, restoreBuiltinResource, updateNexusAgent, type AgentSandboxProfile,
  type AgentToolCatalog, type AgentToolEntry, type NativeDefaults, type NexusAgent, type TenantSkill,
} from '@/api/nexus-agents'
import { getModelSettings, type ModelSettingsView } from '@/api/nexus-models'
import { listKnowledgeBases } from '@/api/knowledge-base'
import { chatModelOptions, defaultChatVersion, findModelByVersion } from '@/views/settings/nexusModelCards'
import {
  DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_MODEL_TIMEOUT_SECONDS, MAX_OUTPUT_TOKENS_LIMIT, MAX_ROUNDS_LIMIT, REASONING_EFFORTS,
  KNOWLEDGE_TOOLS, draftFromForm, formForNewAgent, formFromAgent, skillHasNewerVersion, skillToolNeeds, validateForm,
  type AgentEditorForm,
} from './nexusAgentForm'

const props = defineProps<{ visible: boolean; tenantId: string; agentId: string | null }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', agent: NexusAgent): void }>()

const { t, te } = useI18n()
const router = useRouter()

const currentSection = ref('basic')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const enabling = ref('')
const agent = ref<NexusAgent | null>(null)
const catalog = ref<AgentToolCatalog | null>(null)
const modelSettings = ref<ModelSettingsView | null>(null)
const nativeDefaults = ref<NativeDefaults | null>(null)
const form = reactive<AgentEditorForm>(formForNewAgent(null, '', []))
const errors = reactive<Partial<Record<keyof AgentEditorForm, string>>>({})

const isEdit = computed(() => !!props.agentId)
const chatModels = computed(() => modelSettings.value ? chatModelOptions(modelSettings.value) : [])

const navGroups = computed(() => [
  {
    key: 'basic', label: t('agentEditor.navGroups.basic'), items: [
      { key: 'basic', icon: 'info-circle', label: t('agent.editor.basicInfo') },
      { key: 'prompts', icon: 'file-paste', label: t('agent.editor.promptsConfig') },
      { key: 'model', icon: 'control-platform', label: t('agent.editor.modelConfig') },
    ],
  },
  {
    key: 'capability', label: t('agentEditor.navGroups.capability'), items: [
      { key: 'tools', icon: 'tools', label: t('agent.editor.toolsConfig'), badge: form.allowed_tools.length || undefined },
      { key: 'skills', icon: 'book', label: t('nexusAgent.skillBinding.navLabel'), badge: form.skills.length || undefined },
      { key: 'knowledge', icon: 'folder', label: '知识库', badge: form.knowledge_bases.length || undefined },
    ],
  },
])

// ---- Skills (openspec 2026-11-07-skill-evolution). The list holds the space's own skills and the builtin ones, which
// every space can see and assign. Choosing a skill grants nothing: the tools needed to read it are bound beside it.
const skills = ref<TenantSkill[]>([])
const skillsLoading = ref(false)
const skillsError = ref('')
const switching = ref('')
const installOpen = ref(false)
const mySkillsOpen = ref(false)
let skillsRequest = 0

async function loadSkills() {
  const request = ++skillsRequest
  skillsLoading.value = true
  skillsError.value = ''
  try {
    const listed = await listTenantSkills(props.tenantId, form.sandbox_profile)
    if (request === skillsRequest) skills.value = listed
  } catch (error) {
    if (request === skillsRequest) {
      skills.value = []
      skillsError.value = errorMessage(error) || t('nexusAgent.skillBinding.loadFailed')
    }
  } finally {
    if (request === skillsRequest) skillsLoading.value = false
  }
}

const canManageSpace = computed(() => !!catalog.value?.can_enable_tools)
const offeredTools = computed(() => new Set((catalog.value?.tools || []).filter(tool => tool.enabled_in_tenant).map(tool => tool.name)))
const builtinSkills = computed(() => skills.value.filter(skill => skill.scope === 'builtin'))
const spaceSkills = computed(() => skills.value.filter(skill => skill.scope !== 'builtin'))
const skillGroups = computed(() => [
  { key: 'builtin', label: t('nexusAgent.skillBinding.builtinGroup'), items: builtinSkills.value },
  { key: 'space', label: t('nexusAgent.skillBinding.spaceGroup'), items: spaceSkills.value },
])
const boundSkill = (name: string) => form.skills.find(skill => skill.name === name)
const skillSelectable = (skill: TenantSkill) => !!skill.version_id && (!skill.disabled || !!boundSkill(skill.name))
const skillMissingTools = (skill: TenantSkill) => skillToolNeeds(skill.tools, offeredTools.value).missing
const skillIsOutdated = (skill: TenantSkill) => skillHasNewerVersion(boundSkill(skill.name), skill.version_id)

function onSkillsChange(names: Array<string | number | boolean>) {
  const chosen = new Set(names.map(String))
  const next = [] as typeof form.skills
  for (const skill of skills.value) {
    if (!chosen.has(skill.name) || !skill.version_id) continue
    // A skill that is already bound keeps its version; a newly chosen one takes the latest.
    next.push(boundSkill(skill.name) || { name: skill.name, version_id: skill.version_id, source_tenant_id: skill.source_tenant_id })
    for (const tool of skillToolNeeds(skill.tools, offeredTools.value).needed) {
      if (offeredTools.value.has(tool) && !form.allowed_tools.includes(tool)) form.allowed_tools.push(tool)
    }
  }
  // Bound skills the list no longer shows (removed or hidden by an administrator) stay until the user clears them.
  const listed = new Set(skills.value.map(skill => skill.name))
  form.skills = [...next, ...form.skills.filter(skill => !listed.has(skill.name) && chosen.has(skill.name))]
}

function updateSkill(skill: TenantSkill) {
  const bound = boundSkill(skill.name)
  if (!bound || !skill.version_id) return
  bound.version_id = skill.version_id
  MessagePlugin.success(t('nexusAgent.skillBinding.updated', { name: skill.name }))
}

/** Turn a builtin tool or skill off for this space only, or back on. Published agent versions are not touched. */
async function switchBuiltin(kind: 'tool' | 'skill', name: string, off: boolean) {
  switching.value = `${kind}:${name}`
  try {
    if (off) await disableBuiltinResource(props.tenantId, kind, name)
    else await restoreBuiltinResource(props.tenantId, kind, name)
    const [tools] = await Promise.all([getAgentToolCatalog(props.tenantId), loadSkills()])
    catalog.value = tools
    MessagePlugin.success(t(off ? 'nexusAgent.disableDone' : 'nexusAgent.restoreDone', { name: kind === 'tool' ? toolLabel(name) : name }))
  } catch (error) {
    MessagePlugin.error(errorMessage(error) || t('nexusAgent.switchFailed'))
  } finally {
    switching.value = ''
  }
}

// ---- Sandbox profile: the operator defines profiles; an agent only picks one by name. Empty means the default.
const sandboxProfiles = computed<AgentSandboxProfile[]>(() => catalog.value?.sandbox_profiles || [])
const sandboxOptions = computed(() => {
  const fallback = sandboxProfiles.value.find(profile => profile.default)
  return [
    { value: '', label: t('nexusAgent.sandboxProfile.defaultOption', { name: fallback?.name || '-' }) },
    ...sandboxProfiles.value.map(profile => ({
      value: profile.name,
      label: t('nexusAgent.sandboxProfile.option', { name: profile.name, type: sandboxTypeLabel(profile.type) })
        + (profile.available ? '' : ` · ${sandboxReasonLabel(profile.reason)}`),
    })),
  ]
})
const chosenSandboxProfile = computed(() => form.sandbox_profile
  ? sandboxProfiles.value.find(profile => profile.name === form.sandbox_profile)
  : sandboxProfiles.value.find(profile => profile.default))

function sandboxTypeLabel(type: string): string {
  const key = type === 'local' ? 'typeLocal' : type === 'docker' ? 'typeDocker' : type === 'bwrap' ? 'typeBwrap' : ''
  return key ? t(`nexusAgent.sandboxProfile.${key}`) : type
}

function sandboxReasonLabel(reason: string): string {
  const key = ({
    sandbox_disabled: 'reasonSandboxDisabled', sandbox_not_accepted: 'reasonNotAccepted',
    sandbox_local_not_allowed: 'reasonLocalNotAllowed', sandbox_profile_unknown: 'reasonUnknown',
    sandbox_unavailable: 'reasonUnavailable', local_not_allowed: 'reasonSkillLocal',
    skill_execution_not_permitted: 'reasonSkillLocal',
  } as Record<string, string>)[reason] || 'reasonOther'
  return t(`nexusAgent.sandboxProfile.${key}`)
}

// Knowledge bases the agent may bind: the space's own and those shared into it.
const knowledgeBases = ref<Array<{ id: string, name: string, description: string, shared: boolean, tenant_id: string,
  knowledge_count: number }>>([])
async function loadKnowledgeBases() {
  try {
    const res: any = await listKnowledgeBases()
    knowledgeBases.value = res?.data || []
  } catch {
    knowledgeBases.value = []
  }
}
void loadKnowledgeBases()

function onKnowledgeChange(ids: Array<string | number | boolean>) {
  const chosen = new Set(ids.map(String))
  form.knowledge_bases = knowledgeBases.value.filter(kb => chosen.has(kb.id))
    .map(kb => ({ id: kb.id, source_tenant_id: kb.tenant_id }))
  // Offer the knowledge tools together with the first base: those the space has enabled are added to the selection.
  if (form.knowledge_bases.length) {
    const enabled = new Set((catalog.value?.tools || []).filter(tool => tool.enabled_in_tenant).map(tool => tool.name))
    for (const name of KNOWLEDGE_TOOLS) {
      if (enabled.has(name) && !form.allowed_tools.includes(name)) form.allowed_tools.push(name)
    }
  }
}

// WeKnora's "default / custom" radio for max tokens; 0 in the form means "default".
const maxTokensMode = computed<'default' | 'custom'>({
  get: () => (form.max_completion_tokens > 0 ? 'custom' : 'default'),
  set: mode => { form.max_completion_tokens = mode === 'custom' ? (form.max_completion_tokens || 4096) : 0 },
})

const timeoutInput = computed<number | undefined>({
  get: () => form.llm_call_timeout ?? undefined,
  set: value => { form.llm_call_timeout = typeof value === 'number' && value > 0 ? value : null },
})

const toolGroups = computed(() => {
  const tools = catalog.value?.tools || []
  const order = catalog.value?.groups || ['base']
  return order.map(key => ({
    key,
    label: te(`nexusAgent.toolGroups.${key}`) ? t(`nexusAgent.toolGroups.${key}`) : key,
    tools: tools.filter(tool => tool.group === key),
  })).filter(group => group.tools.length > 0)
})

/** Selected tools the space has not enabled; the server rejects them at publish. */
const inactiveSelected = computed(() => {
  const enabled = new Set((catalog.value?.tools || []).filter(tool => tool.enabled_in_tenant).map(tool => tool.name))
  return form.allowed_tools.filter(name => !enabled.has(name))
})

function toolLabel(name: string): string {
  return te(`nexusAgent.tools.${name}.label`) ? t(`nexusAgent.tools.${name}.label`) : name
}

function toolDescription(tool: AgentToolEntry): string {
  return te(`nexusAgent.tools.${tool.name}.desc`) ? t(`nexusAgent.tools.${tool.name}.desc`) : tool.description
}

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const record = error as Record<string, unknown>
    const detail = record.detail ?? record.message ?? record.error
    if (typeof detail === 'string') return detail
  }
  return error instanceof Error ? error.message : ''
}

function resetErrors() {
  for (const key of Object.keys(errors)) delete errors[key as keyof AgentEditorForm]
}

async function load() {
  loading.value = true
  loadError.value = ''
  resetErrors()
  currentSection.value = 'basic'
  try {
    const [settings, tools] = await Promise.all([getModelSettings(props.tenantId), getAgentToolCatalog(props.tenantId)])
    modelSettings.value = settings
    catalog.value = tools
    void loadSkills()
    if (props.agentId) {
      const loaded = await getNexusAgent(props.tenantId, props.agentId)
      agent.value = loaded
      const model = loaded.model_profile_version_id ? findModelByVersion(settings, loaded.model_profile_version_id) : undefined
      Object.assign(form, formFromAgent(loaded, model?.options || {}))
    } else {
      agent.value = null
      nativeDefaults.value = await getNativeDefaults(props.tenantId)
      const enabled = new Set(tools.tools.filter(tool => tool.enabled_in_tenant).map(tool => tool.name))
      Object.assign(form, formForNewAgent(nativeDefaults.value, defaultChatVersion(settings),
        tools.default_tools.filter(name => enabled.has(name))))
    }
  } catch (error) {
    loadError.value = errorMessage(error) || t('nexusAgent.loadFailed')
  } finally {
    loading.value = false
  }
}

// The per-skill "can its scripts run here" line depends on the chosen profile, so changing it asks again.
watch(() => form.sandbox_profile, () => { if (props.visible) void loadSkills() })

watch(() => [props.visible, props.agentId, props.tenantId] as const, ([visible]) => {
  if (visible) void load()
}, { immediate: true })

async function enableTool(name: string) {
  enabling.value = name
  try {
    await enableTenantTool(props.tenantId, name)
    catalog.value = await getAgentToolCatalog(props.tenantId)
    if (!form.allowed_tools.includes(name)) form.allowed_tools.push(name)
    MessagePlugin.success(t('nexusAgent.enableDone', { name: toolLabel(name) }))
  } catch (error) {
    MessagePlugin.error(errorMessage(error) || t('nexusAgent.enableFailed'))
  } finally {
    enabling.value = ''
  }
}

function copyAgentId() {
  if (agent.value) void copyWithToast(agent.value.id, 'common.copied')
}

function goModelSettings() {
  emit('close')
  void router.push({ path: '/platform/settings', query: { section: 'models' } })
}

function requestClose() {
  if (!saving.value) emit('close')
}

async function save() {
  resetErrors()
  Object.assign(errors, validateForm(form))
  const firstError = Object.keys(errors)[0] as keyof AgentEditorForm | undefined
  if (firstError) {
    currentSection.value = firstError === 'model_id' ? 'model' : firstError === 'system_prompt' ? 'prompts' : 'basic'
    MessagePlugin.warning(t(errors[firstError] as string))
    return
  }
  saving.value = true
  try {
    const body = draftFromForm(form, agent.value, nativeDefaults.value, props.tenantId)
    const saved = agent.value
      ? await updateNexusAgent(props.tenantId, agent.value.id, body)
      : await createNexusAgent(props.tenantId, body)
    agent.value = saved
    try {
      await publishNexusAgent(props.tenantId, saved.id)
    } catch (error) {
      MessagePlugin.error(t('nexusAgent.publishFailed', { reason: errorMessage(error) || t('nexusAgent.saveFailed') }))
      emit('saved', saved)
      return
    }
    MessagePlugin.success(t('nexusAgent.saved'))
    emit('saved', saved)
    emit('close')
  } catch (error) {
    MessagePlugin.error(errorMessage(error) || t('nexusAgent.saveFailed'))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped lang="less">
// Copied from WeKnora views/agent/AgentEditorModal.vue (sections basic, prompts, model, tools).
.content-wrapper {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 28px 40px 48px;
  box-sizing: border-box;
  scroll-padding-bottom: 24px;

  &--prompts {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding-bottom: 28px;
  }
}

.section {
  width: 100%;
  animation: sectionFadeIn 0.25s ease;
}

@keyframes sectionFadeIn {
  from {
    opacity: 0;
    transform: translateY(6px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.section-header {
  margin-bottom: 20px;

  .section-header-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;

    h2 {
      margin: 0;
    }
  }

  h2 {
    font-size: var(--app-text-3xl);
    font-weight: 600;
    color: var(--td-text-color-primary);
    margin: 0 0 6px 0;
  }

  .section-description {
    font-size: var(--app-text-base);
    color: var(--td-text-color-secondary);
    margin: 0;
    line-height: 1.5;

    .doc-link {
      margin-left: 8px;
    }
  }
}

// 与知识库设置一致的 settings-group 样式
.settings-group {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.parser-policy-block {
  padding: 16px 0;
  border-bottom: 1px solid var(--td-component-stroke);

  &__header {
    margin-bottom: 12px;

    label {
      display: block;
      font-size: var(--app-text-lg);
      font-weight: 500;
      color: var(--td-text-color-primary);
      margin-bottom: 4px;
    }

    .desc {
      margin: 0;
      font-size: var(--app-text-md);
      color: var(--td-text-color-secondary);
      line-height: 1.5;
    }
  }
}

.setting-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--td-component-stroke);
  min-width: 0;

  &:last-child {
    border-bottom: none;
  }

  &.setting-row-vertical {
    flex-direction: column;
    gap: 12px;

    .setting-info {
      max-width: 100%;
      padding-right: 0;
    }
  }

  // 强调行：用于"智能体类型"这类对用户影响最大、需要突出的关键配置。
  // 视觉上只做极轻度强调 —— 左侧 3px 品牌色竖条 + label 加粗。
  &.setting-row--emphasize {
    position: relative;
    padding-left: 14px;

    &::before {
      content: '';
      position: absolute;
      left: 0;
      top: 18px;
      bottom: 18px;
      width: 3px;
      border-radius: var(--app-radius-xs);
      background: var(--td-brand-color);
    }

    .setting-info label {
      font-weight: 600;
    }
  }

  &.setting-row--field-highlight {
    border-radius: var(--app-radius-sm);
    animation: agent-field-flash 0.8s ease-in-out 3;
  }
}

@keyframes agent-field-flash {
  0%,
  100% {
    background-color: transparent;
    box-shadow: none;
  }

  50% {
    background-color: var(--td-warning-color-light);
    box-shadow: inset 0 0 0 1px rgba(237, 123, 47, 0.35);
  }
}

.setting-info {
  flex: 0 0 42%;
  max-width: 42%;
  min-width: 0;
  padding-right: 0;

  &.full-width {
    max-width: 100%;
    padding-right: 0;
  }

  .setting-info-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;

    label {
      margin-bottom: 0;
    }
  }

  label {
    font-size: var(--app-text-lg);
    font-weight: 500;
    color: var(--td-text-color-primary);
    display: block;
    margin-bottom: 4px;

    .required {
      color: var(--td-error-color);
      margin-left: 2px;
    }
  }

  .desc {
    font-size: var(--app-text-md);
    color: var(--td-text-color-secondary);
    margin: 0;
    line-height: 1.5;

    .hint {
      color: var(--td-warning-color);
    }
  }
}

.setting-control {
  flex: 1 1 58%;
  min-width: 0;
  max-width: 58%;
  display: flex;
  justify-content: flex-end;
  align-items: flex-start;
  overflow: hidden;

  .reasoning-effort-select {
    width: 100%;
    max-width: 220px;
  }

  &.setting-control-full {
    width: 100%;
    min-width: 100%;
    max-width: 100%;
    justify-content: flex-start;
  }

  &.max-tokens-control {
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;

    :deep(.t-input-number) {
      width: 140px;
    }
  }

  // 让 select 和 input 占满控件区域
  :deep(.t-select),
  :deep(.t-input),
  :deep(.t-textarea) {
    width: 100%;
    min-width: 0;
  }

  :deep(.t-select-input) {
    min-width: 0;
  }

  :deep(.t-select .t-tag) {
    max-width: 160px;
  }

  :deep(.t-select .t-tag__text) {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  :deep(.t-input-number) {
    width: 120px;
  }
}


.name-input-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;

  .name-input {
    flex: 1;
  }
}

.agent-id-field {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 6px 8px 6px 12px;
  background: var(--td-bg-color-secondarycontainer);
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-sm);

  .agent-id-value {
    flex: 1;
    min-width: 0;
    margin: 0;
    padding: 0;
    background: none;
    border: none;
    font-family: var(--app-font-family-mono);
    font-size: var(--app-text-md);
    line-height: 1.5;
    color: var(--td-text-color-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .agent-id-copy {
    flex-shrink: 0;
    color: var(--td-text-color-secondary);

    &:hover {
      color: var(--td-brand-color);
    }
  }
}

/* 滚动条：与设置弹窗一致 */
.content-wrapper::-webkit-scrollbar {
  width: 6px;
}

.content-wrapper::-webkit-scrollbar-track {
  background: var(--td-bg-color-container);
}

.content-wrapper::-webkit-scrollbar-thumb {
  background: var(--td-gray-color-5);
  border-radius: var(--app-radius-xs);
}

.content-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--td-gray-color-6);
}

// 模式提示样式
.mode-hint {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  background: var(--td-success-color-light);
  border-radius: var(--app-radius-sm);
  border: 1px solid var(--td-success-color-focus);
  color: var(--td-brand-color);
  font-size: var(--app-text-md);
  line-height: 1.5;
}

// 过渡动画
// Slider 样式
.slider-wrapper {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;

  :deep(.t-slider) {
    flex: 1;
  }
}

.slider-value {
  width: 40px;
  text-align: right;
  font-family: var(--app-font-family-mono);
  font-size: var(--app-text-base);
  color: var(--td-text-color-primary);
}

.max-tokens-value {
  font-family: var(--app-font-family-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-placeholder);
}

// 推荐问题列表

.kb-bind-list { display: flex; flex-direction: column; gap: 10px; }
.kb-bind-tag { margin-left: 6px; padding: 0 6px; border-radius: var(--app-radius-pill); font-size: var(--app-text-xs);
  color: var(--td-brand-color); background: var(--td-brand-color-1); }
.kb-bind-desc { margin-left: 8px; color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }

/* Skills (openspec 2026-11-07-skill-evolution). Status is always written out, never colour alone. */
.skill-alert { margin-bottom: 12px; }
.skill-install-button { margin-top: 8px; margin-right: 8px; }
.skill-groups { display: flex; flex-direction: column; gap: 20px; width: 100%; }
.skill-list { display: flex; flex-direction: column; gap: 8px; }
.skill-row {
  padding: 10px 14px;
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);

  &--off { background: var(--td-bg-color-secondarycontainer); }
}
.skill-name { font-weight: 500; }
.skill-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: var(--app-text-2xs);
  line-height: 1;
  white-space: nowrap;
  color: var(--td-warning-color);
  border: 1px solid var(--td-warning-color-light);
  border-radius: var(--app-radius-xs);

  &--muted {
    color: var(--td-text-color-secondary);
    background: var(--td-bg-color-container-hover);
    border-color: transparent;
  }
}
.skill-desc { margin: 4px 0 0 24px; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.skill-note { margin: 4px 0 0 24px; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.skill-note--warn { color: var(--td-warning-color); }
.skill-actions { display: flex; gap: 14px; margin: 6px 0 0 24px; }
.skill-empty { padding: 24px 0; text-align: center; color: var(--td-text-color-secondary); }
.skill-empty-hint { margin-top: 4px; font-size: var(--app-text-xs); }
.sandbox-control { display: flex; flex-direction: column; gap: 6px; align-items: stretch; }
.sandbox-note { margin: 0; font-size: var(--app-text-xs); line-height: 1.5; color: var(--td-warning-color); }
.sandbox-note--ok { color: var(--td-text-color-secondary); }
.tools-overview {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
  padding: 12px 14px;
  background: var(--td-bg-color-secondarycontainer);
  border-radius: var(--app-radius-lg);
  border: 1px solid var(--td-component-stroke);
}

.tools-overview-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;

  &--preset {
    border-top: 1px dashed var(--td-component-stroke);
    padding-top: 10px;
    justify-content: space-between;
  }
}

.tools-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: var(--app-text-md);
  color: var(--td-text-color-secondary);
  background: var(--td-bg-color-container);
  border-radius: var(--app-radius-pill);
  border: 1px solid var(--td-component-stroke);

  .t-icon {
    color: var(--td-text-color-secondary);
    font-size: var(--app-text-base);
  }

  .tools-status-metric {
    display: inline-flex;
    align-items: baseline;
    gap: 4px;

    strong {
      font-size: var(--app-text-base);
      font-weight: 600;
      color: var(--td-text-color-primary);
    }
  }

  .tools-status-sep {
    color: var(--td-text-color-placeholder);
  }

  &--warn {
    color: var(--td-warning-color);
    background: var(--td-warning-color-1);
    border-color: var(--td-warning-color-light);

    .t-icon {
      color: var(--td-warning-color);
    }
  }
}

// ===== 按组的卡片网格 =====
.tool-groups {
  display: flex;
  flex-direction: column;
  gap: 22px;
  width: 100%;
}

.tool-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 2px;

  .tool-group-bar {
    display: inline-block;
    width: 3px;
    height: 14px;
    border-radius: var(--app-radius-xs);
    background: var(--td-brand-color);
  }

  .tool-group-title {
    font-size: var(--app-text-md);
    font-weight: 600;
    color: var(--td-text-color-primary);
    letter-spacing: 0.2px;
  }

  .tool-group-count {
    min-width: 20px;
    padding: 0 6px;
    font-size: var(--app-text-xs);
    color: var(--td-text-color-secondary);
    background: var(--td-bg-color-secondarycontainer);
    border-radius: var(--app-radius-pill);
    text-align: center;
    line-height: 18px;
  }

  .tool-group-warning {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    font-size: var(--app-text-sm);
    color: var(--td-warning-color);
    background: var(--td-warning-color-1);
    border: 1px solid var(--td-warning-color-light);
    border-radius: var(--app-radius-pill);

    .t-icon {
      font-size: var(--app-text-md);
    }
  }
}

// 不同分组的左侧色条
.tool-group--base .tool-group-bar {
  background: var(--td-gray-color-6);
}

.tool-group--rag .tool-group-bar {
  background: var(--td-brand-color);
}

.tool-group--wiki_read .tool-group-bar {
  background: var(--td-success-color);
}

.tool-group--wiki_edit .tool-group-bar {
  background: var(--td-warning-color);
}

.tool-group--wiki_issue .tool-group-bar {
  background: var(--td-purple-5, #8e56dd);
}

.tool-group--data .tool-group-bar {
  background: var(--td-cyan-6, #09a3b7);
}

// 统一两列网格；小屏退化单列
.tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;

  @media (max-width: 720px) {
    grid-template-columns: 1fr;
  }
}

// ===== 工具卡片（基于 t-checkbox 的 label 结构） =====
.tool-card {
  margin: 0; // 清掉 TDesign checkbox 默认外边距
  padding: 12px 14px;
  background: var(--td-bg-color-container);
  border-radius: var(--app-radius-md);
  border: 1px solid var(--td-component-stroke);
  transition: border-color var(--app-motion-base), background var(--app-motion-base);
  cursor: pointer;
  overflow: hidden;

  &:hover:not(.tool-card--disabled) {
    border-color: var(--td-brand-color);
    background: var(--td-brand-color-1);
  }

  // checkbox 的勾选框 + label 改造
  :deep(.t-checkbox__input) {
    margin-top: 2px;
    flex-shrink: 0;
  }

  :deep(.t-checkbox__label) {
    flex: 1;
    min-width: 0;
    padding-left: 10px;
  }

  &.t-is-checked {
    border-color: var(--td-brand-color);
    background: var(--td-brand-color-1);
  }

  &--disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  &--danger {
    border-color: var(--td-warning-color-light);

    &:hover:not(.tool-card--disabled) {
      border-color: var(--td-warning-color);
      background: var(--td-warning-color-1);
    }

    &.t-is-checked {
      border-color: var(--td-warning-color);
      background: var(--td-warning-color-1);
    }
  }
}

.tool-card-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.tool-card-head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.tool-card-name {
  font-size: var(--app-text-md);
  font-weight: 500;
  color: var(--td-text-color-primary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 0 1 auto;
  min-width: 0;
}

.tool-card-badge {
  flex: 0 0 auto;
  font-size: var(--app-text-2xs);
  line-height: 1;
  padding: 3px 6px;
  color: var(--td-warning-color);
  background: transparent;
  border: 1px solid var(--td-warning-color-light);
  border-radius: var(--app-radius-xs);
  letter-spacing: 0.3px;
}

.tool-card-desc {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tool-card-hint {
  font-size: var(--app-text-xs);
  color: var(--td-warning-color);
  font-style: italic;
  line-height: 1.4;
}

.tool-card--disabled {

  .tool-card-name,
  .tool-card-desc {
    color: var(--td-text-color-placeholder);
  }
}

// ===== 有效工具预览（芯片组）=====
.effective-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 12px;
  background: var(--td-bg-color-container);
  border-radius: var(--app-radius-md);
  border: 1px dashed var(--td-component-stroke);
  min-height: 52px;
  align-items: flex-start;
}

.effective-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  font-size: var(--app-text-sm);
  line-height: 18px;
  color: var(--td-brand-color);
  background: color-mix(in srgb, var(--td-brand-color) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--td-brand-color) 22%, transparent);
  border-radius: var(--app-radius-pill);
  max-width: 100%;
}

.effective-chip-label {
  font-weight: 500;
}

.effective-chip-reason {
  font-size: var(--app-text-xs);
  color: var(--td-warning-color);
  font-style: normal;

  &::before {
    content: "· ";
    color: var(--td-text-color-placeholder);
    margin-right: 2px;
  }
}

.effective-chip--inactive {
  color: var(--td-text-color-placeholder);
  background: var(--td-bg-color-secondarycontainer);
  border-color: var(--td-component-stroke);

  .effective-chip-label {
    text-decoration: line-through;
  }
}

.effective-tools-empty {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-placeholder);
  font-style: italic;
}


.textarea-with-template {
  position: relative;
  width: 100%;
}


.system-prompt-textarea {
  width: 100%;
  font-family: var(--app-font-family-mono);
  font-size: var(--app-text-md);

  :deep(textarea) {
    resize: vertical !important;
    min-height: 200px;
  }
}

// 占位符标签组样式
.placeholder-tags {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--app-text-sm);
  line-height: 1.4;
  overflow-x: auto;
  white-space: nowrap;
  padding-bottom: 4px;

  // 隐藏滚动条但保持可滚动
  scrollbar-width: thin;

  &::-webkit-scrollbar {
    height: 4px;
  }

  &::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.1);
    border-radius: var(--app-radius-xs);
  }

  .placeholder-label {
    color: var(--td-text-color-secondary);
    flex-shrink: 0;
  }

  .placeholder-hint {
    color: var(--td-text-color-placeholder);
    font-size: var(--app-text-xs);
    user-select: none;
    flex-shrink: 0;
  }

  .placeholder-tag {
    display: inline-flex;
    align-items: center;
    padding: 1px 5px;
    border-radius: var(--app-radius-xs);
    font-family: var(--app-font-family-mono);
    font-size: var(--app-text-xs);
    color: var(--td-text-color-primary);
    background-color: var(--td-bg-color-secondarycontainer);
    cursor: pointer;
    transition: all var(--app-motion-base);
    user-select: none;
    border: 1px solid transparent;
    flex-shrink: 0;

    &:hover {
      color: var(--td-brand-color);
      background-color: var(--td-brand-color-light);
      border-color: var(--td-brand-color-focus);
    }

    &:active {
      background-color: var(--td-brand-color-focus);
    }
  }
}


.tool-card-badge--muted {
  background: var(--td-bg-color-container-hover);
  color: var(--td-text-color-secondary);
}
</style>

<!-- Non-scoped: TDesign teleports select popups outside this component. -->
<style lang="less">
.reasoning-level-select-popup {
  padding: 4px;

  .t-select-option {
    height: auto !important;
    padding: 6px 10px;
    border-radius: var(--app-radius-sm);
    margin: 2px 0;
    white-space: normal;
  }
}

.reasoning-level-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.35;
  min-width: 0;

  &__title {
    font-size: var(--app-text-md);
    color: var(--td-text-color-primary);
  }

  &__hint {
    font-size: var(--app-text-sm);
    color: var(--td-text-color-placeholder);
    word-break: break-word;
  }
}

</style>
