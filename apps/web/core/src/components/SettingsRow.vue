<script setup lang="ts">
/** 设置页标准行：左侧标签/说明，右侧控件，版式与常规设置共用。 */
defineProps<{ label: string; description?: string }>()
</script>
<template>
  <div class="setting-row">
    <div class="setting-info"><span class="setting-label">{{ label }}</span><p v-if="description" class="desc">{{ description }}</p><slot name="description" /></div>
    <div class="setting-control"><slot /></div>
  </div>
</template>
<style scoped lang="less">
@import (reference) '../styles/settings-section.less';
.setting-row { .setting-row(); }
.setting-info { .setting-info(); }
.setting-control { .setting-control(); }
@media (max-width: 880px) {
  .setting-row { flex-wrap: wrap; }
  .setting-info { max-width: 100%; flex-basis: 100%; }
  .setting-control { min-width: 0; width: 100%; justify-content: flex-start; }
}
</style>
