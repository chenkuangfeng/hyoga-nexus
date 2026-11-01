<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { i18n } from '../i18n'
type Capability = { name: string; status: string }
const groups = ref<Record<string, Capability[]>>({})
const loading = ref(true)
const error = ref('')
async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/capabilities')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    groups.value = await response.json()
  } catch { error.value = i18n.global.t('overview.fetchFailed') }
  finally { loading.value = false }
}
const titles: Record<string, () => string> = { runtimes: () => i18n.global.t('overview.groups.runtimes'), channels: () => i18n.global.t('overview.groups.channels'), applications: () => i18n.global.t('overview.groups.applications') }
onMounted(load)
</script>

<template>
  <main>
    <header><div><p class="eyebrow">HYOGA NEXUS / 织枢</p><h1>{{ $t('overview.heading') }}</h1></div><el-button :loading="loading" @click="load">{{ $t('overview.refresh') }}</el-button></header>
    <p class="intro">{{ $t('overview.intro') }}</p>
    <el-alert :title="$t('overview.alert')" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="error" />
    <el-skeleton v-if="loading" :rows="6" animated />
    <section v-else class="grid" :aria-label="$t('overview.capabilities')">
      <el-card v-for="(items, key) in groups" :key="key" shadow="never">
        <template #header><h2>{{ titles[key] ? titles[key]() : key }}</h2></template>
        <div v-for="item in items" :key="item.name" class="capability"><span>{{ item.name }}</span><el-tag :type="item.status === 'available' ? 'success' : 'info'">{{ item.status === 'available' ? $t('overview.available') : item.status === 'requires_configuration' ? $t('overview.needsConfig') : $t('overview.notConnected') }}</el-tag></div>
      </el-card>
    </section>
  </main>
</template>
