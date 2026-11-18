<script setup lang="ts">
/** WeKnora e1f9a6166 resource-card.less 的资源卡片；动作由宿主按真实权限提供。 */
defineProps<{ title: string; description?: string; icon?: string; interactive?: boolean }>()
const emit = defineEmits<{ (event: 'open'): void }>()
</script>
<template>
  <article class="resource-directory-card" :class="{ interactive }" :role="interactive ? 'button' : undefined" :tabindex="interactive ? 0 : undefined" @click="interactive && emit('open')" @keydown.enter.self.prevent="interactive && emit('open')" @keydown.space.self.prevent="interactive && emit('open')">
    <div class="card-header"><div class="card-header-left"><span class="resource-avatar"><t-icon :name="icon || 'folder'" size="16px" /></span><h3 class="card-title" :title="title">{{ title }}</h3></div><div @click.stop @keydown.stop><slot name="actions" /></div></div>
    <div class="card-content"><p class="card-description">{{ description || '—' }}</p></div>
    <div class="card-bottom" @click.stop @keydown.stop><slot /></div>
  </article>
</template>
<style scoped lang="less">
@import (reference) '../styles/resource-card.less';
.resource-directory-card { .resource-card(); .resource-card-quiet(); }
.resource-avatar { display: grid; place-items: center; width: 20px; height: 20px; border-radius: var(--app-radius-md); color: var(--td-text-color-secondary); flex-shrink: 0; }
.interactive { cursor: pointer; } .interactive:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
h3, p { margin: 0; }
.card-description { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
