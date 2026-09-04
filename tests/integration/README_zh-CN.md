# Blender 集成测试

[English version](README.md)

这些脚本会执行真实的 Blender 行为，因此有意排除在默认 pytest 收集范围之外。请通过档位
运行器执行，确保测试素材、执行策略、超时和直接修改例外始终受控：

```bash
python tests/run.py blender-headless
python tests/run.py blender-smoke
python tests/run.py blender-full
```

`blender-smoke` 是标准的发布前 GUI 门槛。它会在不使用内部修改旁路的情况下执行一次公开
read/patch/read/patch/read/verify 工作流。`blender-full` 还会运行全部已登记的集成工作流。

合成媒体仅使用 FFmpeg 生成一次。项目只会写入已忽略的 `projects/` 目录。请关闭个人项目：
会话守卫会拒绝另一个已打开的 `.blend`，但完整档位会执行大量修改，并且必须串行运行。

有关档位预算和 CI 职责，请参阅[测试指南](../../docs/testing_zh-CN.md)。
