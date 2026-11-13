<template><t-config-provider><router-view /></t-config-provider></template>
<style>
html { color-scheme: light dark; }
body, html, #app {
  width: 100%; height: 100%; margin: 0; padding: 0;
  font-size: var(--app-text-base); font-family: var(--app-font-family);
  -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  color: var(--td-text-color-primary); background: var(--td-bg-color-page);
}
* { box-sizing: border-box; }
</style>
