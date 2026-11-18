<script setup lang="ts">
/** 可配置编辑容器。仅管理端接受展示偏好，保留原表单的确认、取消及关闭事件。 */
import { computed, useAttrs } from 'vue'
import { useEditorPresentation } from '../../composables/useEditorPresentation'
defineOptions({ inheritAttrs: false })
const props = defineProps<{ visible: boolean; header?: string; width?: string }>()
const emit = defineEmits<{ (event: 'close'): void; (event: 'confirm'): void; (event: 'update:visible', value: boolean): void }>()
const attrs = useAttrs()
const { mode } = useEditorPresentation(() => props.visible, () => emit('close'))
const tag = computed(() => mode.value === 'drawer' ? 't-drawer' : 't-dialog')
const pass = computed(() => mode.value === 'drawer' ? { ...attrs, size: props.width || '640px', placement: 'right' } : { ...attrs, width: mode.value === 'route' ? '100%' : props.width })
</script>
<template>
  <component :is="tag" v-bind="pass" :visible="visible" :header="header" :class="{ 'editor-dialog-route': mode === 'route' }" @close="emit('close')" @confirm="emit('confirm')" @update:visible="emit('update:visible', $event)">
    <template v-for="(_, name) in $slots" #[name]="slotProps"><slot :name="name" v-bind="slotProps || {}" /></template>
  </component>
</template>
<style>
@import '../../styles/editor-presentation.css';
</style>
