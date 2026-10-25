# 安装

[English version](installation.md)

## 一键安装

Linux 与 macOS：

```bash
curl -LsSf https://raw.githubusercontent.com/Aoike123/blender-vse/main/install.sh | sh
```

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Aoike123/blender-vse/main/install.ps1 | iex"
```

脚本会：

1. 在缺少 [uv](https://docs.astral.sh/uv/) 时，用官方安装程序安装它。
2. 运行 `uv tool install`，在 uv 托管的 Python 3.12 上安装 `blender-vse` 与
   `blender-vse-mcp` 命令，无需系统 Python。
3. 查找 Blender，并告诉你找到的位置或下载地址。

脚本不会修改 MCP 宿主的配置。设置 `BLENDER_VSE_REF` 可安装其他 git 引用，设置
`BLENDER_VSE_SOURCE` 可从分支仓库或本地检出安装。

## 注册服务

像添加其他 MCP 服务器一样，把 `blender-vse-mcp` 作为 stdio 服务器加入宿主。它不需要参数，
也不需要环境变量。服务自带 `blender-vse` Skill：核心规则作为服务说明自动下发，完整 Skill
可通过 `blender-vse` 提示词和 `blender-vse://skill/...` 资源获取。只有生成代理媒体和测试素材
时才需要 FFmpeg。

## 工程保存位置

工程始终保存在宿主启动服务时所在文件夹（通常就是你的工作文件夹）下的
`blender-vse-projects/` 中。工具使用相对于它的路径，例如 `demo.blend` 或 `cuts/v2.blend`，
越出该文件夹的路径会被拒绝。文件夹会在创建第一个工程时自动生成。由于任何地方都不保存
绝对路径，工作文件夹移动或改名后，所有工程依然可用。

如果某个宿主不在工作文件夹中启动 MCP 服务，请在该宿主的服务配置里把
`BLENDER_VSE_WORKSPACE` 设为工作文件夹。

## 更新与卸载

重新运行安装命令即可更新。卸载命令：

```bash
uv tool uninstall blender-vse-control
```

## 从源码开发

贡献者改用可编辑模式安装：

```bash
python -m pip install -e ".[dev]"
blender-vse status
```
