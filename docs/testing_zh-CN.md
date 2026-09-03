# 测试

[English version](testing.md)

## 一份计划，九个档位

[`tests/test-plan.json`](../tests/test-plan.json) 是规范测试清单。[`tests/run.py`](../tests/run.py) 读取它、应用每套环境策略、执行超时、只生成一次合成素材并报告耗时。每次 Pytest 调用都会获得唯一的忽略 `.tmp` 根目录，其中包含档位、Python 版本、进程 ID 和时间戳；运行器结束后清理。这样可以避免操作系统临时目录冲突，也不会在矩阵任务、并发运行或不同本地身份之间复用。

缺少 Pytest、JSON Schema 验证、MCP、uv、Coverage、Blender 或 FFmpeg 时会在预检阶段失败，不会等到档位部分运行后才报错。

| 档位 | 运行内容 | Blender GUI | 目标 / 硬超时 |
| --- | --- | --- | ---: |
| `fast` | 核心单元与契约测试，不含 MCP SDK 测试 | 否 | 3 / 10 秒 |
| `coverage` | 同一核心测试及分支覆盖率 | 否 | 5 / 15 秒 |
| `mcp` | 安全边界、四工具、覆盖率及真实 stdio | 否 | 4 / 10 秒 |
| `plugin` | 精确 `.mcp.json` 命令与四工具发现 | 否 | 60 / 180 秒 |
| `harness` | 真实 Claude 清单验证及 DSH Skill/Cordis 组合 | 否 | 60 / 180 秒 |
| `stateful` | 场景回放及 250 轮上下文/压缩评估 | 否 | 5 / 15 秒 |
| `blender-headless` | 原生媒体检查器 | 否 | 15 / 60 秒 |
| `blender-smoke` | 一条公开 API 工作流 | 是 | 120 / 240 秒 |
| `blender-full` | 冒烟加全部已登记集成脚本 | 是 | 900 / 1200 秒 |

```bash
python tests/run.py list
python tests/run.py fast
python tests/run.py coverage
python tests/run.py mcp
python tests/run.py plugin
python tests/run.py harness
python tests/run.py stateful
python tests/run.py blender-smoke
```

脚本档位默认在第一次失败时停止以节约时间；需要完整回归报告时传入 `--keep-going`。使用 `--dry-run` 可查看精确命令而不启动 Blender。

目标耗时是性能信号，超过后报告为慢；硬超时是终止卡死进程的安全边界。二者分离可避免正常 CI 抖动产生错误失败。

无头档位显式关闭可选的实时一致性检查，因此恰好在运行的 Bridge 不会把它变成 GUI 测试。

插件档位首次运行可能准备本地 uv 环境，因此 60 秒目标包含依赖解析。它只列出 MCP 工具，不打开 Blender 或修改项目。Checkout 启动预热缓存后，解压归档启动会被强制离线。

Harness 档位是显式发布门槛，不是拉取请求 CI 任务。它通过固定 Claude Code CLI 严格验证并安装插件、持久化必需目录选项、连接插件 MCP 服务，并使用已安装 DSH CLI 组合 Skill/Cordis 状态。所有客户端状态隔离在仓库临时目录；首次运行可能需要 npm 访问，但不会编辑用户的 Claude 或 DSH 配置。

GUI 档位必须由连接到 Blender 同一交互桌面的进程运行。服务、沙盒和隔离桌面即使能枚举 Blender 窗口，也会正确返回 `gui_not_visible`；不得为让托管自动化通过而削弱检查。

## 快速门槛证明什么

快速门槛不需要 Blender，也不启动子进程，但覆盖范围超过普通单元测试。它与独立 MCP 门槛共同检查：

- 所有公开操作都能路由且只属于一个功能族；
- 适配器、路由、Schema、只读策略、无头策略、内部原语和已移除操作错误保持同步；
- 修订 API 的成功、回滚、过期基线、检查点与会话失败；
- summary/range/detail 过滤、分页、过期游标、UTF-8 字节截断与硬响应预算；
- 精确四工具 MCP 发现、生成输入守卫、内存协议调用、允许根目录拒绝及按项目串行；
- Skill 命令索引漂移、示例 Schema、精确 MCP 接口、依赖元数据、参考链接与指令/索引字节上限；
- 插件清单版本/路径完整性、审批策略、环境白名单、确定性市场归档与内置文件白名单；
- 恢复胶囊 Schema/预算/历史摘要和 Stateful 场景语料完整性；独立 Stateful 门槛测量 250 个编辑循环；
- 便携跨客户端配置、版本/协议一致性，以及确定性源码、wheel 和插件归档；
- Bridge 帧结构、分片 Socket 读取、回环策略与项目身份；
- Runner 模式选择、超时、结果解析与临时脚本清理；
- 代理清单哈希、路径包含、必需字段与过期源；
- 所有本地 Markdown 链接、中英文文档配对、包版本、许可证、源码清单以及测试计划/上下文策略条目。

参数化目录测试无需启动 140 个 Blender 进程即可覆盖所有公开操作。渲染与持久化行为留在 Blender 档位，因为使用 Mock 不能提供有效证据。

## 覆盖率范围

Coverage 档位测量确定性宿主侧 Python 和分支行为。固定 bpy 模板正文、内置 Blender Bridge 以及平台/GUI 专用实时会话状态机不计入核心数值阈值。无依赖 MCP 授权测试仍在核心覆盖率中，可选协议服务则有独立档位，在支持版本两端对 MCP 包执行更严格的 85% 分支阈值。排除的 Blender 代码仍具有聚焦协议/安全契约与真实 Blender 档位；强制用 Mock 覆盖每段嵌入脚本和操作系统分支只会提高数字、降低信心。阈值与排除项位于 `pyproject.toml` 和 `tests/test-plan.json`。

## 集成安全

- 素材由色块和正弦波过滤器生成，不提交不透明媒体。
- 项目与渲染只写入被忽略的仓库目录。
- 测试生成的 Blender 脚本与日志使用仓库忽略的 `.tmp`，不使用共享用户状态。
- GUI 档位串行执行，因为单个可见 Blender 会话拥有时间线；不得并行。
- 会话守卫拒绝切离另一个已打开的人工项目。
- 初始 GUI 证明失败时，冒烟 Harness 只关闭由自身启动且干净的空白或准确测试项目；绝不关闭脏项目或外部项目。
- `BLENDER_VSE_ALLOW_DIRECT_MUTATION=1` 只应用到指定旧测试；公开冒烟流程不使用。
- 运行完整档位前关闭个人 Blender 项目。

## CI 布局

CI 并行运行六个独立任务：

1. 在最小和最大支持 Python 版本运行快速测试；
2. 在主 Python 版本运行一次覆盖率；
3. 在最小和最大 Python 版本运行完整 MCP 契约及一次真实 stdio 子进程发现；
4. 在一个 Python 版本运行精确 uv 插件启动；
5. 运行确定性 Stateful/压缩场景评估；
6. 构建一次源码/wheel/插件，并进行归档与 CLI 冒烟检查。

MCP 测试与核心 fast/coverage 收集隔离，因此无关任务不会重复导入可选 SDK 和启动 stdio。一次构建取代过去每个 Python 矩阵项中的重复构建。Blender 档位仍是显式发布门槛，因为托管 Runner 无法提供必需的可见桌面证明。

## 添加测试

- 纯行为测试放入 `tests/unit`。
- 同步、Schema、文档、打包和测试计划检查放入 `tests/contract`。
- 真实 Blender 行为放入 `tests/integration`，每个新脚本登记到 `blender-full`。
- 只把最小代表性流程加入 `blender-smoke`。
- 保持 `fast` 三秒目标；优先使用参数化与 Fake，避免启动进程。
