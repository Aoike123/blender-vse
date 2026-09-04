# 变更记录

[English version](CHANGELOG.md)

## 0.1.0 - 2026-09-04

- 统一定位为面向持久 `.blend` 时间线的本地、修订安全 Agent 剪辑；有界上下文作为
  支撑保证，不再作为产品类别本身。
- 扩展包与插件的发现关键词，覆盖 Blender VSE、AI 视频编辑、MCP、NLE、Agent Skill、
  修订安全与本地优先工作流。
- 修复公开 GUI 冒烟流程：`set_text` 使用已观察到的片段名，后续读取仍使用稳定片段 ID。
- 在发布清单中补充缺失的分发内容校验命令。

- 独立 Blender VSE 控制包与 CLI。
- 带修订保护的 read、patch、acknowledge 与 verify 工作流。
- 具有显式项目根目录授权的四工具本地 MCP 服务。
- 使用有界读取与恢复胶囊的低上下文 Agent Skill。
- Codex、Claude Code 与 DSH 安装路径。
- uv 管理的 Python 3.12 运行时；插件用户无需系统 Python。
- 独立英文与中文文档。
