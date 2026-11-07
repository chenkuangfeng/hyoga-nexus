# 沙箱设计

模型只看到两个虚拟根：`/workspace`（可读写）和 `/outputs`（交付物）。宿主路径由后端映射，不出现在任何工具结果里。

| 模块 | 职责 |
| --- | --- |
| `settings` | 读取 `[sandbox]`；非法值只报键名，不回显值 |
| `paths` | 虚拟路径解析：拒绝 `..`、NUL、其他根；按真实路径判断符号链接是否越界 |
| `files` | `HostFileStore`：宿主目录上的文件读、分页读、原子写、唯一匹配编辑、搜索、配额、产物收集 |
| `backends/docker` | 每个（租户，会话）一个容器；`docker exec` 执行；`timeout` 带进程组；取消时按命令标记杀进程组 |
| `backends/local` | 开发替身，不隔离 |
| `backends/output` | 输出按头 70% 加尾 30% 保留 |
| `session` | `SandboxSession`：把文件存储与执行器合成工具使用的 `SandboxSessionPort`（契约在 `nexus_core.sandbox`） |
| `manager` | 租约：目录、容器名、空闲与孤儿回收 |
| `acceptance` | 隔离验收：12 项真实探测，报告按后端、镜像与限制的指纹失效 |

## 容器参数

非 root（服务进程为 root 时用 65534），`--cap-drop ALL`，`no-new-privileges`，只读根文件系统，`/tmp` 为 tmpfs，默认 `--network none`，`--cpus`、`--memory` 与同值 `--memory-swap`、`--pids-limit`，`--pull never`，只挂载本会话的两个目录，不传服务进程环境变量。

## 验收项

connectivity、user、network、time_limit、output_limit、memory_limit、process_limit、tenant_isolation、path_escape、environment、cancellation、cleanup_and_residue。`local` 后端在任何探测运行前被拒绝，因为内存与进程数探测本身带有破坏性。

## 已知限制

- 路径检查与打开之间存在符号链接替换的竞态；边界由容器提供，不由路径检查提供。
- 验收报告保存在 `workspace_root/acceptance.json`，多机部署时各机各自验收。迁移到数据库表需要等仓库中迁移链稳定后进行。
- 配额以目录总大小估算，每次写入遍历一次工作区。
