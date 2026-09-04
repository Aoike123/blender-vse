# 入门指南

[English version](getting-started.md)

## 1. 前置条件

- 源码开发或 CLI 开发需要 Python 3.10 或更高版本。通过 Harness 插件安装的用户无需准备系统 Python；安装流程会初始化 `uv`，再由 `uv` 提供托管的 Python 3.12 环境。
- Blender 需要单独安装。
- 只有代理媒体工作流和集成测试素材生成需要 FFmpeg。

Blender 5.1 是目前的主要验证版本。不要单独安装 `bpy` wheel；控制器会直接使用 Blender 自带的运行时。

## 2. 安装开发环境

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

如果 Blender 不在 `PATH` 中，请指定其可执行文件的路径：

```powershell
$env:BLENDER_VSE_BLENDER_EXECUTABLE = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

```bash
export BLENDER_VSE_BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender
```

在不修改任何项目的情况下，确认控制器能否发现运行环境：

```bash
blender-vse status
blender-vse context-policy
blender-vse ops --family revision
```

`status` 命令只会观察运行环境。首次交互操作启动 Blender 或连接到 Blender 之前，没有活动会话是正常的。

## 3. 创建并读取项目

```bash
blender-vse read ./projects/demo.blend --create --resolution 1920 1080 --fps 30
```

保存响应中的以下字段：

- `revision`
- `timeline_hash`
- `observation_id`

这些字段共同标识下一份补丁必须基于的确切时间线状态。默认响应只返回一份有长度限制的摘要，不会列出各个片段。

只检查准备编辑的时间线范围：

```bash
blender-vse read ./projects/demo.blend \
  --view range --frame-range 1 300 --include text --limit 50

blender-vse read ./projects/demo.blend \
  --view detail --strip-id TEXT_STRIP_ID --include text
```

如果 `context.has_more` 为 true，请使用 `--cursor NEXT_CURSOR` 重复同一查询。构建补丁时，必须使用最近一次定向读取所返回的观察字段。

## 4. 应用一个原子补丁

如果命令内容过于复杂，不适合直接在 Shell 中安全引用，请将命令放入 JSON 文件：

```json
[
  {
    "op": "add_text",
    "text": "你好",
    "channel": 3,
    "frame_start": 1,
    "length": 90
  }
]
```

```bash
blender-vse patch ./projects/demo.blend \
  --base-revision 0 \
  --base-timeline-hash HASH_FROM_READ \
  --read-token TOKEN_FROM_READ \
  --patch-id patch-title-001 \
  --commands @commands.json
```

补丁 ID 是幂等键。重复使用已成功执行的补丁 ID 时，不得再次应用相同的编辑。

## 5. 重新读取并验证

```bash
blender-vse read ./projects/demo.blend
blender-vse verify ./projects/demo.blend --expected '{"text":1}'
```

切勿根据上一次补丁响应构建下一份补丁。请重新读取项目，获取新的、仅可使用一次的观察 ID。

## 等价 Python 用法

```python
from blender_vse import BlenderVSE

controller = BlenderVSE()
controller.read("demo.blend")  # 有界项目摘要
observed = controller.read(
    "demo.blend",
    view="detail",
    strip_ids=("text-strip-id",),
    include=("text",),
)
base = observed["data"]
title = base["strips"][0]

result = controller.patch(
    "demo.blend",
    base_revision=base["revision"],
    base_timeline_hash=base["timeline_hash"],
    read_token=base["observation_id"],
    patch_id="patch-title-001",
    commands=[
        {
            "op": "set_text",
            "target": title["name"],
            "text": "更新后的标题",
        }
    ],
)
```

有关结果与错误处理方式，请参阅 [API 参考](api_zh-CN.md)。

## 由 Agent 托管的 MCP

以上 CLI 和 Python 示例无需 Agent 框架即可运行。如需让 Codex、Claude 或其他 MCP 宿主使用同一套具备修订保护的工作流，请继续阅读[本地 MCP 服务指南](mcp_zh-CN.md)。MCP 扩展依赖为可选项，不会改变四步 API 契约。
