# 贡献指南

[English version](CONTRIBUTING.md)

欢迎贡献。请勿让本包依赖 Agent 框架、生产数据存储、下载器或媒体服务商。

## 开发环境

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python tests/run.py fast
```

`fast` 是日常开发循环，目标耗时不超过三秒。选择 Blender 档位前，请先运行
`python tests/run.py list`。

## 变更应放在哪里

- 公开 API 与协作策略：`src/blender_vse/api.py`
- 操作名称与分类：`src/blender_vse/catalog.py`
- 固定的 `bpy` 操作模板：`src/blender_vse/blender/vse_ops.py`
- 执行与会话策略：`src/blender_vse/blender/runner.py` 和 `live_session.py`
- 序列化数据契约：`src/blender_vse/schemas`
- 上下文视图与预算：`src/blender_vse/context.py` 和 `context-policy.json`
- 上下文压缩胶囊：`src/blender_vse/resume.py`
- MCP 工具和授权边界：`src/blender_vse/mcp`
- Agent 工作流与生成的命令索引：`skills/blender-vse`
- 本地插件元数据与启动契约：`.codex-plugin/plugin.json` 和 `.mcp.json`
- 确定性插件归档：`scripts/build_plugin.py`
- 一键安装脚本：`install.sh` 与 `install.ps1`
- 测试档位与预算：`tests/test-plan.json`
- 用户文档：`docs`，由 `docs/index_zh-CN.md` 统一链接

## 变更检查清单

1. 先添加一个聚焦的单元或契约回归测试。
2. 新增 `bpy` 操作必须固定、类型化并经过 JSON 编码；禁止暴露任意 Python。
3. 每个公开操作只能登记到操作目录中的一个功能族，并同步更新编辑命令 Schema。
4. 有界读取的输出必须符合机器可读的上下文策略，且绝不能产生无法推进的游标。
5. 只有宿主侧测试无法证明相关行为时，才添加真实 Blender 覆盖。
6. 保持公开冒烟档位精简；覆盖范围更广的脚本应登记到 `blender-full`。
7. 运行 `python tests/run.py fast` 与 `python tests/run.py coverage`。
8. 命令签名发生变化后，运行 `python skills/blender-vse/scripts/generate_command_index.py`，
   并提交生成的索引。
9. 行为发生变化时，更新公开文档以及 `CHANGELOG.md` 和 `CHANGELOG_zh-CN.md`。

修改插件元数据或 stdio 启动命令时，还必须运行 `python tests/run.py plugin`，并使用当前
Codex 安装附带的 `plugin-creator` 校验器。

修改上下文预算、压缩状态、观察状态转换或 Skill 恢复规则时，必须运行
`python tests/run.py stateful`；若行为是有意调整，还要更新面向模型的场景语料。

涉及会话身份、持久化、检查点恢复、代理验证或直接修改策略的拉取请求，还应在可见的
桌面 Blender 环境中运行 `python tests/run.py blender-smoke`。

有关档位边界和安全规则，请参阅[测试指南](docs/testing_zh-CN.md)。
