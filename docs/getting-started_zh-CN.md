# 入门指南

[English version](getting-started.md)

## 1. 前置条件

- 源码/CLI 开发需要 Python 3.10 或更高版本。Harness 插件用户无需系统 Python；安装流程会引导准备 `uv`，再由它提供托管 Python 3.12。
- 单独安装 Blender。
- 只有代理工作流和生成集成测试素材时需要 FFmpeg。

Blender 5.1 是当前主要验证目标。不要单独安装 `bpy` wheel；控制器使用 Blender 自带运行时。

## 2. 安装开发环境

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

如果 Blender 不在 `PATH`，请设置可执行文件：

```powershell
$env:BLENDER_VSE_BLENDER_EXECUTABLE = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

```bash
export BLENDER_VSE_BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender
```

在不修改项目的情况下验证发现结果：

```bash
blender-vse status
blender-vse context-policy
blender-vse ops --family revision
```

`status` 只做观察。第一次交互操作启动或连接 Blender 前，缺少活动会话属于正常情况。

## 3. 创建并读取项目

```bash
blender-vse read ./projects/demo.blend --create --resolution 1920 1080 --fps 30
```

保留结果中的以下字段：

- `revision`
- `timeline_hash`
- `observation_id`

它们共同证明下一次 Patch 基于哪个时间线状态。默认响应为有界摘要，不包含单独片段。

只检查准备编辑的范围：

```bash
blender-vse read ./projects/demo.blend \
  --view range --frame-range 1 300 --include text --limit 50

blender-vse read ./projects/demo.blend \
  --view detail --strip-id TEXT_STRIP_ID --include text
```

如果 `context.has_more` 为 true，使用同一查询并传入 `--cursor NEXT_CURSOR`。Patch 必须使用最后一次目标读取的观察字段。

## 4. 应用一个原子 Patch

当 Shell 引号超出简短示例时，把命令放入 JSON 文件：

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

Patch ID 是幂等键。重复一个已经成功的 ID 绝不能再次应用编辑。

## 5. 重新读取并验证

```bash
blender-vse read ./projects/demo.blend
blender-vse verify ./projects/demo.blend --expected '{"text":1}'
```

不要根据前一次 Patch 响应构造第二个 Patch。必须重新读取，取得新的一次性观察令牌。

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

result = controller.patch(
    "demo.blend",
    base_revision=base["revision"],
    base_timeline_hash=base["timeline_hash"],
    read_token=base["observation_id"],
    patch_id="patch-title-001",
    commands=[
        {
            "op": "set_text",
            "video_ai_id": "text-strip-id",
            "text": "更新后的标题",
        }
    ],
)
```

结果与错误处理见 [API 参考](api_zh-CN.md)。

## Agent 宿主 MCP

以上 CLI 和 Python 示例无需 Agent 框架即可运行。如需向 Codex、Claude 或其他 MCP 宿主公开同一套修订安全流程，请继续阅读[本地 MCP 服务指南](mcp_zh-CN.md)。MCP extra 是可选项，不会改变四步 API 契约。
