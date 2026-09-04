# Python 与 CLI API

[English version](api.md)

## 推荐的 Python 边界

`BlenderVSE` 公开四个协作方法：

| 方法 | 用途 | 副作用 |
| --- | --- | --- |
| `read` | 返回修订号、时间线哈希、单次使用的观察 ID，以及选定的时间线投影 | 仅当 `create_if_missing=True` 时才可能创建项目 |
| `patch` | 验证已观察基线并原子应用类型化命令 | 修改并保存 `.blend` |
| `acknowledge` | 接纳调用方已明确观察并理解的人工修改 | 推进已接受修订 |
| `verify` | 在新的 Blender 进程中重新打开并验证持久化的片段数量 | 对时间线内容只读 |

`BlenderVSE.execute` 是类型化底层操作的备用入口。除非内部集成测试明确启用，否则适配器仍会拒绝直接编辑原语。应用应始终通过 `patch` 修改项目。

## 有界读取

`read` 默认使用 `view="summary"`，并接受：

```python
controller.read(
    "demo.blend",
    view="detail",                 # summary | range | detail | full
    frame_range=(1, 300),          # range 视图必需
    strip_ids=("clip-id",),       # 优先稳定 ID，也接受名称
    channels=(1, 3),
    strip_types=("MOVIE", "TEXT"),
    include=("text", "source"),
    cursor=None,
    limit=50,
)
```

`summary` 不返回片段。`range` 和 `detail` 返回有界分页，并在 `context.next_cursor` 中提供下一页游标。游标只对相同的修订、时间线哈希、选择器、`include` 字段组和 `limit` 有效。`full` 是显式兼容模式，不适合长期运行的 Agent 上下文。

执行 `patch` 前，必须立即使用最后一次定向读取返回的观察 ID。观察 ID 不得跨越上下文压缩或任务交接。

## 恢复胶囊辅助函数

`build_resume_capsule(...)` 创建确定性的上下文与交接记录，硬上限为 4 KB。它接收需要长期保留的项目意图、已确认的修订和哈希、近期相关历史、阻塞项、输出及下一步动作，并明确排除观察 ID 和游标。

```python
from blender_vse import build_resume_capsule

capsule = build_resume_capsule(
    project="/projects/demo.blend",
    objective="完成字幕时序",
    last_verified_revision=12,
    last_verified_timeline_hash="...",
    patch_ids=["subtitle-011", "subtitle-012"],
    relevant_strip_ids=["subtitle-42"],
    next_action="读取摘要，然后读取 subtitle-42 详情",
)
```

历史字段仅保留有限数量的近期条目，并记录被省略历史的摘要和数量。序列化契约见 [`resume-capsule.schema.json`](../src/blender_vse/schemas/resume-capsule.schema.json)。

## 结果封装

方法返回字典，便于通过以 JSON 为接口的工具边界传递：

```json
{
  "ok": false,
  "op": "patch",
  "error": {
    "code": "stale_base",
    "message": "Timeline changed after it was read."
  }
}
```

`patch`、`acknowledge` 和 `verify` 的成功回执及错误封装都受 `context-policy.json` 的字节预算约束。Patch 回执不代表一次新的观察；其中的 `next_action` 会要求调用方重新读取。

不要根据消息文本决定分支，应使用 `ok` 和稳定的 `error.code`。相关恢复分组如下：

- `project_not_found`、`input_missing`：确认并解析明确的本地路径。
- `session_not_ready`、`project_mismatch`：恢复可见的 Blender 会话，不得切换或关闭包含未保存人工修改的项目。
- `stale_base`、`revision_mismatch`、`invalid_read_token`、`stale_observation`：重新读取，再决定是接纳状态还是重建 Patch。
- `patch_rolled_back`：检查命令输入；时间线没有被部分提交。
- `invalid_read_query`、`invalid_cursor`：修正选择器，或从第一页重新开始分页。
- `stale_cursor`：分页期间时间线已变化；丢弃已收集页并开始新的有界读取。
- `context_budget_exceeded`：减少可选字段组或缩小范围。
- `invalid_proxy_manifest`、`stale_proxy_source`：重建并重新验证外部代理清单。

## CLI

```text
blender-vse status
blender-vse context-policy
blender-vse ops [--family FAMILY]
blender-vse read PROJECT [--create] [--resolution W H] [--fps FPS] \
    [--view summary|range|detail|full] [--frame-range START END] \
    [--strip-id ID] [--channel N] [--type TYPE] [--include GROUP] \
    [--cursor CURSOR] [--limit N]
blender-vse patch PROJECT --base-revision N --base-timeline-hash HASH \
    --read-token TOKEN --patch-id ID --commands JSON_OR_@FILE
blender-vse acknowledge PROJECT --observed-revision N \
    --observed-hash HASH --read-token TOKEN
blender-vse verify PROJECT [--expected JSON_OR_@FILE]
blender-vse execute OP [--project PROJECT] [--params JSON_OR_@FILE]
```

所有命令都输出 JSON，失败时返回非零退出码。脚本中应优先使用 `@file.json` 输入，避免不同 Shell 的引号规则造成问题。

## Schema 列表

- [编辑命令](../src/blender_vse/schemas/edit-command.schema.json)
- [操作结果](../src/blender_vse/schemas/operation-result.schema.json)
- [时间线状态](../src/blender_vse/schemas/timeline-state.schema.json)
- [媒体信息](../src/blender_vse/schemas/media-info.schema.json)
- [外部代理清单](../src/blender_vse/schemas/proxy-manifest.schema.json)
- [有界读取查询](../src/blender_vse/schemas/read-query.schema.json)
- [有界读取结果](../src/blender_vse/schemas/read-result.schema.json)
- [恢复胶囊](../src/blender_vse/schemas/resume-capsule.schema.json)
- [上下文策略](../src/blender_vse/context-policy.json)
