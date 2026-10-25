# 本地 Codex 插件

[English version](plugin.md)

仓库根目录本身就是一个有效的本地 Codex 插件。它将 `blender-vse` Skill 与一个由四个工具组成的本地 stdio MCP 服务器整合在一起：

```text
blender-vse/
|-- .codex-plugin/plugin.json
|-- .mcp.json
|-- skills/blender-vse/
|-- src/blender_vse/
`-- pyproject.toml
```

当前版本面向本地 Codex 使用。提交公开 ChatGPT 插件需要可供审查的 HTTPS MCP 端点；本地服务器则有意采用 stdio，并且不会开放网络监听端口。

## 市场条目

仓库包含 `.agents/plugins/marketplace.json`。由于插件位于仓库根目录，其中唯一的条目使用基于 Git 的 `url` 来源，因此 Codex 可以像安装其他市场插件一样安装它。大多数用户应改用[一键安装脚本](installation_zh-CN.md)，直接注册 MCP 服务。

下面的发布 ZIP 和本地市场命令供维护、离线安装和恢复使用。

## 前置条件

- Blender 必须安装在与 Codex 相同的计算机上，并与 Codex 共用同一个交互式桌面。
- `PATH` 上需要有 [`uv`](https://docs.astral.sh/uv/)。无需预装 Python；[一键安装脚本](installation_zh-CN.md)会在缺少 uv 时自动安装。

插件的 `.mcp.json` 会执行以下命令：

```bash
uv run --no-project --managed-python --python "3.12" --with "mcp==2.1.1" python scripts/run_plugin_mcp.py
```

`uv` 会在需要时下载托管的 Python 3.12，创建可缓存的隔离运行环境，并在首次使用时提供 MCP SDK。这个小型启动器会从插件自身的 `src/` 目录导入服务器。它不会在已安装的插件目录中创建虚拟环境或锁文件，因此即使插件源码为只读状态，插件仍然可用。首次启动可能需要访问网络，后续启动则会复用 uv 缓存。插件启动命令固定使用已通过协议矩阵验证的 SDK 版本，而 Python 软件包的可选依赖仍保留兼容的 `mcp>=2,<3` 版本范围。配置只会转发文档中列出的 Blender VSE 和基础操作系统运行时变量，不会转发服务提供商凭据，也不会转发仅供测试使用的直接修改开关。

成功在线启动一次并填充所选 uv 缓存后，需要离线启动的宿主可以设置 `UV_OFFLINE=1`；插件会明确将这一设置传递给 uv。

`blender_patch` 和 `blender_acknowledge` 已配置为执行前请求批准。无论宿主采用何种审批设置，服务器都会独立执行允许根目录、修订号、时间线哈希和观察 ID 检查。

## 构建可安装的本地市场

在仓库检出目录中运行：

```bash
uv run --no-project --python ">=3.10" python scripts/build_plugin.py
uv run --no-project --python ">=3.10" python scripts/build_plugin.py --check
```

确定性归档会写入 `dist/blender-vse-plugin-<version>.zip`，其中包含以下本地市场根目录：

```text
blender-vse-marketplace/
|-- .agents/plugins/marketplace.json
`-- plugins/blender-vse/
    |-- .codex-plugin/plugin.json
    |-- .mcp.json
    |-- skills/
    `-- source and license files
```

解压归档，注册其中的非默认市场根目录，然后安装插件：

```bash
codex plugin marketplace add /absolute/path/to/blender-vse-marketplace
codex plugin add blender-vse@blender-vse-local
```

打开 Codex 插件目录，确认插件来自本地来源，然后开始新任务，让 Codex 从已安装的版本加载 Skill 和 MCP 元数据。请勿手动编辑 Codex 配置文件。

## 从源码开发

安装本地构建前，请运行清单声明的命令和插件专用质量门槛：

```bash
python -m pip install -e ".[dev]"
python tests/run.py fast
python tests/run.py mcp
python tests/run.py plugin
```

`plugin` 测试配置会执行与 `.mcp.json` 中完全相同的命令，并验证只发现文档列出的四个工具。快速门槛会验证清单、审批设置、环境变量允许列表、确定性归档、Skill，以及生成的命令索引。

此外，还应使用当前 Codex 安装附带的 `plugin-creator` `validate_plugin.py` 验证仓库根目录。本地迭代时，请使用 `plugin-creator` 提供的 cachebuster / 重装流程，不要手动追加版本后缀或编辑市场状态。

## 工程访问

工程保存在 `<workspace>/blender-vse-projects` 中，工具调用使用相对于它的路径，无需任何工程配置。另请参阅[配置](configuration_zh-CN.md)和[本地 MCP 服务](mcp_zh-CN.md)。
