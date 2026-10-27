# 变更记录

[English version](CHANGELOG.md)

## 未发布

- 新建工程改为打开 Blender 原生的 Video Editing 工作区（上方为文件浏览器、预览和属性，下方为
  通栏序列编辑器），该工作区从 Video Editing 应用模板追加，并移除出厂的 3D 工作区标签页。此前
  工作区是 Layout 的副本，带有大纲视图、物体属性、重复的播放时间线，以及一个合并的序列/预览区域。
- 打开 Video Editing 工作区缺少独立预览和时间线的工程时，会用原生工作区替换它；其他工作区保留。
- 新建、打开工程或执行 `configure_vse_layout` 时，工作区的文件浏览器会打开工程所在的工作文件夹
  （包含 `blender-vse-projects` 的那个文件夹）；已在该文件夹内的浏览器保持原位。
  `configure_vse_layout` 不再查找 `assets` 文件夹。
- 新建工程使用 Standard 色彩变换，取代出厂的 AgX（它会对所有片段做色调映射），截图和导出保持
  素材原色。
- `render_frame` 和 `generate_contact_sheet` 改为通过渲染百分比缩小截图，不再覆盖分辨率，
  文字等叠加元素保持真实大小和位置（此前会被放大，联系表中最多放大 6 倍）。联系表各格不再上下
  颠倒；`render_frame` 传 `frame=0` 时渲染第 0 帧，而不是播放头所在帧。
- `configure_vse_layout` 保留已经是文件浏览器和属性的区域，不再按位置挑选。

## 0.2.0 - 2026-10-25

- MCP 服务现在自带 `blender-vse` Skill：核心规则作为服务说明下发，完整 Skill 通过
  `blender-vse` 提示词提供，所有 Skill 文件均以 `blender-vse://skill/...` 资源提供。wheel
  已打包 Skill，一键安装无需插件即可获得。
- Skill 全面改用相对于工作文件夹的工程路径，并引导使用 `sample_frame` 做数值画面检查。
- 新增一键安装脚本：Linux/macOS 使用 `install.sh`，Windows 使用 `install.ps1`。脚本会在缺少
  uv 时安装它，并通过 `uv tool` 安装 `blender-vse-mcp` 命令；服务注册交由 MCP 宿主完成。
- 工程现在固定保存在 `<workspace>/blender-vse-projects` 中（workspace 为 MCP 宿主启动服务时
  所在的文件夹），工具接受相对路径，例如 `demo.blend`。移除了 `BLENDER_VSE_PROJECTS_DIR`、
  `VP_PROJECTS_DIR` 与 `BLENDER_VSE_ALLOWED_ROOTS`；不在工作文件夹中启动服务的宿主可使用
  `BLENDER_VSE_WORKSPACE`。
- 移除 Agent 引导式安装契约（`install-contract.json`、`blender_vse.installation`、DSH 安装
  脚本、配置打印脚本、Claude 的 `projects_dir` 选项以及客户端兼容性文档）。
- 项目许可证由 AGPL-3.0-only 改为 MIT 许可证；随附的 Blender MCP Bridge 保留原有
  MIT 声明。
- 修复 Blender 5 及以上版本序列编辑器预览中，未设置字体的 TEXT 条目被绘制成
  放大翻转的字形碎片而最终渲染却正常的问题：`add_text` 与
  `add_subtitle_track` 现在必定显式绑定可加载字体（优先通过 Blender 资源路径
  使用自带的 Inter / Noto Sans CJK，并复用已载入的字体），中文文本自动选择 CJK
  字体，并在候选全部失败时回执 `font_fallback_warning`，确保预览与渲染一致。
- Linux 可见会话检查现在通过 `xprop` 在 X11 下收集 Blender 进程的原生窗口
  证据；无法获取 X11 证据时保持原有行为。
- 新增 `sample_frame`：渲染单帧并返回有界的数值 RGB 网格（每轴最多 16 格，
  行序自上而下）、最小/最大/平均亮度及场景视图变换，让 Agent 用数值核验画面
  而不再依赖截图目测。
- `generate_contact_sheet` 改用 `scene.frame_set()` 逐帧步进，替代直接赋值
  `frame_current`，渲染循环期间可见预览与 depsgraph 保持同步。
- 补充 Blender VSE Control 与导演或制作编排 Skill 的全流程自动化搭配方式，明确创意规划、
  源素材、时间线执行和持久化验证分别由哪一层负责。

## 0.1.1 - 2026-09-04

- 重写全部 25 组中英文文档，使两种语言都自然、清晰，同时保留命令、契约和安全边界。
- 统一修订、观察 ID、定向读取、操作目录、允许列表、Agent 宿主和代理媒体等术语。
- 修复 Markdown 粗体边界，并新增粗体、标题间距和代码围栏的契约检查。
- 采用更简洁、易读的中英文社交预览标语，并重新生成经过校验的图片资产。
- 修正文档中关于 `set_text`、新项目路径、GUI 冒烟流程和持久化验证的示例与说明。

## 0.1.0 - 2026-09-04

- 将项目重新定位为面向持久 `.blend` 时间线、具备修订保护的本地 Agent 剪辑控制层；
  有界上下文是配套保证，而非产品类别本身。
- 扩充包和插件的检索元数据，覆盖 Blender VSE、AI 视频编辑、MCP、NLE、Agent Skill、
  修订保护和本地优先工作流。
- 修复公开 GUI 冒烟流程：`set_text` 传入观察到的片段名称，后续读取仍使用稳定片段 ID。
- 在发布清单中补充缺失的分发内容校验命令。
- 新增独立的 Blender VSE 控制包和 CLI。
- 带修订保护的 read、patch、acknowledge 与 verify 工作流。
- 提供明确项目根目录授权的四工具本地 MCP 服务。
- 通过有界读取和恢复胶囊节省上下文的 Agent Skill。
- Codex、Claude Code 和 DSH 安装方式。
- 由 `uv` 管理的 Python 3.12 运行时引导；插件用户无需安装系统 Python。
- 相互独立的中英文文档。
