# 设计

聊天页顶部仅显示靠左的三个标签，会话头部标题和快捷操作从该页移除。轨迹表由独立持久化模型请求记录驱动，不读取 RunEvent。Runtime 在请求发出前保存模型输入和工具目录快照，请求结束后按同一记录 ID 补写输出、供应商 usage、状态和 Run 累计 token；记录只允许从 running 转为一个终态。开始和结束写入都校验 Run 租约。API 先使用现有 Run 授权再读取记录。前端按请求序号展示紧凑列表，点击一行打开详情检查器。当前正在执行的 Run 通过轻量轮询读取新记录，完成后停止轮询。历史 Run 没有新表记录时显示明确空状态，不从事件推测伪记录。

实现参考 DeepSeek Harness `packages/client/ui-trajectory/src/client/TrajectoryTable.tsx` 的两列事件/内容表、可键盘选择的记录行与点击检查器，以及 `trajectory-record.ts` 的类型化记录详情。Nexus 使用数据库模型请求快照而不是将 RunEvent 直接投影为轨迹行；不复制参考项目的完整虚拟化时间轴。
