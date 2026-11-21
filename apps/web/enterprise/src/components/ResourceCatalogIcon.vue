<script setup lang="ts">
/** 使用 WeKnora 原有目录图标并继承管理端主题颜色。 */
import { computed } from 'vue'
import agentIcon from '@nexus-web/core/assets/img/agent.svg'
import knowledgeIcon from '@nexus-web/core/assets/img/zhishiku.svg'

const props = defineProps<{ kind: 'agent' | 'knowledge'; size: number }>()
const iconStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  maskImage: `url("${props.kind === 'agent' ? agentIcon : knowledgeIcon}")`,
}))
</script>

<template>
  <span class="resource-catalog-icon" :style="iconStyle" aria-hidden="true" />
</template>

<style scoped>
.resource-catalog-icon {
  display: inline-block;
  flex-shrink: 0;
  background: currentColor;
  mask-position: center;
  mask-repeat: no-repeat;
  mask-size: contain;
}
</style>
