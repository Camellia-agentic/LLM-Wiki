# Local LLM Wiki

一个按 Karpathy LLM Wiki 模式搭建的本地、Markdown 优先知识库：

```text
raw/inbox/ (Obsidian 中可编辑的收件箱)
        -> 持久任务队列
raw/sources/ (按 SHA-256 归档的不可修改原始资料)
        -> 第一阶段：证据/风险分析快照
        -> 第二阶段：候选 Wiki 草稿 + Diff
        -> 人工应用后才更新 Wiki 页面
wiki/ (可在 Obsidian 中浏览的结构化知识)
        -> hybrid search / ask / 事实审核 / 回收站 / lint
```

它不是“每次问答都从原文拼接”的传统 RAG。每次导入会生成一份资料摘要，并可通过本地 LLM 逐步维护概念、实体、交叉引用、冲突与待复核项。`index.md` 和 `log.md` 分别承担内容导航和可追溯的时间线。

## 前置条件

- Windows 已安装 Python 3.10+（当前工作区已有 Python 3.12）。
- 可选：本地 OpenAI 兼容模型服务。Ollama、LM Studio、vLLM 均可。
- 可选：Obsidian。直接把本目录作为 vault 打开即可。

不需要数据库、Docker、向量库或额外 Python 依赖。

## 在 Obsidian 中打开

1. 启动 Obsidian，选择 **打开本地文件夹作为库（Open folder as vault）**。
2. 选择 `D:\Cusor_workspace\local-llm-wiki`，不要选择其中的 `wiki` 子目录。
3. 在文件列表中打开 `wiki/index.md` 作为入口；`[[wiki/...]]` 双链、反向链接和图谱视图会直接生效。

建议在图谱视图的过滤条件中填入 `-path:raw`，隐藏收件箱和原始资料，仅查看 LLM 维护的 Wiki 页面。Obsidian 负责写作、浏览和人工补充；导入状态、草稿 Diff、问答与审核由本机控制中心负责。

## 本机控制中心

在设置模型环境变量的 PowerShell 窗口启动一次：

```powershell
python tools/wiki.py serve `
  --llm-url "http://aiproxy.smoa.cc/smartmore/v1/chat/completions" `
  --model "DeepSeek-V4-Pro"
```

浏览器会打开 `http://127.0.0.1:8765/`。日常整理只需在该页面拖入资料、查看处理状态、审阅草稿 Diff、应用或丢弃变更、检索问答、处理事实核验或待补充事项、恢复资料；无需为这些操作重复输入终端命令。

服务默认监听 `raw/inbox/`，且模型生成内容默认进入草稿，不会静默改写 `wiki/`。`--auto-accept` 会恢复无人值守的直接应用模式，仅适合你已接受该风险的场景。服务只绑定 `127.0.0.1`，不会向局域网公开；API Key 仍只从启动进程的环境变量读取。

## 自动导入 Obsidian 笔记

在 Obsidian 的 `raw/inbox/` 中新建笔记或拖入 `.md` / `.txt` 文件。然后在本目录启动一次后台监听：

```powershell
python tools/wiki.py watch
```

监听器每 2 秒扫描一次，文件连续 4 秒未变动后进入 `.llm-wiki/queue.json`。任务会持久化状态、错误和尝试次数；中断后的 `processing` 任务会在下次启动时恢复为待处理，模型失败最多自动重试 3 次。配置模型时，资料会立即归档、分析快照会保存，而候选页面会进入草稿等待应用。修改同一收件箱文件会形成新的 SHA-256 归档版本，不覆盖已有来源。

`watch` 是启动时加载代码和环境变量的常驻进程。更新 `tools/wiki.py`、修改模型地址或更换 API Key 后，先按 `Ctrl+C` 停止旧监听器，再在设置好当前 PowerShell 会话环境变量的终端中重新启动；旧进程不会自动获得新功能或新密钥。

只想扫描现有收件箱一次时：

```powershell
python tools/wiki.py watch --once
```

## 快速开始

在本目录执行：

```powershell
# 1. 导入单个 Markdown 或 TXT 文件。原文件被复制到 raw/sources，之后不再被修改。
python tools/wiki.py ingest "..\\AAA文档汇总\\LLM_Wiki.md"

# 2. 递归导入一个目录中的 Markdown/TXT 文件。
python tools/wiki.py ingest "..\\AAA文档汇总" --recursive

# 3. 在 Wiki 页中检索（SQLite FTS5 + 中文 BM25 RRF 融合）。
python tools/wiki.py search "知识库如何持续维护"

# 4. 检查断链、孤儿页面与缺失来源。
python tools/wiki.py lint
```

不带模型参数时，`ingest` 会创建确定性的资料摘要、索引和日志，适合先完成资料归档与检索。

## 命令速查

所有命令都在知识库根目录运行。需要模型的命令共用 `--llm-url`、`--model`、`--api-key`（默认读取环境变量 `LLM_WIKI_API_KEY`）和 `--timeout`；`--max-tokens` 仅控制模型输出长度。

| 命令 | 用途 |
| --- | --- |
| `ingest <文件或目录> [--recursive] [--apply]` | 导入 Markdown/TXT；带模型时默认生成草稿，`--apply` 才直接写入。 |
| `search <查询> [--top-k N] [--rebuild-index]` | 用 FTS5 与中文 BM25 的 RRF 融合检索 Wiki；`--rebuild-index` 先重建索引。 |
| `ask <问题> --llm-url <地址> --model <模型> [--top-k N] [--save]` | 基于检索到的 Wiki 页面问答；`--save` 写入 `wiki/queries/`。 |
| `watch [--path <目录>] [--interval 秒] [--settle-seconds 秒] [--once] [--auto-accept]` | 监听收件箱；带模型时默认生成草稿。 |
| `refine [raw/sources/文件.md] --llm-url <地址> --model <模型> [--apply]` | 对全部或指定已归档资料重新提炼为草稿。 |
| `synthesize [主题] --llm-url <地址> --model <模型> [--top-k N] [--apply]` | 生成跨资料综合草稿；省略主题时综合全部资料摘要。 |
| `remove <raw/sources 路径或 wiki/sources 页面> --yes` | 级联删除一份资料及其独占派生页；共享概念和实体会保留。 |
| `review list [--status open\|resolved\|all] [--queue facts\|research\|all]`、`review resolve <ID>`、`review reopen <ID>` | 查看、处理或重新打开审核项；`facts` 仅显示带原文引句的事实，`research` 显示待补充。 |
| `queue status`、`queue retry <ID>`、`queue process [--max-attempts N]` | 查看、重置或手工处理持久导入队列；`process` 可带模型参数。 |
| `draft list`、`draft show <ID>`、`draft accept <ID>`、`draft discard <ID>` | 查看 Diff、应用或丢弃模型草稿。 |
| `trash list`、`trash move <资料>`、`trash restore <digest>` | 隐藏资料并可恢复；永久删除仍使用 `remove --yes`。 |
| `topic alias <类型> <页面> <别名>`、`topic merge <类型> <来源> <目标>` | 为疑似重复概念显式添加别名或合并；不会自动合并。 |
| `status [--json]`、`rebuild`、`serve` | 查看状态、重建派生索引或启动本机控制中心。 |
| `lint` | 检查断链、孤儿页与缺失来源。 |

可运行 `python tools/wiki.py <命令> --help` 查看某个子命令的完整参数。

## 质量闭环

配置模型后，每份资料先生成证据、概念、实体、风险的分析快照，再基于快照生成候选页面。分析快照存放在 `.llm-wiki/analyses/`，草稿存放在 `.llm-wiki/drafts/`；应用前会比较页面基线，发现人工修改则拒绝覆盖。

```powershell
# 查看或重试监听器中的失败任务
python tools/wiki.py queue status
python tools/wiki.py queue retry <任务ID>
python tools/wiki.py queue process --llm-url <endpoint> --model <model>

# 审阅文件变更草稿
python tools/wiki.py draft list
python tools/wiki.py draft show <草稿ID>
python tools/wiki.py draft accept <草稿ID>

# 只查看有原文证据的待核实事实
python tools/wiki.py review list --queue facts

# 查看待补充、待外部查证和旧版无引句记录
python tools/wiki.py review list --queue research
python tools/wiki.py review resolve <审核ID>

# 生成跨资料专题；不传主题时综合全部资料摘要
python tools/wiki.py synthesize "云原生基础设施" --llm-url <endpoint> --model <model>

# 删除一份归档资料及其摘要、独占概念/实体、审核项与死链
python tools/wiki.py remove raw/sources/文件名.md --yes
```

`ask` 只使用检索到的 Wiki 页面生成回答，要求模型引用 `[wiki/路径]`；引用缺失或越界时会自动重试一次，并在仍失败时附上依据页面。

事实核验和待补充是两条不同的队列。只有模型提供逐字原文引句、且工具能在归档资料中找到该引句的 `source_claim` 才会出现在“事实审核”；详情会显示工具计算的行号、原文引句、原始资料和对应 Wiki 页面，并可跳转到 Obsidian。缺漏建议、外部查证问题和旧版未保存引句的项目会进入“待补充”，不会被伪装成原文事实。处理任何项目时都应填写依据、结论或后续动作；记录会保留在队列中。草稿审批只决定是否应用文件变更，不替代事实核验。

## 连接本地模型

以 Ollama 为例，先启动兼容接口并下载任意中文/通用模型：

```powershell
ollama serve
ollama pull qwen3:8b
```

导入时加上模型配置，工具会先做结构化分析，再基于分析生成资料摘要、概念页、实体页和待复核项的草稿：

```powershell
python tools/wiki.py ingest "..\\AAA文档汇总\\LLM_Wiki.md" `
  --llm-url "http://127.0.0.1:11434/v1/chat/completions" `
  --model "qwen3:8b"
```

问答会检索 Wiki 页面，而不是把全部原始资料送入模型。添加 `--save` 可把有价值的回答回写到 `wiki/queries/`，让探索结果继续积累：

```powershell
python tools/wiki.py ask "这个知识库和传统 RAG 有何区别？" `
  --llm-url "http://127.0.0.1:11434/v1/chat/completions" `
  --model "qwen3:8b" --save
```

如服务要求鉴权，增加 `--api-key`。LM Studio 常用地址为 `http://127.0.0.1:1234/v1/chat/completions`；vLLM 则通常是 `http://127.0.0.1:8000/v1/chat/completions`。

### AI Proxy / vLLM

对于 OpenAI 兼容的 AI Proxy，建议把密钥只放入当前 PowerShell 会话的环境变量，不要写入笔记或命令参数：

```powershell
$secret = [System.Net.NetworkCredential]::new("", (Read-Host -AsSecureString "AI Proxy API Key")).Password
$env:LLM_WIKI_API_KEY = $secret
Remove-Variable secret

python tools/wiki.py watch `
  --llm-url "http://aiproxy.smoa.cc/smartmore/v1/chat/completions" `
  --model "DeepSeek-V4-Pro"
```

停止监听器或关闭该 PowerShell 后，使用 `Remove-Item Env:LLM_WIKI_API_KEY` 清除当前会话的密钥。工具会优先请求结构化 JSON；若代理不支持该参数，会自动以普通 JSON 提示重试。

#### `HTTP Error 403: Forbidden` 排查

403 表示请求已到达代理，但当前身份或模型权限被拒绝，通常不是 Wiki 文件或监听器稳定时间的问题。请在**启动命令的同一个 PowerShell 窗口**依次确认：

1. `LLM_WIKI_API_KEY` 已设置且不是空值；新开终端、重启监听器后需要重新设置。
2. `--llm-url` 是代理提供的完整 `.../v1/chat/completions` 地址，`--model` 与该 Key 被授权的模型名完全一致。
3. 在代理控制台确认该 Key 未过期、具备模型调用权限并未触发账户、IP 或配额限制。

不要把 Key 粘贴到笔记、README、命令历史截图或错误报告中。若以上信息正确仍返回 403，需要由代理服务侧检查该请求的权限策略。

### 重新提炼已归档资料

此前在无模型模式导入的资料不会被监听器重复处理。模型配置完成后，用下面命令对全部 `raw/sources/` 资料补做结构化提炼；原始资料不会被复制或修改：

```powershell
python tools/wiki.py refine `
  --llm-url "http://aiproxy.smoa.cc/smartmore/v1/chat/completions" `
  --model "DeepSeek-V4-Pro"
```

可将最后一行替换为单个 `raw/sources/文件名.md`，只提炼一份资料。

## 目录职责

```text
purpose.md        方向、范围与关键问题
AGENTS.md          给 Codex/其他 LLM 的维护规则
raw/sources/       不可变原始资料
raw/inbox/         在 Obsidian 中新增、拖入、修改资料的收件箱
wiki/index.md      内容导航，检索与 LLM 都先读它
wiki/log.md        追加式操作历史
wiki/sources/      每份原始资料的摘要与出处
wiki/concepts/     跨来源概念沉淀
wiki/entities/     人、组织、产品等实体沉淀
wiki/queries/      已保存的问答与分析
wiki/reviews.md    待人工确认的问题
wiki/synthesis/    跨资料专题、比较与待研究问题
.llm-wiki/queue.json  持久导入队列（运行时文件）
.llm-wiki/state.json  归档资料与派生摘要的登记表（运行时文件）
.llm-wiki/reviews.json 审核项状态（运行时文件）
.llm-wiki/analyses/  两阶段模型分析快照（运行时文件）
.llm-wiki/drafts/    候选页面、Diff 基线与应用回滚信息（运行时文件）
.llm-wiki/search.db  SQLite FTS5 搜索索引（运行时文件）
tools/wiki.py      本地导入、搜索、问答和健康检查工具
```

`.llm-wiki/` 下的状态、队列、审核、分析、草稿和索引由工具维护，不应手工编辑或作为知识正文写入 Obsidian。项目的 `.gitignore` 已为这些运行时文件预置排除规则；当前目录尚未初始化为 Git 仓库。`wiki/reviews.md` 是方便在 Obsidian 阅读的事实核验与补充队列镜像，状态以 `.llm-wiki/reviews.json` 为准；旧版没有原文引句的记录会自动迁移为 `legacy_unanchored`，保留在待补充队列。`purpose.md` 目前是范围模板；在明确资料范围和长期问题前，不应把其中的占位文字当作知识库既定目标。

## 工作方式

1. 把资料写入或拖入 `raw/inbox/`，由控制中心或 `watch` 的持久队列归档；处理失败时查看 `status`。
2. 审阅 `draft` 中的文件 Diff 后应用或丢弃；这不等于确认资料中的事实。
3. 用 `review list --queue facts` 核验有原文引句的断言，用 `review list --queue research` 整理待补充事项；再用 `synthesize` 形成跨资料专题，用 `search` 和 `ask` 查询带依据的结论。
4. 先把不再需要的资料移入 `trash`，确认永久删除时才使用 `remove --yes`；定期运行 `lint`，必要时运行 `rebuild`。

原始资料始终是事实依据；Wiki 是可重建的“编译产物”。不确定与冲突应留在 `wiki/reviews.md`，而不是被模型静默覆盖。

## 项目文档

- [术语与状态模型](docs/CONTEXT.md)
- [测试说明](docs/TESTING.md)
- [后续路线图](docs/ROADMAP.md)
