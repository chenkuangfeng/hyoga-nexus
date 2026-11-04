<template>
  <!-- 独立对话页的路由入口：/platform/creatChat（欢迎态）与 /platform/chat/:chatid。 -->
  <NexusChatPage :session-id="chatId" allow-agent-select @session-created="openSession" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NexusChatPage from './NexusChatPage.vue'

const route = useRoute()
const router = useRouter()
const chatId = computed(() => String(route.params.chatid ?? ''))

/** 欢迎态创建会话后改写地址；对话页识别到是自己刚创建的会话，不会重新加载。 */
const openSession = (id: string) => {
  void router.replace(`/platform/chat/${id}`)
}
</script>
