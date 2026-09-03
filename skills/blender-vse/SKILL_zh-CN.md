# Blender VSE Skill 中文说明

[English version](SKILL.md)

本 Skill 通过四个带修订保护的 Blender MCP 工具，执行低上下文、聚焦的视频编辑与验证。适用于 `.blend` 时间线、片段、字幕、音频、代理、渲染、检查点和续作任务；生成源素材时可搭配创作 Skill。不要用于一次性纯 FFmpeg 编辑，也不要执行任意 Blender Python。

把明确指定的 `.blend` 文件视为可编辑事实源。只使用 `blender_read`、`blender_patch`、`blender_acknowledge` 和 `blender_verify`，绝不能用原始 `bpy`、Shell 驱动 Blender 脚本或隐藏无头编辑器代替。

## 建立边界

- 在用户通过 `BLENDER_VSE_PROJECTS_DIR` 确认绝对项目目录前，不能把新安装视为就绪。变量未配置时，创建项目之前先询问可编辑 `.blend` 应保存在哪里。绝不能选择插件缓存、市场 Checkout 或临时 Clone。
- 项目及引用媒体优先使用 `<workspace>/blender-vse-projects`。没有工作区时建议先打开一个。用户选择工作区外目录时，说明沙盒/可移植性取舍并取得明确确认；绝不能隐式迁移现有文件。
- 要求显式 `.blend` 路径，不扫描文件系统寻找项目。
- 四个工具不可用时停止，并说明必须安装和配置本地 MCP 服务。不得用任意 Python 模仿。
- 路径位于已配置根目录之外属于授权/配置问题，不移动或复制项目来规避。
- 只有用户明确要求创建准确项目时，才设置 `create_if_missing=true`。检查和续作绝不隐式创建缺失文件。

## 选择工作流

- 检查、解释或诊断只读；除非用户同时要求修改/接纳状态，否则不执行 Patch 或 acknowledge。
- 创建或编辑使用下方观察式编辑循环。
- 暂停、交接、压缩或状态不确定后的续作，假定先前观察已经过期，从新的摘要读取开始。
- 发生失败时，只有结构化错误指出具体分支后才读取 [recovery_zh-CN.md](references/recovery_zh-CN.md)。

## 观察式编辑循环

1. 对准确项目调用 `blender_read`，使用 `view="summary"`。
2. 只读取任务需要的区域：
   - `range` 需要 `frame_range`，适合有界时间线范围；
   - `detail` 需要片段 ID、通道、片段类型或帧范围，适合修改已命名片段前使用；
   - 只加入必需 `include` 组：`text`、`source`、`transform`、`audio`、`proxy` 或 `metadata`；
   - `has_more` 为 true 时，使用完全相同查询跟随 `next_cursor`。
3. 理解已观察时间线，形成一个连贯命令批次。构造命令时读取 [commands_zh-CN.md](references/commands_zh-CN.md)，然后只在 [command-index.json](references/command-index.json) 中查找所需操作。
4. 对同一个显式项目调用 `blender_patch`，传入最新读取的 `revision`、`timeline_hash` 与 `observation_id`。生成一个稳定、唯一的 `patch_id`；只有重试完全相同批次时才能复用。
5. 再次调用 `blender_read`。绝不能从 Patch 回执构造第二个 Patch，也不能复用观察 ID。
6. 只在需要时重复目标读取 → Patch → 读取。修改完成后调用 `blender_verify`；已知预期片段数量时可以一并提供。

只有显式旧版/调试请求且有界视图无法回答时，才使用 `view="full"`。不得把它作为日常编辑准备。

## 人工修改

变化后的时间线属于用户。任何后续动作前必须读取并理解新状态。如果新状态与请求工作兼容，可用 `blender_acknowledge` 接纳准确观察，然后再次读取。如果与用户意图冲突或选择不明确，则停止并询问。绝不能接纳未见状态，也不能用 acknowledge 绕过过期 Patch。

## 上下文状态

不断增长的对话上下文属于 Agent 宿主，不属于 MCP 服务。只维护紧凑恢复胶囊：

- 显式项目路径与当前用户意图；
- 最后确认的修订和时间线哈希；
- 有界近期 Patch ID、已完成动作、相关稳定片段 ID 与已验证输出；更早历史只保留总数与摘要；
- 未解决编辑决定与下一次目标读取。

压缩或交接后不保留观察 ID、游标、完整片段转储、原始日志或窗口诊断。恢复时从摘要读取开始，并在任何修改前取得新的目标观察。

## 完成条件

只有 Patch 后读取符合预期时间线，且 `blender_verify` 确认持久化，编辑才算完成。报告项目路径、已应用编辑、返回时的最终已验证修订/哈希、输出路径，以及任何警告或未决选择。API 返回成功本身不能证明请求的视觉结果或渲染正确。
