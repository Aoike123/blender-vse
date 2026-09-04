# 上下文模型

[English version](context-model.md)

状态：已接纳为上下文协议 1.1。

## 决策

Blender VSE Control 支持长时间运行、保持上下文状态的 Agent 工作流，同时避免原始时间线和诊断输出让对话上下文无限膨胀。`.blend` 仍是唯一的持久化事实源。模型上下文只包含当前目标、精简的项目观察结果、相关稳定 ID 和近期工具结果。

机器可读策略位于 [`context-policy.json`](../src/blender_vse/context-policy.json)。代码和测试会直接读取该文件；本文只解释设计决策，不重复列出每个字段。

使用 `blender-vse context-policy` 检查打包后的生效策略。

## 逐级读取

`BlenderVSE.read` 默认使用 `summary`：

| 视图 | 用途 | 上限 |
| --- | --- | ---: |
| `summary` | 修订号、时间线哈希、观察 ID、项目结构、数量、通道、边界和警告 | 8 KB |
| `range` | 与指定帧区间重叠的片段，分页 | 16 KB |
| `detail` | 按稳定 ID、通道、类型或区间选择的片段，分页 | 16 KB |
| `full` | 显式兼容/调试响应 | 无界 |

其他面向模型的结果同样有界：

| 结果 | 上限 |
| --- | ---: |
| Patch 回执 | 4 KB |
| 接纳回执 | 4 KB |
| 持久化验证 | 8 KB |
| 错误封装 | 4 KB |

Patch 回执汇总命令结果，并返回大小受限的负载预览，不会重放原始负载历史。`verify` 回执用数量和有界警告取代逐片段列出的代理媒体状态。会话失败时不返回原始窗口树；如果有本地诊断日志，则只提供其位置。

每个数据视图都会为外层工具与传输封装预留 512 字节。因此，公布的上限适用于模型可见的完整结果，而不仅是内部 `data` 对象。

Agent 应按需逐级读取：

```text
summary
  → 针对预期编辑的 range 或 detail
  → 使用最新 observation_id 执行 patch
  → 用 summary 确认新修订
```

`range` 和 `detail` 使用不透明游标，游标绑定修订、时间线哈希、查询选择器、`include` 字段组和分页上限。时间线变化会返回 `stale_cursor`；查询变化会返回 `invalid_cursor`。此时应从第一页重新开始分页，不能合并来自不同时间线状态的页面。

## 字段披露

每个有界片段都包含稳定定位和时序字段。可选字段组必须显式请求：

- `text`：文本及可编辑文本样式；
- `source`：已解析源路径；
- `transform`：变换与混合字段；
- `audio`：音量；
- `proxy`：代理媒体状态；
- `metadata`：宿主元数据。

大字符串和对象会按 UTF-8 字节数截断，并记录在 `_truncated_fields` 中。必要时，分页也会减少单页内容。如果单个片段仍无法放入预算，则返回 `context_budget_exceeded`；服务绝不会返回无法推进的游标。

## 压缩边界

完成重要里程碑后保留：

- 项目路径与用户目标；
- 已完成动作；
- 最后验证的修订和时间线哈希；
- 相关片段 ID；
- 近期已应用 Patch ID 与已验证输出路径；
- 用户约束、阻塞项和下一步动作。

丢弃：

- 观察 ID；
- 完整时间线和原始工具历史；
- 原始 Blender 日志与过期诊断；
- 已完成工作的详细推理。

上下文压缩或任务交接后，先调用 `read summary`，再执行定向的 `range/detail` 读取；后续修改只能使用新返回的观察 ID。这样可以确定性地恢复工作，同时避免把对话记忆当作项目状态。

### 有界恢复胶囊

`build_resume_capsule` 把保留的状态转换为确定性 JSON 胶囊，上限为 4 KB。对于较长的历史记录，胶囊只保留近期条目，并记录完整序列的总数、省略数和 SHA-256 摘要。摘要可以检测早期历史是否变化，无需把整段历史重新放入模型上下文。各字段和近期条目的限制以机器可读形式保存在上下文策略的 `compaction.capsule` 下。

胶囊从不接受观察 ID 或游标。即使其中包含最后确认的修订和哈希，恢复后的第一个动作仍必须是重新读取摘要，然后再执行定向详情读取。

## 兼容性

`view="full"` 仍为明确需要旧版兼容行为的调用方保留。它标记为 `bounded=false`，不能分页或过滤，也不是 Skill 或 MCP 的默认路径。

## 非目标

- 核心库不压缩模型对话。
- 核心库不持久化提示词或推理过程。
- MCP 服务和 Skill 不在调用之间保留对话历史。
- `changes_since_revision` 依赖有界变更日志，将在后续协议版本中实现。

## 相关指南

- [Skills 与渐进工作流指令](https://developers.openai.com/plugins/concepts/skills)
- [MCP 工具与结构化结果](https://developers.openai.com/plugins/concepts/mcp-server)
- [长流程工具工作中的压缩](https://developers.openai.com/api/docs/guides/latest-model)
