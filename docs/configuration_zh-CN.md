# 配置

[English version](configuration.md)

所有设置都是可选项。推荐名称使用 `BLENDER_VSE_*`；列出的 `VP_*` 别名仅用于迁移兼容。

## 项目存储就绪度

为兼容旧运行方式，`BLENDER_VSE_PROJECTS_DIR` 在运行时可以省略，但安装契约要求必须配置。新安装的 Harness 必须询问用户选择绝对目录；当变量缺失、只从旧别名继承或使用相对路径时，不得报告 `ready`。

操作系统专用回退路径会继续保留，以免破坏现有 CLI 调用，但它不能证明用户已选择存储位置。插件缓存、市场 Checkout、临时 Clone 和包目录绝不能保存可编辑项目。

Harness 有活跃工作区时，推荐 `<workspace>/blender-vse-projects`。没有工作区或目录位于工作区外属于提醒条件，而不是硬错误：应说明沙盒与可移植性取舍，取得明确确认，然后授权选定的外部根目录。没有单独请求时，绝不能迁移现有项目或媒体。

## 运行时与执行

| 变量 | 旧别名 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `BLENDER_VSE_BLENDER_EXECUTABLE` | `VP_BLENDER_EXECUTABLE` | `BLENDER_EXECUTABLE`、已知安装路径，然后 `PATH` | Blender 可执行文件 |
| `BLENDER_VSE_EXECUTION` | `VP_BLENDER_EXECUTION` | `live_session` | `live_session` 或 `headless`；交互编辑仍拒绝无头模式 |
| `BLENDER_VSE_STATE_DIR` | — | 操作系统用户数据目录 | 运行时状态根目录 |
| `BLENDER_VSE_PROJECTS_DIR` | `VP_PROJECTS_DIR` | `<state>/projects` | 状态中显示的默认项目目录 |
| `BLENDER_VSE_TMP_DIR` | `VP_TMP_DIR` | `<state>/tmp` | 生成的固定脚本与会话日志 |
| `BLENDER_VSE_TEST_MEDIA_DIR` | — | `<state>/test-media` | 可选外部测试媒体目录 |
| `BLENDER_VSE_FFMPEG` | `VP_FFMPEG` | `PATH`，然后已知 Windows 路径 | FFmpeg 可执行文件 |
| `BLENDER_VSE_FFPROBE` | `VP_FFPROBE` | `PATH`，然后已知 Windows 路径 | ffprobe 可执行文件 |

## 可见会话发现

| 变量 | 旧别名 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `BLENDER_VSE_AUTOSTART` | `VP_BLENDER_AUTOSTART` | `1` | 需要时启动可见 Blender 会话 |
| `BLENDER_VSE_START_TIMEOUT` | `VP_BLENDER_START_TIMEOUT` | `45` | GUI 发现总截止时间，单位秒 |
| `BLENDER_VSE_VISIBILITY_GRACE` | `VP_BLENDER_VISIBILITY_GRACE` | `5` | 修复隐藏会话前的宽限期 |
| `BLENDER_VSE_STABILITY_SAMPLES` | `VP_BLENDER_STABILITY_SAMPLES` | `3` | 连续稳定窗口观察次数 |
| `BLENDER_VSE_STABILITY_INTERVAL` | `VP_BLENDER_STABILITY_INTERVAL` | `0.35` | 稳定性观察间隔，单位秒 |

## 本地 Bridge

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `BLENDER_BRIDGE_HOST` | `127.0.0.1` | Bridge 主机；只接受回环名称与地址 |
| `BLENDER_BRIDGE_PORT` | `10850` | 本地 TCP 端口 |
| `BLENDER_BRIDGE_TIMEOUT` | `30` | Socket 操作超时，单位秒 |

Bridge 没有身份验证。非回环绑定会被拒绝，不要转发端口。见[安全策略](../SECURITY_zh-CN.md)。

## MCP 边界

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `BLENDER_VSE_ALLOWED_ROOTS` | 生效的 `BLENDER_VSE_PROJECTS_DIR` | 允许通过 MCP 调用的项目所在目录，以操作系统路径分隔符分隔 |

MCP 适配器解析每个显式 `.blend` 路径；若路径逃逸所有允许根目录，会在启动 Blender 前拒绝。Windows 使用 `;` 分隔根目录，POSIX 系统使用 `:`。见[本地 MCP 服务](mcp_zh-CN.md)。

本地插件通过 `.mcp.json` 中显式 `env_vars` 白名单转发记录过的 Blender VSE 变量和基础操作系统/uv 运行时路径，不转发任意宿主变量。请在启动 Codex 前持久配置项目根目录；插件启动后修改交互 Shell 环境不会更新正在运行的服务。

## 仅测试开关

`BLENDER_VSE_ALLOW_DIRECT_MUTATION=1`（旧别名 `VP_ALLOW_DIRECT_MUTATION`）只为明确登记的历史集成测试绕过公开 Patch 边界。生产应用绝不能设置它。公开 GUI 冒烟档位会在不使用该开关的情况下证明正常路径。

## 检查生效配置

```bash
blender-vse status
```

该命令只读，不会启动 Blender。它报告已解析可执行文件、执行策略、Bridge 就绪度、状态目录、项目目录配置来源、允许根目录、以及安装后配置是否仍未完成。
