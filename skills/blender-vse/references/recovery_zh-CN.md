# 故障恢复与续作

[English version](recovery.md)

只读取与结构化错误码对应的分支。保留原始用户意图，不要仅为让操作通过而扩大访问范围，
也不要静默切换执行模式。

## 观察与游标失败

| 错误码 | 动作 |
| --- | --- |
| `stale_base`、`revision_mismatch` | 时间线在观察基线后发生变化。丢弃该 Patch 使用的观察状态，读取摘要，再检查受影响片段。 |
| `invalid_read_token`、`stale_observation` | 观察状态缺失、已使用或不再对应当前状态。绝不重试原令牌；重新读取。 |
| `invalid_cursor`、`stale_cursor` | 丢弃游标，从第一页重新开始同一定向查询。 |
| `invalid_read_query` | 修正视图/选择器组合；不得直接扩大到 `full`。 |
| `context_budget_exceeded` | 缩小帧范围、片段 ID、通道、类型、include 字段组或分页上限。 |

人工修改导致状态过期时，先理解最新读取的内容。只有在基于该内容继续工作符合用户意图时，
才能使用 `blender_acknowledge` 接纳该状态，然后在 Patch 前再读取一次。

## 项目与会话失败

| 错误码 | 动作 |
| --- | --- |
| `project_not_allowed` | 请用户在 `BLENDER_VSE_ALLOWED_ROOTS` 授权包含目录；不得以移动文件作为规避方案。 |
| `project_not_found` | 确认准确路径。只有明确要求新项目时使用 `create_if_missing`。 |
| `project_mismatch` | 停止。不要切离或关闭无关的用户项目。 |
| `gui_not_visible`、`vse_not_visible`、`gui_not_stable` | 报告可见会话阻塞，不回退到隐藏/无头编辑。 |
| `session_not_ready`、`bridge_not_ready`、`bridge_unreachable` | 只有本地 Blender/Bridge 状态发生实质变化后才重试；盲目重复调用不属于恢复。 |
| `vse_scene_mismatch`、`vse_visible_strip_mismatch`、`vse_current_frame_empty` | 停止并报告失败的具体证据；不得声明时间线可用。 |

缺少 MCP 工具或服务无法启动属于设置问题，不能因此改用原始 `bpy`。请引导用户查看仓库的
本地 MCP 设置指南。

## Patch 与持久化失败

| 错误码 | 动作 |
| --- | --- |
| `invalid_args`、`unsupported` | 在 `command-index.json` 中核对操作的确切签名，只修复被拒绝的命令，然后在新 Patch 前取得最新读取。 |
| `input_missing` | 获取缺失素材或清单的确切路径，必要时向用户询问；不要搜索无关目录。 |
| `patch_rolled_back` | 将该批次视为未提交。查看受限范围内的失败详情并重新读取；修正后构造新的 Patch ID。 |
| `checkpoint_not_found` | 从已知项目上下文确认预期检查点名；绝不猜测文件名。 |
| `checkpoint_reopen_failed`、`session_close_failed` | 保留报告的备份路径并停止，等待用户处理；不要盲目重复替换。 |
| `validation_failed`、`vse_media_missing` | 读取受影响区域/源字段，修复或报告缺失媒体后才能完成。 |
| 代理警告或 `stale_proxy_source` | 在外部重建代理并附加新验证的清单；最终渲染仍使用原始媒体。 |

任何修正 Patch 成功后，都要再次读取并运行 `blender_verify`。不得根据回滚或恢复元数据
推断持久化成功。

## 压缩或任务交接

保留此紧凑恢复胶囊：

```text
project: .blend 绝对路径
intent: 当前用户批准的编辑结果
confirmed: 最后修订 + 时间线哈希
applied: 有界近期 Patch ID/动作/输出 + 总数与摘要
pending: 未决选择与下一次定向读取
```

丢弃观察 ID、游标、完整时间线页面、原始工具响应和 GUI 诊断树。恢复时调用
`blender_read(view="summary")`，将结果与胶囊比较，并在任何写入前取得新的定向读取结果。
