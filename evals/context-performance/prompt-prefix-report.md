# 提示缓存前缀优化验证

## 范围

本次按用户确认实施工作锚点尾置默认值、检查点迁出 system、常驻画像与目录稳定排序、工具 schema 确定性序列化及原生 Anthropic 缓存断点。不修改历史工具结果窗口、压缩阈值、逐次授权、源消息或已发布智能体版本。为模型参考资料添加来源标记，确保确定性裁剪和模型摘要仍保护最新真实用户问题。

## 离线结果

运行 `uv run --locked python evals/context-performance/prompt_prefix_benchmark.py`，复用既有 20 个固定会话场景。20/20 场景在工作锚点尾置后保留更长的共同消息前缀；原始消息完整保留。明细见 [JSON](prompt-prefix-results.json)。

这是序列化消息的共同前缀字节数对比，未包含供应商内部工具模板、分词、缓存有效期、路由或最小长度判断；不等于缓存命中率，也不证明回答质量或实际延迟改善。

## 自动验证

在 `git archive HEAD` 的隔离副本中覆盖本任务暂存内容，最终执行缓存、协议、上下文、压缩边界、权限、工具、快照与记忆 API 回归：297 passed。扩大范围时另有 7 个失败，全部位于 `tests/test_memory_evolution_stage2.py`；恢复未修改的 HEAD 记忆规则后同模块仍为 7 failed / 4 passed，确认是既有测试替身未跟随事实身份参数、旧画像默认值及旧主题合并约定更新，并非本次引入。未混入其他正在实施的记忆界面/类别调整。

新增回归验证：各协议工具与 schema 顺序一致；Anthropic 至多四个 ephemeral 断点、source 对象不变、缓存 usage 口径不变；其他协议无 Anthropic 专属字段；默认尾置及显式旧布局；检查点为历史后 user 参考；目录不随置顶顺序变化但权限过滤结果立即生效；使用次数不改变常驻条目集合及顺序，禁用仍立即生效。

core、runtimes、platform、memory 的 sdist/wheel 构建均通过。未配置/调用真实供应商进行本批对比，不报告真实 cached_tokens、首字延迟或语义质量通过。

## 生效及在线验收

缺省行为采用 `working_memory_tail=True`。旧已发布版本显式保存 `False` 时保留原行为，需通过既有智能体编辑/发布流程启用，不修改不可变版本。原生 Anthropic Messages 请求自动携带官方 ephemeral 断点；Chat/Responses 不猜测中转服务的缓存扩展。

线上应固定模型、工具集合、语料与输出约束，分别比较旧显式布局和尾置布局。统计实际 cache_read、输入量、首字延迟与任务质量；Chat/Responses 的输入分母为 input，Anthropic 为 input+cache_read+cache_creation。无 usage 的请求标为未知，不当成 0% 命中。真实模型与 PostgreSQL 等原提案剩余验收尚未完成，因此原 OpenSpec 变更继续保持活动状态。
