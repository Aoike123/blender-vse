# 在 Codex、Claude Code 或 DSH 中安装

[English version](installation.md)

本仓库提供一个 `blender-vse` Skill，以及一个包含四个工具的 `blender-vse-control` MCP 服务。面向各客户端的清单只是这些共享组件的适配层，并不包含另一套独立的编辑实现。

## 运行时初始化与外部应用程序

不要预设系统已经安装 Python 或 `uv`。启用 MCP 服务之前，负责安装的 Agent 必须检查 `uv`。如果尚未安装，Agent 必须先征得用户同意，再按照 [uv 官方安装指南](https://docs.astral.sh/uv/getting-started/installation/)选择安装方式，并通过 `uv --version` 验证安装结果。不得在用户不知情的情况下运行下载的安装程序。

MCP 启动命令使用由 `uv` 管理的 Python 3.12。首次运行时，`uv` 会下载并缓存一个隔离的解释器，因此无需安装系统 Python。初次配置需要网络连接；后续启动会复用由 `uv` 管理的解释器和软件包缓存。

Blender 和 FFmpeg 都是外部应用程序，不得在用户不知情的情况下下载。配置项目目录后，请运行 `blender-vse status`：

- 如果 Blender 不可用，请引导用户前往 [Blender 官方下载页](https://www.blender.org/download/)，然后在开始编辑前重新运行状态检查。
- 如果 FFmpeg 或 ffprobe 不可用，请引导用户前往 [FFmpeg 官方下载页](https://ffmpeg.org/download.html)。基础的时间线编辑仍可进行，但代理文件生成和媒体测试素材尚未就绪。

## 必需的安装后对话

安装过程包含两个状态：

- `installed`：客户端已经复制或注册 Skill 和 MCP 服务。
- `ready`：用户已经确认绝对项目目录，并且 MCP 进程已通过 `BLENDER_VSE_PROJECTS_DIR` 接收到该目录。

### 优先使用当前工作区

询问项目目录之前，先检查 Harness 当前是否有已打开的工作区。若有，建议将 `.blend` 文件及其引用的媒体保存在 `<workspace>/blender-vse-projects` 中。集中存放这些文件有助于沙盒访问，也能提高交接的可移植性，并让路径关系更加清晰。

如果没有可用的工作区，应建议用户先打开或选择一个工作区，再继续配置。若选定目录位于工作区之外，应同时显示选定路径和推荐路径，说明宿主沙盒可能需要额外授权，而且交接的可移植性会降低，然后请求用户明确确认。确认后仍可使用外部目录，但必须将其加入 `BLENDER_VSE_ALLOWED_ROOTS`。绝不能自动移动现有项目或媒体文件。

安装完成后，负责安装的 Agent 必须检查 `BLENDER_VSE_PROJECTS_DIR`。若该变量尚未设置，不得声称配置已经完成，而应询问：

> Blender VSE 已安装，但尚未配置项目存储目录。你希望将可编辑的 `.blend` 项目保存在哪个绝对目录中？

确认用户提供的是绝对目录路径。只有在用户同意后才能创建该目录。请在客户端的启动环境中设置 `BLENDER_VSE_PROJECTS_DIR`；除非用户要求使用其他位置，否则应将同一目录设为 `BLENDER_VSE_ALLOWED_ROOTS` 中唯一的条目。严禁将插件缓存、市场仓库的检出目录、临时克隆目录或软件包目录用作用户项目目录。

如需配置 Windows 用户级环境变量，只有在用户确认路径后，负责安装的 Agent 才能提供以下命令：

```powershell
[Environment]::SetEnvironmentVariable(
  "BLENDER_VSE_PROJECTS_DIR",
  "D:\VideoProjects",
  "User"
)
```

在 macOS 或 Linux 上，应在用于启动客户端的环境中导出该变量。写入 Shell 配置文件只会影响从该 Shell 启动的客户端；桌面启动器需要单独配置持久化环境变量。Claude 会直接使用插件选项，而 DSH 生成器会将用户确认的值写入隔离的 Cordis 补丁。

如果 `BLENDER_VSE_PROJECTS_DIR` 已经设置，应报告其实际生效值，并请用户确认是否继续使用。如果在桌面客户端运行期间更改了 Windows 持久化用户环境变量，必须彻底退出并重新启动客户端；只新建任务不会刷新父进程环境。最后，请运行 `blender-vse status` 或等效的配置检查，并报告 Skill、MCP 服务、四个工具、项目目录和配置来源。

此流程的机器可读版本请参阅 [`install-contract.json`](../install-contract.json)。

## Codex

将仓库 URL 提供给 Codex，并让其安装插件。Codex 会在内部将该仓库注册为插件市场，然后安装 `blender-vse@blender-vse`。维护者命令请参阅仓库中的 [Codex 指南](plugin_zh-CN.md)。

安装完成后，Codex 必须完成上述项目目录对话。内置的 `.mcp.json` 会从 Codex 启动环境继承 `BLENDER_VSE_PROJECTS_DIR` 和 `BLENDER_VSE_ALLOWED_ROOTS`。设置这些变量后，请完整退出并重新启动 Codex，再新建任务，确保已安装的 Skill 和 MCP 进程都基于新的父进程环境重新加载。

## Claude Code

本仓库既是 Claude Code 的插件市场，也提供对应的插件：

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

Claude 清单将 `projects_dir` 声明为必填的目录选项，因此 Claude Code 会在启用插件时提示用户输入。非交互式安装可通过 Claude 支持的 `--config projects_dir=/absolute/path` 参数传入。Claude 会将该值作为 `BLENDER_VSE_PROJECTS_DIR` 和初始允许根目录注入内置的 MCP 服务。重新加载插件或开始新会话，然后确认一个 Skill、一个 MCP 服务和四个工具均已可用。

## DeepSeek Harness（DSH）

将仓库克隆到长期保留的位置。首次运行安全的 DSH 安装程序时，不要传入项目目录；安装程序会复制完整的 Skill，并按设计返回 `ready: false` 以及必需的用户提示：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py --apply
```

安装位置取决于作用域：

- 用户级：`<DSH_HOME>/skills/blender-vse`，通常为 `~/.dsh/skills/blender-vse`；
- 项目级：`<project>/.dsh/skills/blender-vse`。

如需安装到项目作用域，请添加 `--scope project --project-root /absolute/project`。用户提供目录后，请使用已确认的目录重新运行安装程序。安装程序会原样保留已安装的 Skill，并写入一份隔离的补丁，不会覆盖用户的主要 DSH 配置：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects \
  --apply
```

只有当用户明确确认当前没有工作区，或明确选择使用外部目录时，才能添加 `--allow-external-projects`。不得提前添加此参数。

输出是一份只含一个条目的 Cordis 补丁，其中使用了 DSH 官方的 `@deepseek-ai/dsh-mcp-client`。安装程序会报告 `configured` 而不是 `ready`，因为补丁尚未激活。可通过以下命令进行测试，且不会改变用户状态：

```bash
dsh --profile web --patch <DSH_HOME>/integrations/blender-vse/cordis.patch.yml --dump-config
```

如需持久化安装，请将这个补丁条目合并到所选 profile 的 `cordis.patch.yml`，或主目录下的 `$DSH_HOME/cordis.patch.yml`。不得覆盖现有的补丁文件。重新启动 DSH，确认能够发现 Skill，且四个工具已经注册到 `mcp__blender-vse-control__*` 命名空间下。只有通过这项最终验证，Agent 才能报告 `ready`。

## 仅支持 MCP 的宿主

不支持 Skill 或插件的宿主仍可使用 MCP 服务。请指定明确的项目目录，并生成标准的 stdio 配置对象：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects
```

如果没有工作区，或者项目目录、允许根目录位于工作区之外，生成器都会拒绝执行；只有通过 `--allow-external-projects` 记录用户此前的确认后，才会继续。

此方式只提供执行能力，不会安装 Agent Skill。
