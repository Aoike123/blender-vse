# Blender 集成测试

[English version](README.md)

这些脚本执行真实 Blender 行为，并被有意排除在默认 Pytest 收集之外。请通过档位运行器执行，确保素材、执行策略、超时和直接修改例外始终有界：

```bash
python tests/run.py blender-headless
python tests/run.py blender-smoke
python tests/run.py blender-full
```

`blender-smoke` 是正常发布前 GUI 门槛：它在没有内部修改旁路的情况下执行一次公开 read/Patch/read/Patch/read/verify 工作流。`blender-full` 还会运行全部已登记集成工作流。

合成媒体只通过 FFmpeg 生成一次。项目仅写入被忽略的 `projects/` 目录。请关闭个人项目；会话守卫会拒绝不同的已打开 `.blend`，但完整档位具有大量修改且必须串行运行。

档位预算和 CI 职责见[测试指南](../../docs/testing_zh-CN.md)。
