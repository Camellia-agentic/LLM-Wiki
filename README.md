# Local LLM Wiki

一个本地、Markdown 优先、由 LLM 协助维护的可追溯知识库。

远程仓库：[github.com/Camellia-agentic/LLM-Wiki](https://github.com/Camellia-agentic/LLM-Wiki)

```text
raw/inbox/  用户可编辑的收件箱
    -> 持久任务队列
raw/sources/  SHA-256 不可变原始资料
    -> 第一阶段：证据、概念、实体、冲突与风险分析（长文分块）
    -> 第二阶段：候选 Wiki 页面
.llm-wiki/drafts/  草稿、Diff、基线与回滚
    -> 人工应用
wiki/  Obsidian 可浏览和编辑的结构化知识
```

它不是每次问答都临时拼接原文的传统 RAG。资料先沉淀为带来源的 Wiki 页面，再参与搜索、问答、综合分析和双链导航；模型不能绕过草稿闸门静默修改 Wiki。

## 当前能力

- 导入本地 `.md`、`.markdown` 和 `.txt`；**公开 URL** 与**粘贴正文**采集（Web 或 API）。
- 监听 `raw/inbox/`，稳定保存后自动入队、归档和处理。
- **长文分块分析**（不再静默截断前 14,000 字符）。
- 按 SHA-256 / 正文 digest 创建不可变来源版本；同 URL 正文不变时不重复快照。
- 两阶段模型分析，分析快照与页面草稿分离。
- 草稿 Diff、人工应用/丢弃、基线冲突检测、**草稿图谱差异预览**（graph-delta）。
- 未知 frontmatter 与 `## 人工补充` 保留。
- 事实核验与待补充分开，事实项必须有可定位的逐字原文引句。
- SQLite FTS5 + 中文 BM25 的 RRF 融合搜索。
- 基于 Wiki 页面、带页面引用约束的模型问答。
- 回收站、显式别名/合并、健康检查和本机控制中心（**收集 / 待处理 / 知识** 三工作区）。
- **语义关系**（frontmatter `relations:` + `## 关系`）与导航/语义图谱 API。
- Obsidian 双链、反向链接；可选 **Obsidian 薄插件**（`clients/obsidian-llm-wiki/`）。
- 薄 **MCP** 只读工具（`python tools/wiki.py mcp`）。
- **`config.toml`** 持久化模型端点（DeepSeek / OpenAI / Ollama 等 OpenAI 兼容服务）。

目标设计与未实现边界见 [采集、交互与知识图谱设计](docs/INTERACTION_AND_GRAPH_DESIGN.md)、[技术说明](docs/TECHNICAL.md)、[全流程验收](docs/ACCEPTANCE.md)、[路线图](docs/ROADMAP.md)。

## 前置条件

- Windows 与 Python 3.10+。
- 可选：DeepSeek、OpenAI、Ollama、LM Studio、vLLM 或其他 OpenAI 兼容模型服务。
- 可选：Obsidian。将仓库根目录作为 Vault 打开，不要只打开 `wiki/`。

核心命令只依赖 Python 标准库和 SQLite。未配置模型时仍可完成归档、确定性资料摘要、搜索和健康检查。

## 快速开始

```powershell
# 克隆后进入仓库
git clone git@github.com:Camellia-agentic/LLM-Wiki.git
cd LLM-Wiki

# 复制并编辑模型配置
copy config.toml.example config.toml

# 设置 API Key（DeepSeek 示例；密钥不要写入 config.toml）
$env:DEEPSEEK_API_KEY = "sk-..."

# 启动控制中心
python tools/wiki.py serve
```

浏览器打开 `http://127.0.0.1:8765/`。完整可复制验收步骤见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)。

## 本机控制中心

`config.toml` 支持 `deepseek`、`openai`、`ollama` 等配置档；`api_key_env` 填写**环境变量名**（如 `DEEPSEEK_API_KEY`），不是密钥本身。详见 [config.toml.example](config.toml.example)。

控制中心提供**收集**（文件 / URL / 粘贴）、**待处理**（草稿、核验、失败任务）、**知识**（搜索、预览、局部图）工作区。服务只绑定 `127.0.0.1` / `localhost`。

模型密钥从 `config.toml` 的 `api_key_env` 或启动时的 `LLM_WIKI_API_KEY` / `--api-key` 读取。不要把密钥写入 Git、日志或截图。

`serve` 和 `watch` 只在启动时读取代码、`config.toml` 和环境变量。更新工具或密钥后需停止旧进程并重新启动。

### 常见模型错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| HTTP 401 | 环境变量未设置，或把 `sk-...` 误写入 `api_key_env` | 在同一终端设置 `$env:DEEPSEEK_API_KEY`，`api_key_env` 保持为变量名 |
| HTTP 503 | 上游服务繁忙（如 DeepSeek `Service is too busy`） | 稍后重试、切换 `active` 配置档，或改用 Ollama 本地模型 |
| JSON 解析失败 | 模型返回不完整 JSON | 多为服务不稳定；API 恢复后 `refine` 重试 |

工具对 503 / 429 / 502 会自动退避重试。详见 [ACCEPTANCE.md 附录 A](docs/ACCEPTANCE.md#附录-a-常见-llm-错误排查)。

## Obsidian

1. 在 Obsidian 中选择「打开本地文件夹作为库」。
2. 选择本仓库根目录。
3. 从 `wiki/index.md` 开始阅读。

`[[wiki/...]]` 双链、反向链接和图谱会直接生效。建议在 Obsidian 图谱中使用 `-path:raw` 隐藏收件箱和原始资料。

Obsidian 负责深度阅读、编辑和人工补充；控制中心负责采集、草稿、问答与审核。

**Obsidian 薄插件**（可选）：见 [clients/obsidian-llm-wiki/README.md](clients/obsidian-llm-wiki/README.md)。需 `npm install && npm run build` 后手工安装。

`serve` 默认已包含 inbox 监听，不要对同一 Vault 同时再运行 `watch`。

## 导入资料

### 控制中心采集

启动 `serve` 后，在**收集**工作区可：

- 拖入或选择 Markdown/TXT 文件
- 提交公开 URL（后台抓取）
- 粘贴标题与正文

### 监听 Obsidian 收件箱

```powershell
python tools/wiki.py watch
```

默认每 2 秒扫描一次，文件连续 4 秒未变化后入队。`serve` 默认已启动同一 watcher；只需 Web/API 时用 `serve --no-watch`。

```powershell
python tools/wiki.py watch --once
```

### 命令行导入

```powershell
python tools/wiki.py ingest "path\to\note.md"
python tools/wiki.py ingest "path\to\notes" --recursive
```

不带模型时，导入立即创建确定性资料摘要。带模型时，默认创建草稿；只有 `--apply` 或 `draft accept` 才写入 Wiki。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `ingest <文件或目录> [--recursive] [--apply]` | 导入 Markdown/TXT；带模型时默认生成草稿 |
| `watch [--once] [--auto-accept]` | 无头监听收件箱 |
| `refine [raw/sources/文件] [--apply]` | 对已归档资料重新提炼 |
| `synthesize [主题] [--apply]` | 生成跨资料综合页面草稿 |
| `search <查询> [--top-k N] [--rebuild-index]` | 混合检索 Wiki |
| `ask <问题> [--top-k N] [--save]` | 基于检索页面问答 |
| `queue status/process/retry` | 查看、处理或重置持久任务 |
| `draft list/show/accept/discard` | 查看 Diff、应用或丢弃草稿 |
| `review list/resolve/reopen` | 处理事实核验和待补充 |
| `trash list/move/restore` | 隐藏或恢复资料 |
| `remove <资料> --yes` | 永久级联删除 |
| `topic alias/merge` | 显式别名或合并重复主题 |
| `status [--json]` | 收件箱、队列、草稿、审核和健康状态 |
| `rebuild` | 重建导航、概览和搜索索引 |
| `lint` | 检查断链、孤儿页和缺失来源 |
| `serve` | 启动本机控制中心和收件箱监听 |
| `mcp [--http]` | 薄 MCP（只读转发 loopback API） |

使用 `python tools/wiki.py <命令> --help` 查看完整参数。

## 模型配置

**推荐：使用 `config.toml`**

```toml
[llm]
active = "deepseek"   # 或 openai | ollama
```

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
python tools/wiki.py serve
```

**临时覆盖（Ollama 示例）：**

```powershell
ollama serve
ollama pull qwen3:8b

python tools/wiki.py refine `
  --llm-url "http://127.0.0.1:11434/v1/chat/completions" `
  --model "qwen3:8b"
```

安全输入 API Key：

```powershell
$secret = [System.Net.NetworkCredential]::new("", (Read-Host -AsSecureString "LLM API Key")).Password
$env:LLM_WIKI_API_KEY = $secret
Remove-Variable secret
```

## 质量闭环

```powershell
python tools/wiki.py queue status
python tools/wiki.py draft list
python tools/wiki.py review list --queue facts
python tools/wiki.py lint
python -B -m unittest discover -s tests -v
```

草稿审批、事实核验和待补充是三种不同操作；详见 [docs/CONTEXT.md](docs/CONTEXT.md)。

## Git 与提交

`.gitignore` 已排除不应入库的内容：

| 路径 | 原因 |
| --- | --- |
| `config.toml` | 可能含本地配置；用 `config.toml.example` 作模板 |
| `.llm-wiki/*` | 队列、草稿、索引等运行时状态 |
| `raw/inbox/*` | 待导入临时笔记（归档后进入 `raw/sources/`） |
| `.obsidian/workspace*.json` | Obsidian 个人窗口布局 |
| `clients/obsidian-llm-wiki/node_modules/` | 插件依赖 |

**应提交：** `wiki/`、`raw/sources/`（你的知识沉淀）、`llm_wiki/`、`web/`、`tools/`、`tests/`、`docs/`、`config.toml.example`。

若 Cursor 显示「非 Git 仓库」，可能是目录所有权问题，执行：

```powershell
git config --global --add safe.directory D:/Cusor_workspace/LLM-Wiki
```

## 当前限制

- `entitie` 等历史页面需通过可审阅草稿或迁移命令批量修正。
- Obsidian 插件需本地 `npm run build`；CI 尚未自动构建插件产物。
- 公开 URL 抓取受目标站点 robots / 反爬限制；部分页面需手工保存为 Markdown。
- DeepSeek 等服务在高峰期可能返回 503，需重试或切换提供商。
- `control.json` 中的客户端 token 不应进入 Git 或截图。

## 目录职责

```text
purpose.md              知识库方向与长期问题
AGENTS.md               Agent 维护边界和验证要求
config.toml.example     模型配置模板（复制为 config.toml）
llm_wiki/               业务包：分块、采集、API、图谱、MCP
tools/wiki.py           CLI 与服务入口
web/                    控制中心静态前端
clients/obsidian-llm-wiki/  Obsidian 薄插件源码
raw/inbox/              用户可编辑收件箱（Git 忽略内容）
raw/sources/            不可变原始资料
wiki/                   结构化 Wiki 页面
.llm-wiki/              工具运行时状态（Git 忽略）
tests/                  自动化测试（59+）
docs/                   设计、技术说明、验收与路线图
```

`.llm-wiki/` 运行时文件不能手工编辑。`wiki/reviews.md` 以 `.llm-wiki/reviews.json` 为准。

## 项目文档

- [知识库目标](purpose.md)
- [术语、状态与设计边界](docs/CONTEXT.md)
- [采集、交互与知识图谱设计](docs/INTERACTION_AND_GRAPH_DESIGN.md)
- [技术说明](docs/TECHNICAL.md)
- [全流程验收测试](docs/ACCEPTANCE.md)
- [Obsidian 集成决策记录](docs/obsidian.md)
- [后续路线图](docs/ROADMAP.md)
- [测试说明](docs/TESTING.md)
