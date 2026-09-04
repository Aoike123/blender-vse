# 本地 MCP 服务

[English version](mcp.md)

Blender VSE Control 提供一个可选的本地 Model Context Protocol 服务器。它只是公开 Python API 的薄适配层：`.blend` 文件仍为事实源，MCP 进程既不保存对话历史，也不维护全局“当前项目”。

## 安装

在软件包所在的 Python 环境中安装 MCP 可选依赖：

```bash
python -m pip install -e ".[mcp]"
```

如需 MCP Inspector 等贡献者工具，请改为安装 `.[dev]`。适配器基于官方 Python MCP SDK 2.x，并通过本地 `stdio` 通信。

## 授权项目目录

每次工具调用都必须提供明确的 `.blend` 路径。服务器会在调用 Blender 前对路径进行规范化，并且只接受位于授权目录下的项目。请将 `BLENDER_VSE_ALLOWED_ROOTS` 设置为使用操作系统路径分隔符分隔的目录列表：

```powershell
$env:BLENDER_VSE_ALLOWED_ROOTS = "D:\VideoProjects;E:\SharedEdits"
```

```bash
export BLENDER_VSE_ALLOWED_ROOTS=/srv/video-projects:/mnt/shared-edits
```

该变量缺失时，服务器只允许访问 `BLENDER_VSE_PROJECTS_DIR`；后者默认指向相应操作系统用户数据目录下的项目目录。配置的根目录可以稍后创建，但已存在的根路径必须是目录。配置项和工具调用都应尽量使用绝对路径。

## 连接 Agent 宿主

`blender-vse-mcp` 是由 MCP 宿主启动的长时间运行协议进程。直接运行时，它看起来处于空闲状态，因为正在 `stdin` 上等待消息。典型的 Windows MCP 宿主配置如下：

```json
{
  "mcpServers": {
    "blender-vse": {
      "command": "D:\\path\\to\\venv\\Scripts\\blender-vse-mcp.exe",
      "env": {
        "BLENDER_VSE_ALLOWED_ROOTS": "D:\\VideoProjects"
      }
    }
  }
}
```

在 macOS 或 Linux 上，`command` 应指向 `/absolute/path/to/.venv/bin/blender-vse-mcp`。不同 Agent 宿主的配置位置各不相同，但命令和环境契约保持一致。Agent 宿主通常会在受限环境中启动子进程，因此应把允许的根目录写入配置，而不是依赖交互式 Shell 中导出的环境变量。

贡献者可以使用以下命令检查生成的工具 Schema：

```bash
mcp dev src/blender_vse/mcp/server.py --with-editable .
```

## 四个工具

| 工具 | 用途 | 重要规则 |
| --- | --- | --- |
| `blender_read` | 读取有界摘要或定向时间线页面 | `summary` 为默认值；`full` 只用于明确的兼容需求 |
| `blender_patch` | 以原子方式应用一批列入允许列表的命令 | 需要最新修订、哈希、单次使用的观察 ID 和幂等 Patch ID |
| `blender_acknowledge` | 观察后接纳人工 Blender 修改 | 绝不能接纳未读取和理解的状态 |
| `blender_verify` | 重新打开并验证持久化的项目状态 | 在最后一次 `read` / `patch` 循环后使用 |

MCP 不提供任意 Python 执行、原始 Bridge 执行、操作目录中的内部项、Shell 访问或隐式项目选择等工具。

## 有状态工作流

不断增长的对话上下文由 Agent 宿主管理。服务器只向上下文提供大小受限的观察结果，不会重放对话：

```text
blender_read(summary)
        |
        +--> blender_read(range/detail, selectors)
                    |
                    +--> blender_patch(fresh observation)
                                  |
                                  +--> blender_read(summary) --> ... --> verify
```

Agent 宿主压缩上下文、任务交接、收到过期基线响应，或对当前观察结果存在任何疑问后，都应丢弃 `observation_id` 并重新调用 `blender_read`。跨越上下文压缩时，只保留明确的项目路径、用户意图、最后确认的修订和哈希、数量受限且附带计数与摘要的近期 Patch ID、动作和输出，以及尚未解决的决定。规范规则和字节预算见[上下文模型](context-model_zh-CN.md)。

## 本地执行与并发

stdio 服务器必须与可见的 Blender 进程位于同一台计算机和同一个交互式桌面。它刻意不开放 HTTP 监听端口。针对同一规范化项目路径的调用会串行执行；不同项目之间不共享“当前项目”变量。如果编辑器正由另一个项目占用，Blender 自身的可见会话身份检查会按失败处理并拒绝执行。

四秒的 `mcp` 门槛会独立验证 MCP 安全边界、四个工具，以及一次真实的子进程握手。它会在受支持的最低和最高 Python 版本上运行，不会拖慢核心 `fast` 或 `coverage` 测试收集。真实 GUI 编辑仍由 `blender-smoke` 覆盖；见[测试指南](testing_zh-CN.md)。

## 提示词与 Skill 层

MCP 服务器负责执行，不提供冗长的行为指令。内置的 [`blender-vse` Skill](../skills/blender-vse/SKILL_zh-CN.md) 提供渐进式 `read`、`patch` 和恢复工作流，并声明对该 stdio 服务器的依赖。[本地插件指南](plugin_zh-CN.md)将二者打包为经过验证、可安装的市场插件包。公开发布到 ChatGPT 属于另一条路径，因为它需要 HTTPS MCP 端点，而不是本地 stdio 进程。
