# 客户端兼容性

[English version](clients.md)

四工具 MCP 服务与 Agent Skill 可以移植，但安装和授权元数据由宿主决定。不要把某个客户端的插件清单当成通用配置文件。

| 接口 | 状态 | 支持路径 |
| --- | --- | --- |
| Python / CLI | 已验证 | 安装软件包并调用 `blender-vse` |
| 通用本地 MCP 宿主 | 已由官方 SDK 客户端验证 | 通过 stdio 启动 `blender-vse-mcp` 或 uv 启动器 |
| Codex 本地插件 | 已验证，包括解压后的归档 | 使用[本地 Codex 插件](plugin_zh-CN.md) |
| Claude Code | 已在隔离状态用 2.1.259 验证 | 安装 GitHub 市场；必需目录选项负责配置 MCP |
| DeepSeek Harness（DSH） | 已在隔离状态用 0.1.0-rc.6 验证 | 安装 Skill，并合并一条生成的 `dsh-mcp-client` Patch 项 |
| Claude Desktop | 已记录配置，本项目未完成应用层执行测试 | 添加生成的标准 stdio 服务对象 |
| ChatGPT 公开插件 | 尚不支持 | 需要经过审查的 HTTPS MCP 端点；本地 stdio 不足以支持 |

所有 Harness 安装都遵循[安装契约](installation_zh-CN.md)。复制组件后状态为 `installed`；只有用户确认绝对 `BLENDER_VSE_PROJECTS_DIR` 后才能成为 `ready`。

## 生成标准 stdio 配置

Codex 插件根目录的 `.mcp.json` 包含 Codex 专用审批与环境继承字段。其他宿主可通过绝对路径生成标准配置：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/path/to/workspace \
  --projects-dir /absolute/path/to/workspace/blender-vse-projects
```

只有添加其他目录时才重复传入 `--allowed-root`。该命令只输出 JSON，不修改宿主配置。审阅后，通过宿主的常规配置界面或 CLI 合并唯一的 `blender-vse-control` 条目。

## Claude Code

Claude Code 会把仓库根目录安装为自包含插件，其中包括规范 `skills/blender-vse` 目录以及 Claude 专用的标准 stdio 配置：

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

清单要求提供 `projects_dir` 用户选项，因此无需手工编辑设置即可询问项目目录。该值会注入为 `BLENDER_VSE_PROJECTS_DIR` 和初始 `BLENDER_VSE_ALLOWED_ROOTS`。修改后重新加载插件或开始新会话。安装 Agent 应推荐当前工作区中的 `blender-vse-projects` 目录；缺少工作区或选择工作区外目录时，必须先说明影响并取得明确确认。

使用 `claude mcp list` 与 `/mcp` 确认只出现四个工具。使用 `/skills` 与 `/context` 确认 Skill 发现并观察上下文占用。服务不保存对话状态；不断增长或压缩的上下文由 Claude 管理，Skill 的 4 KB 恢复胶囊定义压缩后保留的内容。

## DeepSeek Harness（DSH）

DSH 从标准文件系统根目录发现用户级和项目级 Skill。用户级安装时复制完整规范 Skill 到 `<DSH_HOME>/skills/blender-vse`；项目级安装到 `<project>/.dsh/skills/blender-vse`。用户确认项目存储后，再生成单服务 Cordis Patch：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_dsh_config.py \
  --workspace-root /absolute/path/to/workspace \
  --projects-dir /absolute/path/to/workspace/blender-vse-projects \
  --output /absolute/path/to/blender-vse.cordis.yml
```

生成的 Patch 使用 `@deepseek-ai/dsh-mcp-client`、本地 stdio、本仓库实测的精确 MCP SDK 版本和绝对启动器路径。使用 `dsh --profile <name> --patch <file> --dump-config` 测试；然后把这一个条目合并到选定 Profile 或主目录 `cordis.patch.yml`，不得覆盖其他用户条目。DSH 会在 `mcp__blender-vse-control__*` 命名空间公开四个工具。

若用户选择外部目录，只有记录明确确认后才能用 `--allow-external-projects` 重新运行生成器。

## Claude Desktop 与其他 MCP 宿主

运行 `print_mcp_config.py` 并使用其输出的 `mcpServers` 对象。它包含标准 `type`、`command`、`args` 和 `env` 条目以及绝对启动器路径。宿主专用审批设置应保护 `blender_patch` 和 `blender_acknowledge`；服务端允许根目录与修订检查始终具有最终权威。

## 公开 ChatGPT 边界

本地编辑器必须与 Blender 共用同一台计算机和交互桌面，因此 stdio 是正确的本地传输方式。提交公开 ChatGPT 插件需要可访问的 HTTPS MCP 端点，开发测试时也可使用隧道。未来远程设计还需要经过身份验证的本地伴随程序和明确的信任模型；暴露未验证 Blender Bridge 或转发其回环端口都不是可接受的捷径。

官方参考：

- [OpenAI 插件架构](https://developers.openai.com/plugins/concepts/plugins)
- [OpenAI 插件打包](https://developers.openai.com/plugins/build/plugins)
- [Claude Code 插件](https://code.claude.com/docs/en/plugins)
- [Claude Code 市场](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [DSH Skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)
- [DSH MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)
