---
title: 建议改进（对照 CoWiki）
type: design_note
updated: 2026-07-20
status: superseded
audience: implementing agent
---

# 建议改进：对照 CoWiki 可借鉴设计

> 2026-07-20：本文的 P0-P2 已按对抗性审查后的方案落地，历史内容仅保留设计背景，不能再作为实施指令。当前术语和状态以 [CONTEXT.md](CONTEXT.md) 为准，测试以 [TESTING.md](TESTING.md) 为准，P3 薄 MCP 计划见 [ROADMAP.md](ROADMAP.md)。

本文供后续 Agent 阅读并落地。对照对象：[wfnuser/cowiki](https://github.com/wfnuser/cowiki)（LLM Wiki, but multiplayer）。  
**不要照搬 CoWiki 的产品栈**；只吸收与本仓库目标一致的设计。

## 本仓库不变约束

落地任何改动前必须遵守：

1. 继续以 Markdown + Obsidian vault 为真相源；工具保持 Python 标准库优先（允许已有的 SQLite FTS）。
2. 三层结构不变：`raw/inbox/` → `raw/sources/`（不可变）→ `wiki/`（可重建编译产物）。
3. 运行时状态只在 `.llm-wiki/`；密钥只来自 `LLM_WIKI_API_KEY` / `--api-key`。
4. 遵守 `AGENTS.md`：可验证事实保留 `sources`；不确定项进审核队列；不静默写事实。
5. 改工具后按影响范围跑：`python -B -m unittest discover -s tests -v`、`python -B tools/wiki.py --help`、`python -B tools/wiki.py lint`。

## 本仓库已有优势（勿弱化）

- 不可变 `raw/sources/` + SHA-256 版本
- 两阶段 LLM（分析快照 → 页面生成）
- 持久队列、重试、级联 `remove`
- `ask` 的页面引用约束与失败回退
- 混合检索（SQLite FTS5 + BM25 RRF）
- 零重依赖、Windows + Obsidian 开箱

## 明确不做（Out of scope）

下列 CoWiki 能力**本次及近期不要实现**，除非用户另开需求：

- 多人 Personal Space / Shared Space、Git 分支协作、Submit PR 式团队流
- Tauri / 独立桌面编辑器（已有 Obsidian）
- PostgreSQL、pgvector、云端权限 / 邀请 / RBAC
- 为「对齐 OKF」而拆掉现有 `wiki/concepts|entities|sources` 分类

---

## P0 — 编译结果 Diff 闸门（最高优先级）

### 问题

当前带 LLM 的 `ingest` / `watch` / `refine` **直接写入 `wiki/`**。人只能事后处理 `review_items`，无法「整次编译一键丢弃」。

### 目标

对齐 CoWiki 的 **Compile → Review diff → Keep/Discard**：

```text
分析与生成 → staging 拟变更 → 人 accept / discard → 才写入 wiki/
```

### 建议设计

1. 新增 staging 根目录，例如 `.llm-wiki/staging/<run_id>/`：
   - `manifest.json`：run_id、源 digest、拟新建/修改/删除文件列表、变更摘要、时间戳
   - `files/`：拟写入的完整 Markdown 镜像（相对 `wiki/` 的路径结构）
2. 带 LLM 的 compile 路径默认写 staging，**不改**现有 `wiki/`（可用 flag 兼容旧行为，例如 `--apply` 直接写入）。
3. 新增子命令（名称可微调，语义需清晰）：
   - `compile preview` / `staging show <run_id>`：打印摘要 + 文件列表 + 关键 diff
   - `compile accept <run_id>`：把 staging 合并进 `wiki/`，重建 index/overview/search，写 `log.md`
   - `compile discard <run_id>`：删除该次 staging
4. 无 LLM 的纯归档（只进 `raw/sources`）仍可立即完成，不必进 staging。
5. `watch`：建议「归档立即做；编译产物进 staging 并提示 accept」，避免无人值守时静默改 Wiki。若需无人值守，显式 `--auto-accept`。

### 验收标准

- [ ] 带 LLM 的 refine/ingest 在默认模式下不直接改 `wiki/` 正文页
- [ ] `accept` 后页面、index、search、log 与今日直接写入行为等价
- [ ] `discard` 后 `wiki/` 与操作前一致
- [ ] 测试覆盖：staging 生成、accept、discard、中断恢复（可选）
- [ ] README / AGENTS.md 更新流程说明

### 涉及文件（预期）

- `tools/wiki.py`（ingest/refine/watch 写路径、新子命令）
- `tests/test_wiki.py`
- `README.md`、`AGENTS.md`
- `.gitignore`（可忽略 `.llm-wiki/staging/` 或按策略保留最近 N 次）

---

## P1 — 变更摘要（配合 Diff 闸门）

### 目标

每次 staging 附带给人读的摘要（对齐 CoWiki Review 顶部 summary），例如：

- 新建概念 N、更新实体 M、打开审核项 K
- 文件列表：`+ path` / `~ path`
- 可选：1～3 句自然语言摘要（LLM 或确定性模板）

### 验收标准

- [ ] `staging show` / accept 前默认打印摘要
- [ ] 摘要写入 `manifest.json`，可离线复看
- [ ] 无 LLM 时仍有确定性模板摘要

---

## P1 — 术语与流程文档（低成本）

### 目标

新增 `docs/CONTEXT.md`（或并入 `AGENTS.md` 一节），钉死术语，减少 Agent 口语漂移：

| 术语 | 含义 | 本仓库对应 |
| --- | --- | --- |
| Source | 原始输入 | `raw/sources/`（及 inbox 待归档） |
| Page | 编译后的 Wiki 页 | `wiki/**/*.md`（非 reserved） |
| Ingest | 归档入不可变源 | 入队 + copy 到 `raw/sources` |
| Compile | LLM 生成/更新页面 | 分析快照 + staging/写入 wiki |
| Review | 人工确认 | staging accept **或** `review_*` 不确定项 |
| Queue | 可恢复任务 | `.llm-wiki/queue.json` |

### 验收标准

- [ ] Agent 维护规范中 Ingest 与 Compile 不再混用
- [ ] README「工作方式」与术语表一致

---

## P2 — 概念近义去重（轻量，不上向量库）

### 问题

跨资料编译易产生近义分裂页（如「RDMA」与「远程直接内存访问」）。

### 建议设计

在 `update_topic_page`（或 staging 合并前）：

1. 收集同 `kind`（concepts/entities）已有页的 `title` + 首段摘要。
2. 规范化后做字符串/拼音/包含关系匹配；可选一次 LLM「应合并到哪一页 / 新建」。
3. 命中则更新已有页并记录到 staging manifest 的 `merged_into`；不确定则写入 `review_items`。

### 验收标准

- [ ] 明显同义标题默认合并或进审核，而不是静默新建第三页
- [ ] 不引入 pgvector / 额外 pip 依赖
- [ ] 有单测覆盖规范化匹配与合并路径

---

## P2 — 薄 MCP（或同等 Agent 工具面）

### 目标

对齐 CoWiki「MCP 无业务逻辑、代理到唯一实现」：用 MCP（或 Cursor 可调用的薄包装）暴露现有 CLI，而不是让 Agent 直接改文件绕过队列与闸门。

### 建议工具最小集

| Tool | 对应 |
| --- | --- |
| `wiki_search` | `wiki.py search` |
| `wiki_ask` | `wiki.py ask` |
| `wiki_ingest` | `wiki.py ingest`（尊重 staging 策略） |
| `wiki_staging_show` / `accept` / `discard` | P0 子命令 |
| `wiki_review_list` / `resolve` | `wiki.py review` |
| `wiki_queue_status` | `wiki.py queue status` |
| `wiki_lint` | `wiki.py lint` |

实现偏好：独立小进程或脚本调用 `python tools/wiki.py ...`，**不复制**业务逻辑到第二份代码。

### 验收标准

- [ ] Agent 经工具完成 search/ask/review，无需手改 `.llm-wiki/*.json`
- [ ] 文档说明本地启动与 Cursor MCP 配置示例
- [ ] 密钥仍只走环境变量

---

## P3 — OKF 友好增量（可选）

在不拆现有目录分类的前提下：

1. 写页时**保留未知 frontmatter 键**（只更新已知字段）。
2. lint：Concept ID = vault 相对路径去掉 `.md`；断链检查与此一致。
3. 可选：子目录生成渐进式 `index.md` 列表块（根 `index.md` 逻辑下沉）。

不做完整 OKF 迁移，不做强制去掉 `wiki/` 链接前缀（除非单独需求）。

---

## 建议实施顺序

```text
1. P1 术语文档（半天内，降低后续沟通成本）
2. P0 staging + accept/discard（核心行为变更）
3. P1 变更摘要（挂在 staging 上）
4. P2 近义去重
5. P2 MCP 薄包装
6. P3 OKF 增量（有余力再做）
```

每完成一项：更新 `README.md` / `AGENTS.md`，补测试，跑验证命令，并在 `wiki/log.md` 或本文件 `updated` 记录状态（`proposed` → `in_progress` → `done`）。

## 给实施 Agent 的工作方式

1. 先读：`AGENTS.md`、`README.md`、`tools/wiki.py`、`tests/test_wiki.py`、本文。
2. 一次只做一个优先级条目；P0 未完成前不要做 MCP。
3. 默认行为变更必须有迁移说明（旧 `--apply` / 新默认 staging）。
4. 不要提交密钥；不要手工编辑 `.llm-wiki/` 运行时文件作为「修复」。
5. 用户未要求时不要 `git commit`。

## 参考链接

- CoWiki 仓库：https://github.com/wfnuser/cowiki
- CoWiki 术语：https://github.com/wfnuser/cowiki/blob/dev/CONTEXT.md
- CoWiki OKF 说明：https://github.com/wfnuser/cowiki/blob/dev/docs/okf-v0.1.md
- CoWiki MCP：https://github.com/wfnuser/cowiki/blob/dev/docs/mcp.md
- 本仓库维护规范：`AGENTS.md`
- 本仓库工具入口：`tools/wiki.py`
