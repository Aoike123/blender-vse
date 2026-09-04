# 发布清单

[English version](RELEASING.md)

## 1. 元数据与文档

- [ ] 用发布日期替换 `CHANGELOG.md` 和 `CHANGELOG_zh-CN.md` 中的“尚未发布”。
- [ ] 保持 `pyproject.toml` 与 `src/blender_vse/__init__.py` 版本一致。
- [ ] 确认中英文文档索引均不含失效的本地链接。
- [ ] 记录实际验证过的 Blender/操作系统组合。
- [ ] 审阅中英文安全策略与第三方声明。

## 2. 自动化门槛

```bash
python tests/run.py fast
python tests/run.py coverage
python tests/run.py mcp
python tests/run.py plugin
python tests/run.py harness
python tests/run.py stateful
python tests/run.py blender-headless
python tests/run.py blender-smoke
```

```bash
python skills/blender-vse/scripts/generate_command_index.py --check
python scripts/build_plugin.py
python scripts/build_plugin.py --check
```

- [ ] 对 `skills/blender-vse` 运行当前宿主附带的 `skill-creator` 版
  `quick_validate.py`。
- [ ] 对仓库根目录运行当前宿主附带的 `plugin-creator` 版 `validate_plugin.py`。
- [ ] 确认没有命令达到硬超时；调查并记录运行器依据 `tests/test-plan.json` 中的限制报告的任何目标耗时超限。
- [ ] 修改 bpy 模板、修订哈希、时间线持久化或 Blender 版本支持后运行 `python tests/run.py blender-full`。
- [ ] 确认公开冒烟流程没有使用直接修改旁路。
- [ ] GUI 档位必须从 Blender 所在的同一交互式桌面运行，不能使用服务桌面或隔离的自动化桌面。

## 3. 构建与检查

```bash
python -m build
python tests/verify_distribution.py dist
```

- [ ] 源码分发包包含中英文文档、测试、测试计划 JSON、许可证、已验证的 Skill 和生成的命令索引。
- [ ] wheel 包含所有打包 Schema、上下文策略、内置 Bridge 与 MCP 适配器运行时。
- [ ] 两个 Python 分发包均包含 AGPL、Bridge MIT 许可证和 `THIRD_PARTY_NOTICES.md`。
- [ ] 在干净环境安装 wheel，运行 `blender-vse ops` 和 `blender-vse status`。
- [ ] 安装 wheel 的 `mcp` 可选依赖，确认 MCP 发现仅公开四个文档中列出的工具。
- [ ] 解压确定性插件归档，校验市场布局，并在一个新的 Codex 任务中完成安装和测试。

## 4. 发布

- [ ] 提交发布状态。
- [ ] 创建带说明的 `vX.Y.Z` 标签。
- [ ] 在托管平台发布版本，并附上兼容性结果。
- [ ] 只有确认所选包索引上的分发名称和维护者账号后，才发布 Python 构件。
- [ ] 验证已发布的哈希与安装说明。
