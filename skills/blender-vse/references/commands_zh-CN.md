# Patch 命令

[English version](commands.md)

只有在准备 `blender_patch.commands` 时才读取本参考。每条命令都是一个 JSON 对象，包含
`op` 及该操作专用的参数。Patch 级的项目、修订、哈希、观察 ID 和 Patch ID 不应放入
单条命令中。

## 确认确切的命令格式

[command-index.json](command-index.json) 由权威的 Python 操作目录和函数签名生成。请在该文件
中搜索确切的操作名称，不要一次加载完整索引。没有 `=` 的参数为必需项；包含 `=` 的参数
为可选项，并会显示默认值。类型注解描述宿主接受的值。

不要臆造参数。整个 Patch 已经具备原子性，因此不要使用已排除的 `batch` 操作。项目创建
应由 `blender_read(create_if_missing=true)` 完成，状态接纳应使用 `blender_acknowledge`，
持久化证明则应使用 `blender_verify`。

操作目录中的只读操作不会出现在此处：请使用 `blender_read`，不要把发现或检查操作放入 Patch。

## 正确引用片段

- 操作接受 `video_ai_id` 时，优先使用定向读取返回的稳定 ID。
- 操作只接受 `target` 时，传入同一次最新读取中的当前片段名称。不要假设每个旧版
  `target` 字段都接受 ID。
- 绝不猜测片段标识符。如果没有返回所需字段，请在 Patch 前执行范围更窄的 detail 读取。

## 时间与路径

- 需要精确到帧时，优先使用帧字段（`frame_start`、`frame_end`、`at_frame`、`frames`）。
  只有操作明确需要时，才使用以秒计的源或时间线字段，避免意外混用单位。
- 媒体、字幕、字体、清单、渲染、复制和打包路径均应使用绝对路径。不要臆造缺失的源
  路径，也绝不能让渲染结果覆盖源素材。
- 代理在 Blender 外部生成。`attach_proxy` 使用已经验证的外部 `manifest_path`；
  `detach_proxy` 和 `clear_proxies` 不授予删除文件的权限。

## 小型示例

添加可编辑标题：

```json
[
  {
    "op": "add_text",
    "text": "片头标题",
    "channel": 3,
    "frame_start": 1,
    "length": 90,
    "font_size": 64,
    "position": [0.5, 0.82],
    "strip_name": "OpeningTitle"
  }
]
```

在 detail 读取返回当前名称后，以原子方式应用两项相关编辑：

```json
[
  {"op": "trim_strip", "target": "Interview_A", "frame_end": 420},
  {"op": "set_volume", "target": "Interview_Audio", "volume": 0.82}
]
```

将已验证的时间线渲染到新的输出路径：

```json
[
  {
    "op": "render_final",
    "output_path": "/absolute/output/final.mp4",
    "resolution": [1920, 1080],
    "fps": 30,
    "frame_start": 1,
    "frame_end": 900,
    "codec": "H264",
    "quality": "high"
  }
]
```

请按本地操作系统调整路径语法。

## 高风险命令

- `clear_vse`、删除、波纹编辑、提取、覆盖、素材替换、检查点删除和恢复操作，都需要明确
  的用户意图。
- `restore_checkpoint` 必须是所在 Patch 中的唯一命令。控制器会创建可恢复的恢复前备份，
  并重新打开同一个 GUI 项目。
- 只有确实需要一个原子事务时，才将渲染或打包与编辑放入同一个 Patch。通常应先重新读取
  已完成的编辑，再在新的 Patch 中渲染。
- 每个 Patch 应优先只表达一个语义连贯的编辑动作。较小的 Patch 在回滚、过期基线恢复和
  人工审查时更容易理解。
