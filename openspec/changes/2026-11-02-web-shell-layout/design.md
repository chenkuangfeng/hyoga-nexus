# 设计：Web 工作台布局

## 结构

```
App.vue
├── AppShell.vue          外壳：侧栏 + 主内容区 + 响应式状态
│   ├── AppSidebar.vue    Logo、搜索入口、空间选择器、分组导航、会话列表（对话组）、用户区
│   └── <slot>            当前页面
└── （页面组件不再放置顶部导航与空间下拉）
```

- `AppShell` 持有侧栏的展开状态（localStorage 记住），负责三档断点。
- 导航项由一份静态表定义：`{ group, page, label, visible(user) }`。`visible` 决定平台管理员入口。
- 当前页由 vue-router 决定（`route.path`），`aria-current="page"` 标记。

## 空间选择器

- 放在侧栏顶部，读取现有的 `tenants` 列表（`api/chat.ts`），切换后写入全局的当前空间，页面通过同一个来源读取。
- 切换空间时当前页保留；页面内的数据请求以当前空间重新加载。

## 样式

- 复用现有 CSS 变量；新增的仅有侧栏宽度（展开 240px、折叠 56px）与断点变量。
- 颜色仍来自现有变量，不引入新的配色。

## 测试影响

- `tests/web/*.mjs` 中依赖顶部导航按钮文本的选择器需要改为侧栏导航项。
- 对话页的会话列表移入侧栏后，相关测试的选择器需要同步修改。

## 决定结论（2026-11-02）

1. 迁移到 vue-router（history 模式）；旧 hash 链接由 `redirectLegacyHash` 改写。后端 WeCom/OIDC 与登录的重定向改为路径（`/chat`、`/login?error=`、`/personal/account?wecom=`）。
2. 空间选择器在侧栏顶部，写入 `stores/workspace.ts`；各页面不再放置空间下拉（管理员的会话查询和组织绑定目标仍按各自语义保留选择器）。
3. 会话列表在侧栏“会话”分组，当前会话由 `/chat/:sessionId` 决定；对话页只保留智能体选择与新建会话。
4. 分组按提案的四组。
