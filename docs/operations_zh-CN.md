# 操作目录

[English version](operations.md)

操作目录由 `src/blender_vse/catalog.py` 生成。应用代码应调用 CLI，不要复制完整列表：

```bash
blender-vse ops
blender-vse ops --family subtitles
blender-vse ops --family render
```

JSON 响应包含：

- `operations`：所有公开底层操作名称；
- `families`：每个公开操作只分配到一个功能族；
- `read_only`：绝不保存时间线变化的操作；
- `headless`：允许在后台 Blender 进程中运行的操作；
- `project_optional`：原生媒体检查等不要求 `.blend` 路径的操作；
- `control_plane`：检查点恢复等高层 Patch 命令；
- `internal`：对公开路由隐藏的实现原语；
- `removed`：带稳定迁移错误的旧操作；
- `error_codes`：操作结果 Schema 接受的完整稳定错误码集合。

## 公开操作与控制平面操作

大多数时间线变更都是公开命令名，但仍必须在具有修订保护的 `BlenderVSE.patch` 中执行。`restore_checkpoint` 不同：它必须是 Patch 的唯一命令，因为控制器会关闭准确的 GUI 项目、替换文件、重新打开、证明可见性并完成新修订。

`validate_checkpoint_restore` 和 `finalize_checkpoint_restore` 属于内部操作。它们存在于适配器实现中，但不属于公开路由。

## 外部化职责

代理生成和项目级资产注册表属于宿主应用。本包接收已验证代理清单和资产绑定，但不声明拥有这些系统。

## 添加操作

1. 在 `blender/vse_ops.py` 添加固定、类型化的脚本模板。
2. 在 `catalog.py` 中把名称分配给唯一功能族。
3. 在目录只读/无头/项目可选集合中正确标记。
4. 加入编辑命令 Schema。
5. 添加快速验证以及至少一条相关 Blender 集成断言。
6. 运行 `python tests/run.py fast`；目录契约测试会拒绝缺失、重复或分类不一致的操作。
