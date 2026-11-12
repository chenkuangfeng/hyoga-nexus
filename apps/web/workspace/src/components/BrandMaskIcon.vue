<template>
  <!--
    品牌色图标。绿色 SVG 文件内的颜色是写死的，<img> 无法被 CSS 变量覆盖，
    所以这里把 SVG 当作蒙版（mask），背景色取全局品牌色 --td-brand-color，
    从而跟随设置里的主题色。尺寸、间距等由调用方通过 class 决定。
  -->
  <span class="brand-mask-icon" :style="maskStyle" aria-hidden="true" />
</template>

<script setup lang="ts">
import { computed } from 'vue'

/**
 * 用法：<BrandMaskIcon name="organization-green.svg" class="my-icon" />
 * name 为 src/assets/img 下的文件名，必须是已存在的 *-green.svg 资源，
 * 否则渲染为空白（不会报错，便于发现图标缺失时检查文件名）。
 */
const props = defineProps<{ name: string }>()

// 构建时收集所有绿色图标的 URL，按文件名索引，避免在模板里拼接动态 import
const greenIconUrls: Record<string, string> = Object.fromEntries(
  Object.entries(
    import.meta.glob('../assets/img/*-green.svg', {
      eager: true,
      query: '?url',
      import: 'default',
    }) as Record<string, string>,
  ).map(([path, url]) => [path.split('/').pop() as string, url]),
)

const maskStyle = computed(() => {
  const url = greenIconUrls[props.name]
  return url ? { '--icon-url': `url("${url}")` } : undefined
})
</script>

<style lang="less">
// 默认尺寸取 1em，可被调用方 class 覆盖；:where 使其特异性为 0，避免压过调用方样式
:where(.brand-mask-icon) {
  display: inline-block;
  flex-shrink: 0;
  width: 1em;
  height: 1em;
  background-color: var(--td-brand-color);
  -webkit-mask: var(--icon-url) no-repeat center / contain;
  mask: var(--icon-url) no-repeat center / contain;
}
</style>
