# 上下文模型

[English version](context-model.md)

状态：已接纳为 Context Protocol 1.1。

## 决策

Blender VSE Control 支持长流程、上下文 Stateful Agent，同时防止原始时间线和诊断输出无限扩张对话。`.blend` 仍是持久事实源。模型上下文只包含当前目标、紧凑项目观察、相关稳定 ID 和近期工具结果。

机器可读策略位于 [`context-policy.json`](../src/blender_vse/context-policy.json)。代码与测试直接读取该文件；本文解释设计决策，不重复每个字段。

使用 `blender-vse context-policy` 检查打包后的生效策略。

## 读取升级

`BlenderVSE.read` 默认使用 `summary`：

| 视图 | 用途 | 上限 |
| --- | --- | ---: |
| `summary` | 修订令牌、项目形状、数量、通道、边界、警告 | 8 KB |
| `range` | 与指定帧区间重叠的片段，分页 | 16 KB |
| `detail` | 按稳定 ID、通道、类型或区间选择的片段，分页 | 16 KB |
| `full` | 显式兼容/调试响应 | 无界 |

其他面向模型的结果同样有界：

| 结果 | 上限 |
| --- | ---: |
| Patch 回执 | 4 KB |
| 接纳回执 | 4 KB |
| 持久化验证 | 8 KB |
| 错误信封 | 4 KB |

Patch 回执汇总命令结果并返回有界负载预览，不重放原始负载历史。Verify 回执用数量和有界警告替代逐片段代理状态。会话失败不返回原始窗口树；有本地诊断日志时只提供位置。

每个数据投影都会为外层工具/传输信封预留 512 字节，因此公布上限适用于完整的模型可见工具结果，而不仅是内部 data 对象。

Agent 只应按需升级读取：

```text
summary
  → 针对预期编辑的 range 或 detail
  → 使用最新 observation_id 执行 patch
  → 用 summary 确认新修订
```

`range` 和 `detail` 使用不透明游标，绑定修订、时间线哈希、查询选择器、include 字段组和分页上限。时间线变化返回 `stale_cursor`；查询变化返回 `invalid_cursor`。应从第一页重新分页，不能合并不同时间线状态的页面。

## 字段披露

每个有界片段都包含稳定定位和时序字段。可选字段组必须显式请求：

- `text`：文本及可编辑文本样式；
- `source`：已解析源路径；
- `transform`：变换与混合字段；
- `audio`：音量；
- `proxy`：代理状态；
- `metadata`：宿主元数据。

大字符串和对象会按 UTF-8 字节截断，并声明 `_truncated_fields`。必要时分页也会缩小页面。如果单个片段仍放不下，则返回 `context_budget_exceeded`；服务绝不产生零进度游标。

## 压缩边界

完成重要里程碑后保留：

- 项目路径与用户目标；
- 已完成动作；
- 最后验证的修订和时间线哈希；
- 相关片段 ID；
- 近期已应用 Patch ID 与已验证输出路径；
- 用户约束、阻塞项和下一步动作。

丢弃：

- 观察令牌；
- 完整时间线和原始工具历史；
- 原始 Blender 日志与过期诊断；
- 已完成工作的详细推理。

压缩或任务交接后，先调用 `read summary`，再执行目标 `range/detail` 读取，并且写入时只使用新返回的观察令牌。这样可确定性恢复，而不会把对话记忆当作项目状态。

### 有界恢复胶囊

`build_resume_capsule` 把保留状态转换成上限 4 KB 的确定性 JSON 胶囊。长历史只保留近期条目以及完整序列的总数、省略数与 SHA-256 摘要。摘要能检测较早历史变化，而不用把历史重新放进模型上下文。各字段和近期条目限制位于上下文策略的 `compaction.capsule`。

胶囊从不接受观察 ID 或游标。即使包含最后确认的修订/哈希，恢复后的第一个动作仍必须是新的摘要读取，然后再做目标详情读取。

## 兼容性

`view="full"` 仍为显式旧版调用方保留。它标记为 `bounded=false`，不能分页或过滤，也不是 Skill 或 MCP 的默认路径。

## 非目标

- 核心库不压缩模型对话。
- 核心库不持久化 Prompt 或推理。
- MCP 服务和 Skill 不在调用之间保留对话历史。
- `changes_since_revision` 需要有界变化日志，推迟到后续协议版本。

## 相关指南

- [Skills 与渐进工作流指令](https://developers.openai.com/plugins/concepts/skills)
- [MCP 工具与结构化结果](https://developers.openai.com/plugins/concepts/mcp-server)
- [长流程工具工作中的压缩](https://developers.openai.com/api/docs/guides/latest-model)
