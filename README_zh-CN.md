# Blender VSE Control

[English documentation](README.md)

![Blender VSE Control：具有修订保护的可编辑时间线](assets/social-preview_zh-CN.png)

> 让 AI Agent 在 Blender 中剪片，同时保持时间线可见、可编辑、由你掌控。

Blender VSE Control 是面向 Blender Video Sequence Editor 的本地、类型化、修订安全
工程控制层。应用程序或 Agent 可以检查、编辑、续作和渲染明确指定的 `.blend`
时间线，并验证其持久化；文件始终是事实源，人工修改不会被静默覆盖。

> 状态：Alpha。当前主要验证目标为 Blender 5.1。内置 Bridge 的元数据声明支持
> Blender 4.2+，但正式兼容范围只以各版本发布说明中的实测结果为准。

## 从 GitHub 安装

把仓库链接发给 Codex、Claude Code 或 DeepSeek Harness（DSH），直接说：

```text
帮我安装这个插件：https://github.com/Aoike123/blender-vse-control
```

安装 Skill 与 MCP 后，Agent 必须继续询问用户希望把可编辑 `.blend` 项目保存到哪个
绝对目录。只有用户确认目录，并将其作为 `BLENDER_VSE_PROJECTS_DIR` 传给 MCP 后，
状态才是 `ready`。推荐使用 `<工作区>/blender-vse-projects`；没有工作区或选择了
工作区外目录时，Agent 必须先提醒风险并取得确认。三种 Harness 的安装、配置和验证方式见
[安装指南](docs/installation_zh-CN.md)；用户不需要手动修改客户端清单。

## 核心保证

- **先观察再写入：**每次 patch 都必须使用 fresh read 返回的修订号、时间线哈希和
  一次性令牌。
- **不覆盖人工修改：**基线变化时返回 stale-base 错误。
- **原子编辑：**一组命令只提交一个修订；失败时整体回滚。
- **可见协作：**交互编辑前必须证明 Blender GUI、目标项目、VSE 时间线与预览均
  可用。
- **持久化证据：**最终验证会在新 Blender 进程中重新打开作为事实源的 `.blend`，
  检查已保存的结构事实；它不会检查渲染帧，也不判断视觉或创意是否正确。
- **有限操作面：**调用方只能选择登记过的操作，不能传入任意 Python。
- **有界上下文：**读取默认只返回摘要；range/detail 通过分页和可选字段控制进入
  Agent 上下文的数据量；写入、验证与错误回执同样具有字节预算。
- **有界恢复：**压缩胶囊在 4 KB 内保留持久意图与近期证据，并用计数和摘要替代
  更早的历史。

## 安装与快速体验

最终用户不需要预装 Python 或 `uv`。如果缺少 `uv`，安装 Agent 会先征求许可，
再按官方方式安装；随后由 `uv` 准备项目专用的托管 Python 3.12。Blender 单独引导
安装；需要生成代理或测试媒体时再引导安装 FFmpeg。源码贡献者仍需 Python 3.10+。

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
blender-vse status
```

如果要让 Agent 宿主直接调用，请安装 `.[mcp]`、配置允许访问的项目目录，并让宿主
启动 `blender-vse-mcp`。参见[本地 MCP 指南](docs/mcp_zh-CN.md)。

仓库同时提供渐进披露的 [`blender-vse` Skill](skills/blender-vse/SKILL_zh-CN.md)：Skill
负责 Prompt 层的 read/patch/恢复纪律，MCP 负责执行，两者都不保存宿主的对话历史。

仓库根目录也是通过校验的本地 Codex 插件，并可构建确定性的本地市场归档；参见
[插件指南](docs/plugin_zh-CN.md)。

先创建或读取项目，再把返回的 `revision`、`timeline_hash` 与 `observation_id`
用于 patch：

```bash
blender-vse read ./projects/demo.blend --create
blender-vse patch ./projects/demo.blend \
  --base-revision 0 \
  --base-timeline-hash HASH_FROM_READ \
  --read-token TOKEN_FROM_READ \
  --patch-id patch-title-001 \
  --commands '[{"op":"add_text","text":"你好","channel":3,"frame_start":1,"length":90}]'
blender-vse verify ./projects/demo.blend
```

每次后续 patch 前都要重新 read。完整安装与 Python 示例参见
[入门指南](docs/getting-started_zh-CN.md)。

长流程应从 `summary` 逐步升级到目标 `range/detail`；`--view full` 只用于显式
兼容调试。具体规则见[上下文模型](docs/context-model_zh-CN.md)。

## 测试分层

所有测试档位、性能目标与硬超时统一定义在
[`tests/test-plan.json`](tests/test-plan.json)：

| 档位 | 用途 | 命令 | 目标 / 硬超时 |
| --- | --- | --- | ---: |
| `fast` | 核心单元与契约，不启动 MCP/Blender | `python tests/run.py fast` | 3 / 10 秒 |
| `coverage` | 宿主侧 Python 分支覆盖率 | `python tests/run.py coverage` | 5 / 15 秒 |
| `mcp` | 四工具契约与一次真实 stdio 发现 | `python tests/run.py mcp` | 4 / 10 秒 |
| `plugin` | 按插件清单真实启动 stdio | `python tests/run.py plugin` | 60 / 180 秒 |
| `harness` | 真实 Claude + DSH 包装与配置校验 | `python tests/run.py harness` | 60 / 180 秒 |
| `stateful` | 场景回放与 250 轮压缩评估 | `python tests/run.py stateful` | 5 / 15 秒 |
| `blender-headless` | Blender 原生媒体解码 | `python tests/run.py blender-headless` | 15 / 60 秒 |
| `blender-smoke` | 一次公开 API 的 GUI 完整流程 | `python tests/run.py blender-smoke` | 120 / 240 秒 |
| `blender-full` | 完整 Blender 回归 | `python tests/run.py blender-full` | 900 / 1200 秒 |

使用 `python tests/run.py list` 查看清单。测试安全规则与 CI 分工参见
[测试指南](docs/testing_zh-CN.md)。

## 文档

- [中文文档总览](docs/index_zh-CN.md)
- [英文文档总览](docs/index.md)
- [入门指南](docs/getting-started_zh-CN.md)
- [Python 与 CLI API](docs/api_zh-CN.md)
- [操作目录](docs/operations_zh-CN.md)
- [架构](docs/architecture_zh-CN.md)
- [配置](docs/configuration_zh-CN.md)
- [上下文模型](docs/context-model_zh-CN.md)
- [本地 MCP 服务](docs/mcp_zh-CN.md)
- [Agent Skill](skills/blender-vse/SKILL_zh-CN.md)
- [本地 Codex 插件](docs/plugin_zh-CN.md)
- [Codex、Claude Code 与 DSH 安装](docs/installation_zh-CN.md)
- [客户端兼容性与 Claude 配置](docs/clients_zh-CN.md)
- [测试指南](docs/testing_zh-CN.md)
- [安全策略](SECURITY_zh-CN.md)
- [贡献指南](CONTRIBUTING_zh-CN.md)
- [发布清单](RELEASING_zh-CN.md)

## 项目边界

本仓库负责 Blender 执行、白名单时间线操作、修订安全与持久化验证。它可以验证并
附加外部生成的[代理清单](src/blender_vse/schemas/proxy-manifest.schema.json)，但不生成
或搜集源素材，不下载或转码媒体，不编码或重建代理，不自动化通用 Blender 3D 工作或
任意 `bpy`，不维护项目级资产数据库，也不提供 Agent 框架。附加代理不会改变原始
源路径，最终渲染仍使用源媒体。

## 许可证

主体代码使用 [GNU AGPLv3](LICENSE)。内置 Blender MCP Bridge 使用 MIT 许可证，
详见[第三方声明](THIRD_PARTY_NOTICES_zh-CN.md)。
