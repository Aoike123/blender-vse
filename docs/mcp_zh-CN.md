# 本地 MCP 服务

[English version](mcp.md)

Blender VSE Control 提供可选的本地 Model Context Protocol 服务。它只是公开 Python API 的薄适配层：`.blend` 文件仍为事实源，MCP 进程不保存对话历史或全局“当前项目”。

## 安装

在与软件包相同的 Python 环境安装 MCP extra：

```bash
python -m pip install -e ".[mcp]"
```

贡献者工具（包括 MCP Inspector）请改装 `.[dev]`。适配器面向官方 Python MCP SDK 2.x，并使用本地 `stdio`。

## 授权项目目录

每次工具调用都提供显式 `.blend` 路径。服务在联系 Blender 前规范化路径，并且只允许位于授权目录下的项目。把 `BLENDER_VSE_ALLOWED_ROOTS` 设置为按操作系统路径分隔符分隔的列表：

```powershell
$env:BLENDER_VSE_ALLOWED_ROOTS = "D:\VideoProjects;E:\SharedEdits"
```

```bash
export BLENDER_VSE_ALLOWED_ROOTS=/srv/video-projects:/mnt/shared-edits
```

变量缺失时，服务只允许 `BLENDER_VSE_PROJECTS_DIR`；其默认值是操作系统专用用户数据项目目录。根目录可以稍后创建，但已经存在的根路径必须是目录。配置和工具调用都应优先使用绝对路径。

## 连接宿主

`blender-vse-mcp` 是长时间运行的协议进程，由 MCP 宿主启动。直接运行看起来没有动作，是因为它正在 stdin 等待消息。典型 Windows 宿主条目如下：

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

macOS 或 Linux 的 `command` 应指向 `/absolute/path/to/.venv/bin/blender-vse-mcp`。不同宿主的配置位置不同，但命令与环境契约相同。宿主通常用受限环境启动子进程，因此应把允许根目录写入宿主条目，而不是依赖交互 Shell 导出。

贡献者可以检查生成的工具 Schema：

```bash
mcp dev src/blender_vse/mcp/server.py --with-editable .
```

## 四工具接口

| 工具 | 用途 | 重要规则 |
| --- | --- | --- |
| `blender_read` | 读取有界摘要或目标时间线页面 | `summary` 为默认值；`full` 只用于显式兼容 |
| `blender_patch` | 应用一批原子白名单命令 | 需要最新修订、哈希、观察 ID 和幂等 Patch ID |
| `blender_acknowledge` | 观察后接纳人工 Blender 修改 | 绝不能接纳未读取和理解的状态 |
| `blender_verify` | 重新打开并验证持久项目状态 | 在最后一次读取/Patch 循环后使用 |

MCP 不公开任意 Python、原始 Bridge 执行、操作目录内部项、Shell 访问或隐式项目选择工具。

## Stateful 工作流

Agent 宿主拥有不断扩张的对话上下文。服务只贡献有界观察，不重放对话：

```text
blender_read(summary)
        |
        +--> blender_read(range/detail, selectors)
                    |
                    +--> blender_patch(fresh observation)
                                  |
                                  +--> blender_read(summary) --> ... --> verify
```

宿主压缩、任务交接、过期基线响应或对当前观察存在任何疑问后，应丢弃 `observation_id` 并重新调用 `blender_read`。跨压缩只保留显式项目路径、用户意图、最后确认的修订/哈希、带数量和摘要的有界近期 Patch ID/动作/输出，以及未决决定。规范规则和字节预算见[上下文模型](context-model_zh-CN.md)。

## 本地执行与并发

stdio 服务必须与可见 Blender 进程位于同一台计算机和交互桌面。它有意不公开 HTTP Listener。针对同一规范项目路径的调用会串行执行；不同项目不共享“当前项目”变量。如果编辑器由另一个项目占用，Blender 自身的可见会话身份检查仍会关闭失败。

MCP 安全边界、工具覆盖和一次真实子进程握手集中在四秒 `mcp` 门槛。它会在最小和最大 Python 版本运行，不拖慢核心 fast/coverage 收集。真正 GUI 编辑由 `blender-smoke` 覆盖；见[测试指南](testing_zh-CN.md)。

## Prompt 与 Skill 层

MCP 服务提供执行，不提供长篇行为 Prompt。内置 [`blender-vse` Skill](../skills/blender-vse/SKILL_zh-CN.md)提供渐进的 read/Patch/恢复工作流，并声明 stdio 服务依赖。[本地插件指南](plugin_zh-CN.md)把二者打包成已验证、可安装的市场归档。公开 ChatGPT 发布属于另一条路径，因为它需要 HTTPS MCP 端点，而不是本地 stdio 进程。
