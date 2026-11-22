<template>
  <div class="kb-document-layout">
    <slot name="folders" />
    <div class="kb-document-layout__content"><slot /></div>
  </div>
</template>

<style scoped>
.kb-document-layout { display: flex; flex: 1; min-height: 0; min-width: 0; }
.kb-document-layout__content { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; }
@media (max-width: 1000px) {
  .kb-document-layout { flex-direction: column; }
  .kb-document-layout :deep(.kb-folder-tree) {
    width: 100%;
    max-height: 200px;
    padding: 0 0 12px;
    margin: 0 0 12px;
    border-inline-end: 0;
    border-bottom: 1px solid var(--td-component-stroke);
  }
  .kb-document-layout :deep(.kb-folder-tree__header) { height: 28px; padding-bottom: 4px; }
}
</style>
