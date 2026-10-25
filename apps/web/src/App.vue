<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import OverviewView from './views/OverviewView.vue'
import ConversationView from './views/chat/ConversationView.vue'
import NativeSettingsView from './views/settings/NativeSettingsView.vue'
import ModelSettingsView from './views/settings/ModelSettingsView.vue'
const currentPage = () => location.hash === '#native-settings' ? 'native-settings' : location.hash === '#settings' ? 'settings' : location.hash === '#overview' ? 'overview' : 'chat'
const page = ref(currentPage())
function select(value: string) { page.value = value; location.hash = value }
const hashChanged = () => { page.value = currentPage() }
window.addEventListener('hashchange', hashChanged)
onBeforeUnmount(() => window.removeEventListener('hashchange', hashChanged))
</script>
<template>
  <nav class="app-navigation" aria-label="主导航">
    <button type="button" :aria-current="page === 'chat' ? 'page' : undefined" @click="select('chat')">对话工作台</button>
    <button type="button" :aria-current="page === 'settings' ? 'page' : undefined" @click="select('settings')">用户设置</button>
    <button type="button" :aria-current="page === 'native-settings' ? 'page' : undefined" @click="select('native-settings')">Native 与记忆</button>
    <button type="button" :aria-current="page === 'overview' ? 'page' : undefined" @click="select('overview')">平台能力</button>
  </nav>
  <ConversationView v-if="page === 'chat'" /><ModelSettingsView v-else-if="page === 'settings'" /><NativeSettingsView v-else-if="page === 'native-settings'" /><OverviewView v-else />
</template>
