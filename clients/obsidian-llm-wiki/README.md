# LLM Wiki Obsidian 插件

薄客户端：只读 `.llm-wiki/control.json` 并调用本机 loopback API。不运行 LLM、不直接写 Wiki 或草稿。

## 功能

- 状态栏待办计数（草稿、事实审核、待补充）
- 侧栏当前页上下文（来源、入链、出链）
- URL / 粘贴正文采集（`POST /api/v1/acquisitions/*`）
- 打开 Web 控制中心与局部图深链

## 前置条件

1. 本 Vault 即 LLM Wiki 根目录（含 `wiki/`、`raw/`、`.llm-wiki/`）。
2. 已启动服务：

```powershell
python tools/wiki.py serve
```

`serve` 会创建或更新 `.llm-wiki/control.json`（含稳定 `api_token`）。

## 手工安装

```powershell
cd clients/obsidian-llm-wiki
npm install
npm run build
```

将本目录复制到 Obsidian 插件文件夹，或使用符号链接：

```powershell
# Windows（以实际 Vault 路径替换）
mklink /D "%APPDATA%\Obsidian\plugins\llm-wiki" "D:\path\to\LLM-Wiki\clients\obsidian-llm-wiki"
```

在 Obsidian → 设置 → 社区插件 中启用 **LLM Wiki**。

## 开发

```powershell
npm run dev
```

修改 TypeScript 后重新加载 Obsidian 插件即可。

## 命令

| 命令 | 说明 |
| --- | --- |
| 打开 LLM Wiki 控制中心 | 浏览器打开 Web UI |
| 打开 LLM Wiki 侧栏 | 显示当前 wiki 页上下文 |
| 提交 URL 采集 | 弹窗提交 URL |
| 粘贴正文采集 | 弹窗提交标题与正文 |

## 边界

插件**不会**：

- 接受或丢弃草稿
- 永久删除资料
- 写入 `.llm-wiki/` 运行时状态
- 在服务端未启动时伪造处理进度

以上操作请在 Web 控制中心完成。

## MCP（可选）

另可启动薄 MCP 服务供 Cursor 等 Agent 只读查询：

```powershell
python tools/wiki.py mcp          # stdin/stdout JSON-RPC
python tools/wiki.py mcp --http   # http://127.0.0.1:8766
```

MCP 仅暴露 `status_summary`、`search`、`list_drafts`、`list_acquisitions`；不包含 apply/remove。
