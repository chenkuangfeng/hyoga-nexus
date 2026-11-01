# 目录用途

界面文案（中文 `zh-CN` 与英文 `en-US`）。

- `index.ts`：创建 vue-i18n 实例，决定初始语言（localStorage `nexus_locale`，其次浏览器语言，默认中文），提供 `setLocale`。
- `locales/zh-CN.ts`：参考语言，定义消息结构。
- `locales/en-US.ts`：使用 `Messages` 类型约束，缺少或多出的 key 会在 `vue-tsc` 阶段报错。

约定：
- 模板中用 `$t('key')`，脚本中用 `i18n.global.t('key')`（composable 与 API 层）。
- key 按区域分组（`shell.*`、`chat.*`、`errors.*`、各页面名称）。不要在组件中硬编码用户可见文字；品牌字样与语言名本身除外。
- API 层的报错使用 `errors.*`；后端返回的错误码映射到 `chat.errors.*` 时缺省回退到 `chat.retryHint`。
