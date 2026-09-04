# 操作目录

[English version](operations.md)

操作目录由 `src/blender_vse/catalog.py` 生成。应用代码应通过 CLI 查询目录，不要复制完整列表：

```bash
blender-vse ops
blender-vse ops --family subtitles
blender-vse ops --family render
```

JSON 响应包含：

- `operations`：所有公开底层操作名称；
- `families`：将每个公开操作分配到唯一的功能族；
- `read_only`：绝不保存时间线变化的操作；
- `headless`：允许在后台 Blender 进程中运行的操作；
- `project_optional`：原生媒体检查等不要求 `.blend` 路径的操作；
- `control_plane`：检查点恢复等高级 Patch 命令；
- `internal`：对公开路由隐藏的实现原语；
- `removed`：带稳定迁移错误的旧操作；
- `error_codes`：操作结果 Schema 接受的完整稳定错误码集合。

## 公开操作与控制平面操作

大多数修改时间线的操作都会以公开命令名提供，但仍必须通过受修订保护的 `BlenderVSE.patch` 执行。`restore_checkpoint` 是例外：它必须是 Patch 中的唯一命令，因为控制器需要关闭对应的 GUI 项目、替换文件、重新打开项目、验证其可见性，并完成新修订。

`validate_checkpoint_restore` 和 `finalize_checkpoint_restore` 属于内部操作。适配器实现包含这两个操作，但公开路由不提供它们。

## 外部化职责

代理媒体生成和项目级资产注册表由 Agent 宿主应用负责。本包只接收已验证的代理清单和资产绑定，不负责管理这两个系统。

## 添加操作

1. 在 `blender/vse_ops.py` 中添加固定的类型化脚本模板。
2. 在 `catalog.py` 中把名称分配给唯一功能族。
3. 在操作目录的只读、无头和项目参数可选集合中正确标记该操作。
4. 将其加入编辑命令 Schema。
5. 添加快速验证，以及至少一条相关的 Blender 集成测试断言。
6. 运行 `python tests/run.py fast`；操作目录契约测试会拒绝缺失、重复或分类不一致的操作。
