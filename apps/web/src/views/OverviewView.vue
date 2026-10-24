<script setup lang="ts">
import { ref, onMounted } from 'vue'
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
  } catch { error.value = '无法连接平台 API，请确认后端已启动。' }
  finally { loading.value = false }
}
const titles: Record<string, string> = { runtimes: '智能体运行框架', channels: '消息渠道', applications: '业务应用' }
onMounted(load)
</script>

<template>
  <main>
    <header><div><p class="eyebrow">HYOGA NEXUS / 织枢</p><h1>智能体工作台</h1></div><el-button :loading="loading" @click="load">刷新状态</el-button></header>
    <p class="intro">连接模型、技能与业务。观澜是平台的首个股票研究应用。</p>
    <el-alert title="项目初始化阶段：以下能力均待接入。" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="error" />
    <el-skeleton v-if="loading" :rows="6" animated />
    <section v-else class="grid" aria-label="平台能力">
      <el-card v-for="(items, key) in groups" :key="key" shadow="never">
        <template #header><h2>{{ titles[key] || key }}</h2></template>
        <div v-for="item in items" :key="item.name" class="capability"><span>{{ item.name }}</span><el-tag type="info">待接入</el-tag></div>
      </el-card>
    </section>
  </main>
</template>
