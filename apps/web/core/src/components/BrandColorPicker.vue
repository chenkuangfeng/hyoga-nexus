<script setup lang="ts">
/** 两个应用共享员工常规设置的主题色色块，使用同一份用户偏好与全局色阶。 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { BRAND_COLORS, BRAND_COLOR_KEYS, useBrandColor, type BrandColorKey } from '../composables/brandColor'
const { t } = useI18n(), { currentBrand, setBrandColor } = useBrandColor()
const root = ref<HTMLElement | null>(null)
function navigate(event: KeyboardEvent, key: BrandColorKey) {
  if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) return
  event.preventDefault()
  const direction = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1
  const index = (BRAND_COLOR_KEYS.indexOf(key) + direction + BRAND_COLOR_KEYS.length) % BRAND_COLOR_KEYS.length
  setBrandColor(BRAND_COLOR_KEYS[index]!); root.value?.querySelectorAll('button')[index]?.focus()
}
</script>
<template><div ref="root" class="brand-swatches" role="radiogroup" :aria-label="t('theme.brandColor')"><button v-for="key in BRAND_COLOR_KEYS" :key="key" type="button" role="radio" class="brand-swatch" :class="{ 'is-active': key === currentBrand }" :style="{ backgroundColor: BRAND_COLORS[key] }" :aria-checked="key === currentBrand" :tabindex="key === currentBrand ? 0 : -1" :aria-label="t(`theme.brandColors.${key}`)" :title="t(`theme.brandColors.${key}`)" @click="setBrandColor(key)" @keydown="navigate($event, key)" /></div></template>
<style scoped lang="less">
.brand-swatches {
  display: grid;
  grid-template-columns: repeat(6, 28px);
  gap: 10px 8px;
  width: 280px;
  justify-content: end;
}

.brand-swatch {
  position: relative;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
  transition: transform 0.15s ease, box-shadow 0.15s ease;

  &:hover {
    transform: scale(1.08);
  }

  &:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 2px;
  }

  // 选中态：白色内圈 + 外圈描边，并在中央画一个白色对勾
  &.is-active {
    box-shadow: 0 0 0 2px var(--td-bg-color-container), 0 0 0 4px var(--td-brand-color);

    &::after {
      content: '';
      position: absolute;
      left: 10px;
      top: 6px;
      width: 5px;
      height: 10px;
      border: solid #fff;
      border-width: 0 2px 2px 0;
      transform: rotate(45deg);
    }
  }
}


.brand-swatches { max-width: 100%; }
@media(prefers-reduced-motion:reduce) { .brand-swatch { transition: none; } }
</style>
