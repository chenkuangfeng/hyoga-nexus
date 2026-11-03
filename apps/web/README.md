# Web 工作台（apps/web）

前端代码直接复制自 WeKnora 固定版本 `e1f9a6166` 的 `frontend/`（Vue 3、TypeScript、TDesign、pinia、vue-router、vue-i18n、axios）。界面与前端技术架构照抄，后端接口在后续阶段按 Nexus 的 Python API 对接，尚未切换。

## 当前状态

- 已复制：`src/`、`public/`、`scripts/`、`index.html`、`embed.html`、`env.d.ts`、TypeScript 与 Vite 配置、`package.json`。
- 未复制：WeKnora 的部署文件（Dockerfile、nginx 配置、docker-entrypoint.sh）、npm 的 `package-lock.json`、WeKnora 的 `tests/` 与根目录的 mcpProxy 测试。
- 旧的 Element Plus 版本的界面已删除（见 git 历史）。
- `src/` 中的页面、接口调用和文案仍是 WeKnora 的内容，需要按 `openspec/changes/2026-11-03-enterprise-personal-spaces/tasks.md` 逐组改为 Nexus 的接口与范围。

## 使用

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

`pnpm build` 在内存较小的机器上会被系统 OOM 终止（WeKnora 依赖较重，转换阶段占用超过 2GB）。需要在内存充足的机器或 CI 上构建。

## 文档

- [需求](docs/requirements.md)
- [设计](docs/design.md)
