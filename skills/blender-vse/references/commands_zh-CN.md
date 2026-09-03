# Patch 命令

[English version](commands.md)

只有准备 `blender_patch.commands` 时才读取本参考。每条命令都是包含 `op` 和操作专用参数的 JSON 对象。工具级 `project`、修订、哈希、观察 ID 与 Patch ID 不属于单独命令。

## 查找准确形状

[command-index.json](command-index.json) 由规范 Python 操作目录和函数签名生成。应搜索准确操作名，不要加载完整索引。没有 `=` 的参数为必需项；包含 `=` 的参数为可选项，并显示默认值。类型注解描述宿主侧接受的值。

不要臆造参数。外层 Patch 已经是原子操作，因此不要使用被排除的 `batch` 操作。创建项目属于 `blender_read(create_if_missing=true)`，接纳属于 `blender_acknowledge`，持久化证明属于 `blender_verify`。

只读目录操作被有意排除：使用 `blender_read`，不要把发现或检查操作放入 Patch。

## 正确引用片段

- 操作接受 `video_ai_id` 时，优先使用目标读取返回的稳定 ID。
- 操作只接受 `target` 时，传入同一次最新读取中的当前片段名称。不要假设每个旧 target 字段都接受 ID。
- 绝不猜测片段标识符。所需字段未返回时，Patch 前执行更窄的 detail 读取。

## 时间与路径

- 精确到帧的工作优先使用帧字段（`frame_start`、`frame_end`、`at_frame`、`frames`）。只有操作需要时才使用以秒计的源/时间线字段，避免意外混合单位。
- 媒体、字幕、字体、清单、渲染、复制和打包路径使用绝对路径。不要臆造缺失源路径，也绝不能用渲染覆盖源素材。
- 代理在 Blender 外部生成。`attach_proxy` 使用已经验证的外部 `manifest_path`；`detach_proxy` 和 `clear_proxies` 不授予删除文件的权限。

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

在 detail 读取返回当前名称后，原子应用两条相关编辑：

```json
[
  {"op": "trim_strip", "target": "Interview_A", "frame_end": 420},
  {"op": "set_volume", "target": "Interview_Audio", "volume": 0.82}
]
```

把已验证时间线渲染到新的输出路径：

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

- `clear_vse`、删除、Ripple、Extract、覆盖、资产替换、检查点删除和恢复操作需要明确用户意图。
- `restore_checkpoint` 必须是所在 Patch 的唯一命令。控制器会创建可恢复的恢复前备份，并重新打开准确 GUI 项目。
- 只有确实需要一个原子事务时，才把渲染或打包与编辑放进同一 Patch；通常应先重新读取已完成编辑，再在新 Patch 中渲染。
- 每个 Patch 优先只表达一个连贯编辑动作。较小 Patch 的回滚、过期基线恢复和人工审查更容易理解。
