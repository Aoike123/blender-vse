# 客户端兼容性

[English version](clients.md)

由四个工具组成的 MCP 服务器和 Agent Skill 可在不同客户端之间复用，但安装方式和审批元数据由具体宿主决定。不要把任一客户端的插件清单当作通用配置文件。

| 使用场景 | 状态 | 支持方式 |
| --- | --- | --- |
| Python / CLI | 已验证 | 安装软件包后调用 `blender-vse` |
| 通用本地 MCP 宿主 | 已通过官方 SDK 客户端验证 | 通过 stdio 启动 `blender-vse-mcp` 或 uv 启动器 |
| Codex 本地插件 | 已验证，包括从解压包安装 | 使用[本地 Codex 插件](plugin_zh-CN.md) |
| Claude Code | 已使用 2.1.259 在隔离环境中验证 | 安装 GitHub 市场；必填的目录选项会配置 MCP |
| DeepSeek Harness（DSH） | 已使用 0.1.0-rc.6 在隔离环境中验证 | 安装 Skill，并合并生成的唯一一条 `dsh-mcp-client` 补丁项 |
| Claude Desktop | 配置已有文档说明；尚未在应用层进行端到端测试 | 添加生成的标准 stdio 服务器对象 |
| ChatGPT 公开插件 | 尚不支持 | 需要经过审查的 HTTPS MCP 端点；仅有本地 stdio 无法满足要求 |

所有 Harness 安装方式都遵循[安装契约](installation_zh-CN.md)。复制组件后，安装状态仍为 `installed`；只有用户确认 `BLENDER_VSE_PROJECTS_DIR` 的绝对路径后，才能变为 `ready`。

## 生成标准 stdio 配置

Codex 插件根目录中的 `.mcp.json` 包含 Codex 专用的审批和环境变量继承字段。其他宿主可使用绝对路径生成标准配置：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/path/to/workspace \
  --projects-dir /absolute/path/to/workspace/blender-vse-projects
```

仅在需要授予其他目录访问权限时，才重复传入 `--allowed-root`。该命令只输出 JSON，不会修改宿主配置。审阅输出内容后，通过宿主常规的配置界面或 CLI 合并唯一的 `blender-vse-control` 条目。

## Claude Code

Claude Code 会将仓库根目录安装为自包含插件，其中包括规范的 `skills/blender-vse` 目录，以及 Claude 专用的标准 stdio 配置：

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

清单将 `projects_dir` 设为必填的用户选项，因此系统会直接询问项目目录，无需手动编辑设置。该值会注入为 `BLENDER_VSE_PROJECTS_DIR` 和初始的 `BLENDER_VSE_ALLOWED_ROOTS`。修改此选项后，请重新加载插件或开始新会话。负责安装的 Agent 应推荐当前工作区下的 `blender-vse-projects` 目录。如果当前没有工作区，或用户选择了工作区外的目录，Agent 必须先说明相关影响并取得明确确认。

使用 `claude mcp list` 和 `/mcp` 确认只出现四个工具。使用 `/skills` 和 `/context` 确认 Skill 已被发现，并检查上下文用量。服务器不会持久化对话状态：上下文的增长和压缩由 Claude 管理，而 Skill 中 4 KB 的恢复胶囊（resume capsule）决定压缩后保留哪些信息。

## DeepSeek Harness（DSH）

DSH 会从标准文件系统位置发现用户级和项目级 Skill。用户级安装时，将完整的规范 Skill 复制到 `<DSH_HOME>/skills/blender-vse`；项目级安装时，则复制到 `<project>/.dsh/skills/blender-vse`。用户确认项目存储目录后，再生成单服务器 Cordis 补丁：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_dsh_config.py \
  --workspace-root /absolute/path/to/workspace \
  --projects-dir /absolute/path/to/workspace/blender-vse-projects \
  --output /absolute/path/to/blender-vse.cordis.yml
```

生成的补丁使用 `@deepseek-ai/dsh-mcp-client`、本地 stdio、本仓库实际验证过的精确 MCP SDK 版本，以及启动器的绝对路径。先用 `dsh --profile <name> --patch <file> --dump-config` 进行测试，再将其中唯一的条目合并到所选 profile 或主目录下的 `cordis.patch.yml`。不要覆盖其他用户条目。DSH 会在 `mcp__blender-vse-control__*` 命名空间下公开这四个工具。

如果用户选择外部目录，必须先记录用户的明确确认，然后才能使用 `--allow-external-projects` 重新运行生成器。

## Claude Desktop 与其他 MCP 宿主

运行 `print_mcp_config.py`，并使用其输出的 `mcpServers` 对象。其中包含带有 `type`、`command`、`args` 和 `env` 字段的标准条目，以及启动器的绝对路径。宿主专用的审批设置应保护 `blender_patch` 和 `blender_acknowledge`；服务端对允许根目录和修订的检查始终具有最终权威。

## 公开 ChatGPT 边界

本地编辑器必须与 Blender 运行在同一台计算机和同一个交互式桌面中，因此 stdio 是合适的本地传输方式。提交公开 ChatGPT 插件需要一个可访问的 HTTPS MCP 端点；开发测试期间也可以使用隧道。未来若要支持远程模式，还需要经过身份验证的本地配套程序和明确的信任模型。直接暴露未经身份验证的 Blender Bridge，或转发其回环端口，都不是可接受的捷径。

官方参考：

- [OpenAI 插件架构](https://developers.openai.com/plugins/concepts/plugins)
- [OpenAI 插件打包](https://developers.openai.com/plugins/build/plugins)
- [Claude Code 插件](https://code.claude.com/docs/en/plugins)
- [Claude Code 市场](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [DSH Skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)
- [DSH MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)
