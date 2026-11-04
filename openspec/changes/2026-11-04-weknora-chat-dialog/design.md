# 设计：WeKnora 风格对话页接入 Nexus 会话与 Run

> 状态：已确认（与 proposal.md 一并确认）。

## 1. 参考映射

| WeKnora（e1f9a6166） | Nexus 当前状态 | 处理 |
| --- | --- | --- |
| `views/chat/index.vue` | 已复制，只在助手面板使用 | 作为主页面骨架，替换数据层 |
| `components/Input-field.vue` | 已复制，依赖 `api/chat`、知识库选择 | 去掉知识库与附件依赖，保留输入、发送、停止、排队、steer |
| `views/chat/components/AgentStreamDisplay.vue` | 已复制，与参考相差约 22 行 | 以参考版本为准，事件源改为 Run 事件 |
| `views/chat/components/ToolResultRenderer.vue`、`ToolApprovalCard.vue` | 已复制，有 Nexus 专用变体 | 保留 Nexus 变体（如 `NexusDocResult`），其余对齐参考 |
| `composables/useChatStreamHandler.ts` | 未接入 | 用 Run 事件 + `nativeRunState.ts` 替代 WeKnora 的 SSE 处理 |
| `stores/chatResources.ts` | 未接入 | 评估后只保留会话列表所需部分 |

## 2. 数据层

- 会话：`listSessions` / `createSession` / `getSession` 使用 `api/native-runs.ts` 已有的封装，并补充重命名与删除（如后端支持，否则隐藏）。
- 消息：历史消息来自 `GET .../messages`，映射为 WeKnora 消息模型（`role`、`content`、`events`、`created_at`）。映射函数独立成模块，便于测试。
- Run：提交返回 `RunView`；事件订阅沿用 native-run-workbench 的 SSE 客户端；按 `sequence` 去重，`Last-Event-ID` 续读。

## 3. 路由

- `/platform/creatChat`：新建页；选择已发布智能体后创建会话并跳转 `/platform/chat/:chatid`。
- `/platform/chat/:chatid`：会话页；会话不存在或无权限时显示错误状态，不泄漏其他空间的信息。
- `/platform/knowledge-bases/:kbId/creatChat`：重定向到 `/platform/creatChat`（待确认决定第 3 项）。
- `/platform/native`、`/platform/native/sessions/:sessionId`：重定向到对应会话页（待确认决定第 4 项）。

## 4. 与参考实现的已知偏离

以下偏离在实施时逐条记录到 `apps/web/docs/design.md`：

- 知识库、引用、附件、推荐追问、后台任务：v1 不提供（见 proposal 第 4 项）。
- 会话 ID 与路由参数使用 Nexus UUID，不使用 WeKnora 的会话格式。
- 权限判断全部交给服务端；前端隐藏按钮只作为体验优化。

## 5. 测试

- 纯函数与映射：消息映射、事件去重、排队与 steer 状态（单元测试）。
- 组件：输入区的发送/停止/排队、告警条的三个操作、会话页的加载/空/错误状态。
- 样式守卫与 i18n 审计沿用现有测试。
- `pnpm build` 与浏览器用例需要在内存充足的环境执行（本机因内存不足无法完成完整构建）。
