<script setup lang="ts">
import { useAuthStore } from '@nexus-web/core/stores/auth'
const auth = useAuthStore()
</script>
<template>
  <main class="admin-entry">
    <template v-if="auth.currentEntries.includes('admin')">
      <h1>{{ auth.currentTenantName }} · 企业管理</h1>
      <t-alert theme="info" message="管理后台正在迁移，管理页面尚未接入。" />
    </template>
    <template v-else>
      <h1>无权访问企业管理后台</h1>
      <p>当前企业未授予你管理入口权限。</p>
    </template>
    <t-link href="/" theme="primary">进入员工工作台</t-link>
  </main>
</template>
<style scoped>
.admin-entry { max-width: 960px; margin: 64px auto; padding: 24px; }
.admin-entry :deep(.t-alert) { margin-bottom: 24px; }
</style>
