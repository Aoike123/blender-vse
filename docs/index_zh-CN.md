# 文档

[English documentation](index.md)

Blender VSE Control 是面向 Agent 辅助剪辑的本地控制层，为持久化的 `.blend` 时间线提供具备修订保护的编辑能力。Blender 始终作为可编辑的事实源；每次写入都基于最新观察，从而防止 Agent 静默覆盖人工修改。

如果需要全流程自动化，建议与可用的导演或制作编排 Skill 搭配使用。上层负责创意方向、
分镜、源素材和验收标准；Blender VSE Control 负责执行明确的时间线修改，并验证保存后的
`.blend`。职责边界详见[架构](architecture_zh-CN.md)。

代理编码和重建不在本项目的职责范围内；本项目只验证并附加外部生成的代理清单。`blender_verify` 会在新的进程中重新打开项目，确认已保存的结构事实，但不会评估视觉质量或创意是否正确。仓库根目录的 [README](../README_zh-CN.md) 提供简要概览，详细契约则集中在此处。

## 使用项目

| 文档 | 用途 |
| --- | --- |
| [入门指南](getting-started_zh-CN.md) | 安装、检测 Blender、创建项目并执行第一次 `patch` |
| [Python 与 CLI API](api_zh-CN.md) | 公开方法、结果封装结构、错误和命令行语法 |
| [操作目录](operations_zh-CN.md) | 操作类别、公开/内部边界，以及添加操作的方法 |
| [配置](configuration_zh-CN.md) | 环境变量、执行策略和运行时目录 |
| [上下文模型](context-model_zh-CN.md) | 有界读取、分页、压缩和恢复规则 |
| [本地 MCP 服务](mcp_zh-CN.md) | 安装、授权项目根目录、连接宿主，以及使用四个工具 |
| [`blender-vse` Skill](../skills/blender-vse/SKILL_zh-CN.md) | 提示层的工具使用规范、命令路由、恢复，以及压缩后的续作 |
| [本地 Codex 插件](plugin_zh-CN.md) | 构建、安装、配置和验证 Skill 与 stdio 组合包 |
| [安装](installation_zh-CN.md) | Linux、macOS、Windows 一键安装，以及工程保存位置 |

## 理解与集成

| 文档 | 用途 |
| --- | --- |
| [架构](architecture_zh-CN.md) | 组件、信任边界、修订模型和执行模式 |
| [安全策略](../SECURITY_zh-CN.md) | 本地 Bridge 的威胁模型和漏洞报告方式 |

## 维护与发布

| 文档 | 用途 |
| --- | --- |
| [测试指南](testing_zh-CN.md) | 核心、MCP、Harness、有状态、无头、GUI 和完整测试档位 |
| [有状态评估语料库](../evals/README_zh-CN.md) | 长会话、压缩、冲突、恢复和负向路由场景 |
| [测试目录指南](../tests/README_zh-CN.md) | 测试和机器可读计划的存放位置 |
| [贡献指南](../CONTRIBUTING_zh-CN.md) | 变更流程和验收标准 |
| [发布清单](../RELEASING_zh-CN.md) | 明确的发布前准入条件和归档检查项 |
| [变更记录](../CHANGELOG_zh-CN.md) | 各版本面向用户的变更 |

## 权威的机器可读事实源

为避免在正文中重复权威清单，请以以下机器可读文件为事实源：

- `src/blender_vse/catalog.py` 定义公开操作类别和执行分类。
- `src/blender_vse/schemas/*.json` 定义外部 JSON 契约。
- `src/blender_vse/context-policy.json` 定义上下文预算和压缩字段。
- `tests/test-plan.json` 定义测试档位、要求、超时和预算。
- `pyproject.toml` 定义软件包、pytest 和覆盖率配置。
- `CHANGELOG.md` 记录发布层面的行为变更。
