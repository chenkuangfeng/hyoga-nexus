<template>
  <!--
    Install a skill from a zip or a remote source (openspec 2026-11-07-skill-evolution, S3). Administrators only; the
    server checks again. A scan stop that an administrator may release is shown with its findings and needs an explicit
    confirmation. Skills with dependencies are built in the background, so the dialog follows the build until it ends.
  -->
  <div class="install-root">
    <t-tabs v-model="tab" class="install-tabs">
      <t-tab-panel value="upload" :label="$t('nexusAgent.skillInstall.tabUpload')">
        <p class="install-hint">{{ $t('nexusAgent.skillInstall.uploadHint') }}</p>
        <div class="install-row">
          <input ref="picker" type="file" accept=".zip,application/zip" class="install-file" @change="onPick">
          <t-button variant="outline" :disabled="busy" @click="picker?.click()">
            <template #icon><t-icon name="upload" /></template>
            {{ $t('nexusAgent.skillInstall.chooseFile') }}
          </t-button>
          <span class="install-file-name">{{ file ? file.name : $t('nexusAgent.skillInstall.noFile') }}</span>
        </div>
        <t-button theme="primary" :disabled="!file || busy" :loading="busy" @click="installUpload(false)">
          {{ $t('nexusAgent.skillInstall.install') }}
        </t-button>
      </t-tab-panel>
      <t-tab-panel value="remote" :label="$t('nexusAgent.skillInstall.tabRemote')">
        <p class="install-hint">{{ $t('nexusAgent.skillInstall.sourceHint') }}</p>
        <t-input v-model="source" :placeholder="$t('nexusAgent.skillInstall.sourcePlaceholder')" :disabled="busy" clearable />
        <t-checkbox v-model="confirmed" class="install-confirm" :disabled="busy">
          {{ $t('nexusAgent.skillInstall.confirmFetch') }}
        </t-checkbox>
        <t-button theme="primary" :disabled="!looksLikeSource(source) || !confirmed || busy" :loading="busy"
          @click="installRemote(false)">{{ $t('nexusAgent.skillInstall.install') }}</t-button>
      </t-tab-panel>
    </t-tabs>

    <!-- A failure the administrator can release after reading the findings. -->
    <div v-if="failure && failure.needsAck" class="install-panel install-panel--warn" role="alert">
      <p class="install-panel-title"><t-icon name="error-circle" /> {{ $t('nexusAgent.skillInstall.ackTitle', { verdict: failure.verdict }) }}</p>
      <ul class="install-findings">
        <li v-for="(finding, index) in failure.findings" :key="index">
          <code>{{ finding.path }}{{ finding.line ? `:${finding.line}` : '' }}</code> {{ finding.rule }}
          <span v-if="finding.excerpt" class="install-excerpt">{{ finding.excerpt }}</span>
        </li>
      </ul>
      <t-checkbox v-model="acknowledged">{{ $t('nexusAgent.skillInstall.ackConfirm') }}</t-checkbox>
      <t-button theme="warning" size="small" :disabled="!acknowledged || busy" @click="retryWithAck">
        {{ $t('nexusAgent.skillInstall.installAnyway') }}
      </t-button>
    </div>
    <t-alert v-else-if="failure" theme="error" class="install-alert"
      :message="$t(failureKey(failure.code), { detail: failure.detail, code: failure.code })" />

    <!-- The result, and the dependency build while it runs. -->
    <div v-if="result" class="install-panel" role="status">
      <p class="install-panel-title">
        <t-icon :name="buildFailed ? 'close-circle' : 'check-circle'" />
        {{ $t('nexusAgent.skillInstall.installed', { name: result.skill, version: result.version }) }}
      </p>
      <p v-if="result.notes.length" class="install-hint">{{ result.notes.join(' · ') }}</p>
      <template v-if="build">
        <p class="install-state">
          <t-loading v-if="build.build_state === 'installing'" size="small" />
          {{ build.build_state === 'installing' ? $t('nexusAgent.skillInstall.buildRunning')
            : build.build_state === 'ready' ? $t('nexusAgent.skillInstall.buildReady')
            : $t('nexusAgent.skillInstall.buildFailed', { reason: build.build_error || '' }) }}
        </p>
        <pre v-if="build.build_log" class="install-log">{{ build.build_log }}</pre>
        <div class="install-row">
          <t-button v-if="build.build_state === 'installing'" size="small" variant="outline" @click="stopBuild">
            {{ $t('nexusAgent.skillInstall.stop') }}
          </t-button>
          <t-button v-if="build.build_state === 'failed'" size="small" variant="outline" @click="retryBuild">
            {{ $t('nexusAgent.skillInstall.retry') }}
          </t-button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  getSkillInstallStatus, installRemoteSkill, reinstallSkill, stopSkillInstall, uploadSkillBundle,
  type SkillInstallResult, type SkillInstallStatus,
} from '@nexus-web/core/api/nexus-agents'
import { failureKey, isFinishedBuild, looksLikeSource, parseInstallFailure, type InstallFailure } from './skillInstall'

const props = defineProps<{ tenantId: string, sandboxProfile?: string }>()
const emit = defineEmits<{ (event: 'installed'): void }>()
useI18n()

const POLL_MS = 3000
const tab = ref<'upload' | 'remote'>('upload')
const picker = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const source = ref('')
const confirmed = ref(false)
const acknowledged = ref(false)
const busy = ref(false)
const failure = ref<InstallFailure | null>(null)
const result = ref<SkillInstallResult | null>(null)
const build = ref<SkillInstallStatus | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined

let epoch = 0
let disposed = false
const active = (current: number) => !disposed && current === epoch

const buildFailed = computed(() => build.value?.build_state === 'failed')

function stopPolling() {
  if (timer !== undefined) clearTimeout(timer)
  timer = undefined
}

function reset() {
  epoch++
  stopPolling()
  failure.value = null
  result.value = null
  build.value = null
  acknowledged.value = false
}

function onPick(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  reset()
}

async function run(action: () => Promise<SkillInstallResult>) {
  if (busy.value || disposed) return
  reset()
  const current = epoch
  busy.value = true
  try {
    const installed = await action()
    if (!active(current)) return
    result.value = installed
    emit('installed')
    if (result.value.build_state === 'installing') await follow()
  } catch (error) {
    if (active(current)) failure.value = parseInstallFailure(error)
  } finally {
    if (active(current)) busy.value = false
  }
}

const installUpload = (acknowledge: boolean) => run(() =>
  uploadSkillBundle(props.tenantId, file.value as File, { sandboxProfile: props.sandboxProfile, acknowledge }))
const installRemote = (acknowledge: boolean) => run(() =>
  installRemoteSkill(props.tenantId, source.value.trim(), { confirm: confirmed.value, acknowledge }))

function retryWithAck() {
  return tab.value === 'upload' ? installUpload(true) : installRemote(true)
}

/** Poll the build until it ends; a closed dialog or a new install stops the loop. */
async function follow() {
  const request = epoch, tenant = props.tenantId
  if (disposed) return
  const current = result.value
  if (!current) return
  try {
    const status = await getSkillInstallStatus(tenant, current.skill, current.version)
    if (!active(request) || result.value !== current) return
    build.value = status
  } catch (error) {
    if (active(request)) failure.value = parseInstallFailure(error)
    return
  }
  if (isFinishedBuild(build.value.build_state)) {
    emit('installed')
    return
  }
  timer = setTimeout(() => { if (active(request) && result.value === current) void follow() }, POLL_MS)
}

async function stopBuild() {
  if (!result.value || disposed) return
  const current = epoch
  try {
    await stopSkillInstall(props.tenantId, result.value.skill, result.value.version)
    if (!active(current)) return
    stopPolling()
    await follow()
  } catch (error) {
    if (active(current)) MessagePlugin.error(parseInstallFailure(error).message)
  }
}

async function retryBuild() {
  if (!result.value || disposed) return
  const current = epoch
  try {
    await reinstallSkill(props.tenantId, result.value.skill, result.value.version, props.sandboxProfile)
    if (!active(current)) return
    stopPolling()
    await follow()
  } catch (error) {
    if (active(current)) MessagePlugin.error(parseInstallFailure(error).message)
  }
}

watch(() => props.tenantId, () => { reset(); busy.value = false; file.value = null; source.value = '' }, { flush: 'sync' })
onBeforeUnmount(() => { disposed = true; epoch++; stopPolling() })
</script>

<style scoped>
.install-tabs { margin-bottom: 12px; }
.install-hint { margin: 0 0 8px; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.install-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.install-file { display: none; }
.install-file-name { font-size: var(--app-text-sm); color: var(--td-text-color-secondary); word-break: break-all; }
.install-confirm { display: flex; margin: 10px 0 12px; }
.install-alert { margin-top: 12px; }
.install-panel { margin-top: 12px; padding: 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--td-radius-medium); }
.install-panel--warn { border-color: var(--td-warning-color); }
.install-panel-title { margin: 0 0 8px; display: flex; align-items: center; gap: 6px; font-weight: 600; }
.install-findings { margin: 0 0 8px; padding-left: 18px; font-size: var(--app-text-xs); line-height: 1.6; max-height: 160px; overflow: auto; }
.install-excerpt { display: block; color: var(--td-text-color-secondary); font-family: var(--app-font-family-mono); word-break: break-all; }
.install-state { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; font-size: var(--app-text-sm); }
.install-log { margin: 0 0 8px; padding: 8px; max-height: 200px; overflow: auto; font-size: var(--app-text-xs); line-height: 1.5; background: var(--td-bg-color-secondarycontainer); border-radius: var(--td-radius-default); white-space: pre-wrap; word-break: break-all; }
</style>
