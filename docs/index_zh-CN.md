# 文档总览

[English documentation](index.md)

Blender VSE Control 是面向 Agent 协同剪辑的本地、修订安全工程控制层，服务于持久、
可编辑的 `.blend` 时间线。Blender 始终保有可编辑事实源，每次写入基于最新观察，
避免 Agent 静默覆盖人工修改。

代理编码与重建不属于本项目；本项目只验证并附加外部生成的代理清单。
`blender_verify` 在新进程重新打开工程后确认已保存的结构事实，不判断视觉质量或创意
正确性。本页是独立中文文档入口，英文主文档与中文镜像通过契约测试保持配对。

## 使用项目

- [入门与首次编辑](getting-started_zh-CN.md)
- [Python 与 CLI API](api_zh-CN.md)
- [操作目录及公开/内部边界](operations_zh-CN.md)
- [环境变量与运行模式](configuration_zh-CN.md)
- [上下文预算、分页与压缩恢复](context-model_zh-CN.md)
- [本地 MCP 安装、目录授权与四工具工作流](mcp_zh-CN.md)
- [`blender-vse` Skill 的 Prompt、命令与恢复规则](../skills/blender-vse/SKILL_zh-CN.md)
- [本地 Codex 插件的构建、安装与验证](plugin_zh-CN.md)
- [Codex、Claude Code 与 DSH 安装及项目目录确认](installation_zh-CN.md)
- [Codex、Claude、DSH 与通用 MCP 客户端兼容性](clients_zh-CN.md)

## 理解与集成

- [架构、事实源与修订模型](architecture_zh-CN.md)
- [安全策略](../SECURITY_zh-CN.md)

## 测试与维护

- [测试档位、预算与 CI 分工](testing_zh-CN.md)
- [长流程、压缩、冲突与负向路由评估](../evals/README_zh-CN.md)
- [测试目录说明](../tests/README_zh-CN.md)
- [贡献指南](../CONTRIBUTING_zh-CN.md)
- [发布清单](../RELEASING_zh-CN.md)
- [变更记录](../CHANGELOG_zh-CN.md)

机器可读的事实源为 `src/blender_vse/catalog.py`、
`src/blender_vse/schemas/*.json`、`tests/test-plan.json` 和
`src/blender_vse/context-policy.json`、`pyproject.toml`；文档不复制完整操作或测试清单。
