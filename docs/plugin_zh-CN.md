# 本地 Codex 插件

[English version](plugin.md)

仓库根目录是有效的本地 Codex 插件，由 `blender-vse` Skill 与本地四工具 stdio MCP 服务组成：

```text
blender-vse/
|-- .codex-plugin/plugin.json
|-- .mcp.json
|-- skills/blender-vse/
|-- src/blender_vse/
`-- pyproject.toml
```

当前阶段面向本地 Codex。公开 ChatGPT 插件提交需要可审查的 HTTPS MCP 端点；本地服务有意保留 stdio，不开放网络 Listener。

## 用户安装契约

支持的用户请求是：

```text
帮我安装这个插件：https://github.com/Aoike123/blender-vse-control
```

仓库包含 `.agents/plugins/marketplace.json`。唯一条目使用 Git 支持的 `url` 来源，因为插件就在仓库根目录。安装 Agent 代表用户执行市场与插件 CLI 操作、验证结果，并提醒用户开始新任务。这些内部操作不是用户必须理解的步骤。

报告安装完成前，Agent 必须执行[必需的安装后对话](installation_zh-CN.md#必需的安装后对话)：询问绝对项目目录、配置 `BLENDER_VSE_PROJECTS_DIR`、验证生效值，然后才能报告插件为 `ready`。

下方发布 ZIP 与本地市场命令仅用于维护、离线和恢复，不是主要安装体验。

## 前置条件

- Blender 安装在与 Codex 相同的计算机和交互桌面。
- 不要求预装 Python。安装 Agent 检查 [`uv`](https://docs.astral.sh/uv/)；缺少时先请求许可，再从官方来源安装并验证，之后才能启用 MCP。
- 项目位于默认 `BLENDER_VSE_PROJECTS_DIR` 之外时，需要持久的 `BLENDER_VSE_ALLOWED_ROOTS` 值。

插件 `.mcp.json` 启动：

```bash
uv run --no-project --managed-python --python "3.12" --with "mcp==2.1.1" python scripts/run_plugin_mcp.py
```

`uv` 会在需要时下载托管 Python 3.12，创建缓存的隔离运行环境，并在首次使用时提供 MCP SDK；小型启动器从插件自身 `src/` 目录导入服务。它不会在已安装插件中创建虚拟环境或锁文件，因此只读插件源码仍可使用。首次启动可能需要网络，后续启动复用 uv 缓存。插件启动固定通过协议矩阵的 SDK 版本，而 Python 包 extra 保留兼容的 `mcp>=2,<3` 范围。配置只转发已记录的 Blender VSE 与基础操作系统运行时变量，不转发服务商凭据或仅测试用的直接修改开关。

一次在线启动填充所选 uv 缓存后，需要离线启动的宿主可以设置 `UV_OFFLINE=1`；插件明确允许将该值传给 uv。

`blender_patch` 与 `blender_acknowledge` 被配置为请求批准。无论宿主是否批准，服务仍独立执行允许根目录与修订令牌检查。

## 构建可安装的本地市场

从 Checkout 运行：

```bash
uv run --no-project --python ">=3.10" python scripts/build_plugin.py
uv run --no-project --python ">=3.10" python scripts/build_plugin.py --check
```

确定性归档写入 `dist/blender-vse-plugin-<version>.zip`，包含本地市场根目录：

```text
blender-vse-marketplace/
|-- .agents/plugins/marketplace.json
`-- plugins/blender-vse/
    |-- .codex-plugin/plugin.json
    |-- .mcp.json
    |-- skills/
    `-- source and license files
```

解压后添加这个非默认市场根目录并安装插件：

```bash
codex plugin marketplace add /absolute/path/to/blender-vse-marketplace
codex plugin add blender-vse@blender-vse-local
```

打开 Codex 插件目录确认本地来源，再开始新任务，使 Skill 与 MCP 元数据从已安装版本加载。不要手工编辑 Codex 配置文件。

## 从源码开发

安装本地构建前，运行清单声明的命令和插件专用门槛：

```bash
python -m pip install -e ".[dev]"
python tests/run.py fast
python tests/run.py mcp
python tests/run.py plugin
```

`plugin` 档位会执行 `.mcp.json` 中的精确命令，并验证只发现四个已记录工具。快速门槛验证清单、审批、环境白名单、确定性归档、Skill 与生成的命令索引。

还应对仓库根目录运行当前 Codex 安装附带的 `plugin-creator` `validate_plugin.py`。本地迭代使用 `plugin-creator` 的 Cachebuster/重装流程，不要手工附加版本后缀或编辑市场状态。

## 配置项目访问

宿主必须在启动插件进程前提供 `BLENDER_VSE_ALLOWED_ROOTS`。Windows 使用 `;` 分隔目录，macOS/Linux 使用 `:`。变量缺失时，只允许生效的 `BLENDER_VSE_PROJECTS_DIR`。见[配置](configuration_zh-CN.md)、[本地 MCP 服务](mcp_zh-CN.md)和[客户端兼容性](clients_zh-CN.md)。

优先使用 `<workspace>/blender-vse-projects`。Codex 没有活跃工作区，或用户选择外部项目/资源目录时，应显示工作区提醒并取得明确确认，再把该目录加入允许根目录。
