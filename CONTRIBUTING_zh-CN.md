# 贡献指南

[English version](CONTRIBUTING.md)

欢迎贡献。请保持本包独立于 Agent 框架、生产数据库、下载器和媒体服务商。

## 开发环境

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python tests/run.py fast
```

`fast` 是日常内部循环，目标为三秒。选择 Blender 档位前先运行 `python tests/run.py list`。

## 变更应放在哪里

- 公开 API 与协作策略：`src/blender_vse/api.py`
- 操作名称与分类：`src/blender_vse/catalog.py`
- 固定 bpy 模板：`src/blender_vse/blender/vse_ops.py`
- 执行与会话策略：`src/blender_vse/blender/runner.py` 和 `live_session.py`
- 序列化契约：`src/blender_vse/schemas`
- 上下文视图与预算：`src/blender_vse/context.py` 和 `context-policy.json`
- 压缩胶囊构建：`src/blender_vse/resume.py`
- MCP 工具及授权边界：`src/blender_vse/mcp`
- Agent 工作流与生成的命令索引：`skills/blender-vse`
- 本地插件元数据与启动契约：`.codex-plugin/plugin.json` 和 `.mcp.json`
- 确定性插件归档：`scripts/build_plugin.py`
- 便携客户端配置：`scripts/print_mcp_config.py`
- 测试档位与预算：`tests/test-plan.json`
- 用户文档：`docs`，由 `docs/index_zh-CN.md` 统一链接

## 变更检查清单

1. 先添加聚焦的单元或契约回归测试。
2. 新增 bpy 操作必须固定、类型化并经过 JSON 编码；禁止暴露任意 Python。
3. 每个公开操作只登记到一个目录功能族，并更新编辑命令 Schema。
4. 有界读取必须符合机器可读上下文策略，绝不能产生零进度游标。
5. 只有宿主侧测试无法证明行为时才增加真实 Blender 覆盖。
6. 公开冒烟档位保持精简；更广的脚本登记到 `blender-full`。
7. 运行 `python tests/run.py fast` 与 `python tests/run.py coverage`。
8. 命令签名变化后运行 `python skills/blender-vse/scripts/generate_command_index.py`，并提交生成的索引。
9. 行为变化时更新公开文档与 `CHANGELOG.md`、`CHANGELOG_zh-CN.md`。

修改插件元数据或 stdio 启动命令时，还必须运行 `python tests/run.py plugin` 以及当前 Codex 安装附带的 `plugin-creator` 校验器。

修改上下文预算、压缩状态、观察状态转换或 Skill 恢复规则时，必须运行 `python tests/run.py stateful`；若行为有意变化，还要更新面向模型的场景语料。

涉及会话身份、持久化、检查点恢复、代理验证或直接修改策略的拉取请求，还应在可见桌面 Blender 环境运行 `python tests/run.py blender-smoke`。

档位边界与安全规则见[测试指南](docs/testing_zh-CN.md)。
