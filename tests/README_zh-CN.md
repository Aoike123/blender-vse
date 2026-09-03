# 测试目录布局

[English version](README.md)

- `unit/`：隔离宿主侧行为，不启动 Blender 进程。
- `contract/`：操作目录、Schema、文档、打包与测试计划漂移。
- `integration/`：真实 Blender 脚本，默认 Pytest 从不收集。
- `plugin/`：精确的打包 stdio 启动契约，不打开 Blender。
- `clients/`：在隔离状态验证真实 Claude 与 DSH 打包/配置。
- `evals/`：状态转换与长会话上下文/压缩评估。
- `fixtures/generate_media.py`：确定性本地媒体生成。
- `test-plan.json`：档位成员、依赖、超时与预算。
- `run.py`：跨平台档位运行器。

开发时运行 `python tests/run.py fast`；修改 MCP 边界后运行 `python tests/run.py mcp`；修改插件清单或启动命令后运行 `python tests/run.py plugin`。运行 GUI 档位前阅读[测试指南](../docs/testing_zh-CN.md)。修改 Claude 或 DSH 打包后运行 `python tests/run.py harness`；修改上下文预算、恢复规则或 Skill 状态转换后运行 `python tests/run.py stateful`。
