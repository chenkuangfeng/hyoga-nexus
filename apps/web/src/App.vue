<script setup lang="ts">
import { ref } from 'vue'
import OverviewView from './views/OverviewView.vue'
import ConversationView from './views/chat/ConversationView.vue'
const page = ref(location.hash === '#overview' ? 'overview' : 'chat')
function select(value: string) { page.value = value; location.hash = value }
window.addEventListener('hashchange', () => { page.value = location.hash === '#overview' ? 'overview' : 'chat' })
</script>
<template>
  <nav class="app-navigation" aria-label="主导航">
    <button type="button" :aria-current="page === 'chat' ? 'page' : undefined" @click="select('chat')">对话工作台</button>
    <button type="button" :aria-current="page === 'overview' ? 'page' : undefined" @click="select('overview')">平台能力</button>
  </nav>
  <ConversationView v-if="page === 'chat'" /><OverviewView v-else />
</template>
