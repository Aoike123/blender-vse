# 在 Codex、Claude Code 或 DSH 中安装

[English version](installation.md)

本仓库分发一个 `blender-vse` Skill 和一个只公开四个工具的 `blender-vse-control` MCP 服务。各客户端清单只是围绕共享组件的适配层，不包含独立编辑实现。

## 运行时引导与外部应用

不要假设用户已经安装 Python 或 `uv`。启用 MCP 服务前，安装 Agent 必须检查 `uv`。如果缺少，应先取得用户许可，使用[官方 uv 指南](https://docs.astral.sh/uv/getting-started/installation/)中的安装方式，并验证 `uv --version`。不得静默执行下载的安装器。

MCP 启动命令需要由 uv 管理的 Python 3.12。首次使用时，`uv` 会下载并缓存隔离解释器，因此不要求系统 Python。首次设置需要网络；之后启动会复用托管解释器和包缓存。

Blender 与 FFmpeg 是外部应用，不会被静默下载。项目目录配置完成后，运行 `blender-vse status`：

- 如果 Blender 不可用，引导用户使用[官方下载页](https://www.blender.org/download/)，编辑前重新运行状态检查；
- 如果 FFmpeg 或 ffprobe 不可用，引导用户使用[官方下载页](https://ffmpeg.org/download.html)。基础时间线编辑仍可继续，但代理生成和媒体测试素材尚未就绪。

## 必需的安装后对话

安装有两个不同状态：

- `installed`：客户端已经复制或登记 Skill 与 MCP 服务。
- `ready`：用户已确认绝对项目目录，并且 MCP 进程通过 `BLENDER_VSE_PROJECTS_DIR` 收到该目录。

### 优先使用活跃工作区

询问目录前，先判断 Harness 是否有活跃工作区。有工作区时，推荐用 `<workspace>/blender-vse-projects` 保存 `.blend` 和引用媒体。把两者放在一起有助于沙盒访问、交接可移植性和路径清晰度。

没有工作区时，建议先打开或选择一个工作区。若选定目录位于工作区之外，应同时显示选定路径与推荐路径，说明宿主沙盒可能需要额外授权且交接可移植性更弱，并取得明确确认。确认后仍支持外部目录，但必须加入 `BLENDER_VSE_ALLOWED_ROOTS`。绝不能自动移动现有项目或媒体。

安装 Agent 必须在安装后检查变量。变量缺失时不得报告设置完成，应询问：

> Blender VSE 已安装，但尚未完成项目目录配置。请告诉我你希望把可编辑 `.blend` 项目保存在哪个绝对目录。

验证答案为绝对目录。只有用户同意后才创建目录。把 `BLENDER_VSE_PROJECTS_DIR` 设置到客户端启动环境；除非用户要求其他位置，否则使用同一目录作为唯一 `BLENDER_VSE_ALLOWED_ROOTS`。绝不能选择插件缓存、市场 Checkout、临时 Clone 或软件包目录保存用户项目。

Windows 用户级配置只有在用户确认路径后才可以提供：

```powershell
[Environment]::SetEnvironmentVariable(
  "BLENDER_VSE_PROJECTS_DIR",
  "D:\VideoProjects",
  "User"
)
```

macOS 或 Linux 应在启动客户端的环境中导出变量。Shell Profile 导出只影响从该 Shell 启动的客户端；桌面启动器需要自身的持久环境配置。Claude 直接使用插件选项，DSH 生成器则把已确认值写入隔离 Cordis Patch。

如果 `BLENDER_VSE_PROJECTS_DIR` 已设置，应报告生效值并询问用户是否继续使用。Windows 持久用户环境变量在桌面客户端运行期间发生变化时，必须完整退出并重新启动客户端；只新建任务不会刷新父进程环境。最后运行 `blender-vse status` 或等价配置检查，并报告 Skill、MCP 服务、四个工具、项目目录与配置来源。

此流程的机器可读版本见 [`install-contract.json`](../install-contract.json)。

## Codex

把仓库 URL 发给 Codex 并要求安装插件。内部流程会登记仓库市场并安装 `blender-vse@blender-vse`。维护者命令记录在仓库的 [Codex 指南](plugin_zh-CN.md)中。

安装后，Codex 必须执行上述项目目录对话。内置 `.mcp.json` 从 Codex 启动环境继承 `BLENDER_VSE_PROJECTS_DIR` 与 `BLENDER_VSE_ALLOWED_ROOTS`。设置后完整退出并重新启动 Codex，再开始新任务，确保已安装 Skill 与 MCP 进程从新的父进程环境重新加载。

## Claude Code

本仓库也是 Claude Code 市场与插件：

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

Claude 清单声明必需的 `projects_dir` 目录选项，因此启用插件时 Claude Code 会主动询问。非交互安装时，通过 Claude 支持的 `--config projects_dir=/absolute/path` 参数提供。Claude 会把该值作为 `BLENDER_VSE_PROJECTS_DIR` 和初始允许根目录注入 MCP 服务。重新加载插件或开始新会话，然后确认一个 Skill、一个 MCP 服务和四个工具。

## DeepSeek Harness（DSH）

把仓库 Clone 到持久位置。第一次运行安全 DSH 安装器时不提供项目目录；它会复制完整 Skill，并有意返回 `ready: false` 和必需的用户提示：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py --apply
```

目标位置为：

- 用户级：`<DSH_HOME>/skills/blender-vse`，通常为 `~/.dsh/skills/blender-vse`；
- 项目级：`<project>/.dsh/skills/blender-vse`。

项目级安装需添加 `--scope project --project-root /absolute/project`。用户回答后，使用已确认目录重新运行；安装器保留完全相同的 Skill，并写入隔离 Patch，不覆盖用户主 DSH 配置：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects \
  --apply
```

如果用户明确确认缺少工作区或使用外部目录，再添加 `--allow-external-projects`；不得提前添加。

输出是一条使用 DSH 官方 `@deepseek-ai/dsh-mcp-client` 的 Cordis Patch。安装器报告 `configured` 而不是 `ready`，因为 Patch 尚未激活。可在不改变用户状态的情况下测试：

```bash
dsh --profile web --patch <DSH_HOME>/integrations/blender-vse/cordis.patch.yml --dump-config
```

持久安装时，把这一个 Patch 项合并到所选 Profile 的 `cordis.patch.yml` 或主目录 `$DSH_HOME/cordis.patch.yml`，不得覆盖现有 Patch 文件。重新启动 DSH，确认 Skill 可发现，且四个工具登记在 `mcp__blender-vse-control__*` 命名空间。只有完成最终验证后，Agent 才能报告 `ready`。

## 仅支持 MCP 的便携宿主

不支持 Skill 或插件的宿主仍可使用 MCP 服务。通过显式项目目录生成标准 stdio 对象：

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects
```

如果没有工作区或项目/允许根目录在工作区外，生成器会拒绝执行；只有 `--allow-external-projects` 能记录用户已经给出的确认。

该路径只安装执行能力，不安装 Agent Skill。
