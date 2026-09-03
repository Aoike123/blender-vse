# 架构

[English version](architecture.md)

## 边界与事实源

Blender VSE Control 是围绕持久 `.blend` 时间线的本地控制平面。`.blend` 是事实源；渲染媒体、JSON 响应、代理文件和会话观察都是派生构件。

本包在运行时不依赖 Agent 框架、生产数据库、下载器或媒体服务商。

```text
应用 / Agent 宿主
        |
        | read / patch / acknowledge / verify
        v
可选本地 stdio MCP       仅四个工具，显式允许项目根目录
        |
        v
blender_vse.api          协作与检查点策略
        |
        +--> catalog      公开能力与执行清单
        +--> context      有界视图、游标与字节预算
        +--> resume       有界压缩/交接胶囊
        +--> router       公开操作边界
        v
blender_vse.blender      结果信封与保存验证
        |
        +--> vse_ops      固定、类型化的 bpy 脚本模板
        +--> runner       可见/无头执行策略
        +--> live_session 本地 Bridge、身份与可见 UI 证明
        +--> .blend       规范持久状态
```

## 规范清单

项目避免重复维护列表：

- `catalog.py` 管理操作族、只读操作、无头操作、项目可选操作、控制平面命令、内部原语及已移除操作的迁移错误。
- `context-policy.json` 管理响应预算、可选字段组和压缩/恢复状态。
- JSON Schema 管理序列化输入输出形状。
- `tests/test-plan.json` 管理测试档位和预算。
- 契约测试证明目录、适配器注册表、路由、Schema、CLI 和文档始终同步。

## 执行模式

交互编辑需要可见 Blender GUI 和 Video Editing 工作区。执行前，会话层会证明 Bridge 进程、原生窗口、请求项目、场景绑定、时间线区域、预览区域和可见片段数量。证据缺失或有歧义时关闭失败。

只有原生媒体检查、渲染和新进程持久化验证可以无头执行。交互编辑绝不会静默回退到第二个后台 Blender 进程。

## 修订协议

1. `read` 返回持久修订、规范完整时间线哈希和一次性观察 ID。
2. `patch` 在修改前立即验证这三项。
3. 命令使用幂等 Patch ID 作为一个原子批次执行。
4. 成功只提交一个修订；失败恢复 Patch 前状态。
5. 下一个 Patch 必须重新 `read`。

人工 Blender 修改会改变规范哈希。调用方必须读取并理解变化，然后从新状态继续，或显式接纳它。控制器不会接纳未经观察的变化。

## 上下文 Stateful Agent

对话历史由 Agent 宿主拥有，不属于本包。上下文层通过 `summary`、`range` 和 `detail` 视图约束工具结果。分页游标绑定单一时间线修订和查询。宿主压缩后，调用方应丢弃观察令牌并重新做有针对性的读取。见[上下文模型](context-model_zh-CN.md)。

可选 MCP 进程有意保持轻量：它只保留有界、确定性的项目锁分片，不保留对话消息、观察或“当前项目”。每次调用都提交并重新授权项目路径。见[本地 MCP 服务](mcp_zh-CN.md)。

可选 Skill 是 Prompt 与编排层。精简入口定义状态转换规则；只有需要时才从聚焦参考文件读取命令签名和故障恢复。快速门槛会把生成的命令索引与规范目录及 Python 签名进行比对。

`resume.py` 是宿主侧辅助函数，不是对话存储。它把持久交接事实写成 4 KB 胶囊，通过近期历史、数量和摘要保留信息。Stateful 评估语料在 250 个合成编辑循环中回放冲突/恢复路径并测量活跃上下文，不会假装核心库拥有 Agent 对话。

## Harness 分发

仓库根目录同时是 Codex 与 Claude Code 市场/插件。DSH 通过文件系统提供方复用同一规范 Skill 和一条生成的 Cordis Patch。三者都启动同一个 stdio 服务；客户端文件不包含编辑实现。

MCP 命令使用 uv 管理的 Python 3.12，所以系统 Python 不是最终用户依赖，已安装源码也不必可写。缺少 uv 时需先取得用户同意；Blender 与 FFmpeg 仍为外部引导安装。确定性构建器生成离线 Codex 市场归档，GitHub 则是跨 Harness 的主要分发路径。这些本地路径都不声称 stdio 满足公开 HTTPS 插件提交要求。见[Harness 安装](installation_zh-CN.md)。

## 检查点恢复

恢复属于控制平面事务，不是普通 bpy 操作。控制器会验证已观察基线、创建可恢复备份、关闭准确的 GUI 项目、替换文件、在可见界面重新打开、重复会话证明，并完成新修订。它必须是所在 Patch 的唯一命令。

## 兼容性

为兼容原内嵌实现创建的时间线，内部 `video_ai_*` 自定义属性和 `VP_RESULT` 进程标记保持稳定。它们属于持久化及线协议细节，不是公开 Python 命名空间。

## 外部集成

代理编码和项目级资产身份属于宿主应用。本包会在附加外部清单前验证代理哈希、源元数据、路径包含关系和配置兼容性。资产操作把宿主拥有的 ID 绑定到片段，不导入宿主注册表。

本地 Bridge 威胁模型见[安全策略](../SECURITY_zh-CN.md)，公开/内部边界见[操作目录](operations_zh-CN.md)。
