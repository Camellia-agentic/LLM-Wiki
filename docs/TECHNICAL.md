---
title: LLM Wiki 技术说明
status: active
updated: 2026-08-03
version: "0.2.0"
based_on: INTERACTION_AND_GRAPH_DESIGN.md
---

# LLM Wiki 技术说明

本文是 [采集、交互与知识图谱设计](INTERACTION_AND_GRAPH_DESIGN.md) 的**实现对照文档**，描述截至 `llm_wiki` **0.2.0** 的代码事实。

## 1. 架构

```text
Obsidian + 薄插件 (clients/obsidian-llm-wiki)
        |  读 control.json + /api/v1
        v
Python llm_wiki/ + tools/wiki.py serve (:8765)
        |  JobRunner 后台线程
        v
Markdown Vault（唯一知识真相源）
        ^
Web 控制中心 (web/) — 收集 / 待处理 / 知识
```

| 层 | 技术 | 职责 |
| --- | --- | --- |
| 知识 | Obsidian + `wiki/**/*.md` | 阅读、编辑、`## 人工补充`、双链 |
| 业务 | `llm_wiki/*` | 采集、分块分析、草稿闸门、图谱派生、检索 |
| 任务 UI | `web/` 静态前端 | Diff、核验、采集时间线、语义图 |
| 胶水 | Obsidian 插件 | 待办角标、URL/粘贴、侧栏上下文 |
| Agent | `wiki.py mcp` | 只读转发 loopback API |

## 2. 模块清单

| 模块 | 文件 | 说明 |
| --- | --- | --- |
| 文本 | `text.py` | read/write、frontmatter、`PAGE_TYPES` |
| 分块 | `chunking.py` | 标题/段落分块、代码块保护、行号 |
| 管线 | `pipeline.py` | 分块 LLM 分析、`merge_chunk_analyses` |
| 存储 | `repository.py` | schema v2、acquisitions/snapshots/jobs 迁移 |
| 控制 | `control.py` | `control.json`、Vault ID、单实例锁 |
| 采集 | `acquisition.py` | URL 安全抓取、HTML 提取、粘贴快照 |
| 任务 | `jobs.py` | AcquisitionStore、JobRunner、幂等键 |
| 关系 | `relations.py` | frontmatter `relations:`、`## 关系` 渲染 |
| 图谱 | `graph.py` | 导航边 + 语义边、`graph_delta`、草稿叠加 |
| API | `server.py` | `/api/v1` GET/POST、capabilities |
| MCP | `mcp_server.py` | JSON-RPC / HTTP 8766，只读工具 |
| CLI | `tools/wiki.py` | 命令分发、`Wiki` 类编排 |

## 3. 领域模型

### 3.1 Acquisition / Snapshot / Job

- **Acquisition**：采集意图（`file|url|paste`），含 `canonical_origin`、`latest_snapshot_id`
- **Snapshot**：不可变正文版本；`captured_at` 首次创建后不变
- **Job**：阶段机 `queued → acquiring → archived → chunking → analyzing → merging → drafting → awaiting_review | applied | failed`
- 同 URL 同正文：复用 Snapshot，仅更新 `checked_at`

### 3.2 Relation（语义边）

frontmatter 结构化合同：

```yaml
relations:
  - predicate: uses
    target: wiki/concepts/纠删码
    source: raw/sources/minio-....md
    evidence_quote: "逐字原文引句"
    evidence_anchor: "L120-L123"
    confidence: medium
    verification: source_backed
```

`## 关系` 段为可读渲染，与 frontmatter 原子更新。

受控谓词：`related_to`, `part_of`, `contains`, `uses`, `implements`, `depends_on`, `contrasts_with`, `derived_from`, `supports`, `contradicts`。

### 3.3 图谱边类型

| 类型 | 来源 |
| --- | --- |
| `references` | 正文 `[[wikilink]]` |
| `supported_by` | frontmatter `sources` |
| 语义谓词 | frontmatter `relations` |

## 4. 认证与进程

```powershell
python tools/wiki.py serve          # 默认含 watcher，:8765
python tools/wiki.py serve --no-watch
python tools/wiki.py mcp            # stdio JSON-RPC
python tools/wiki.py mcp --http     # :8766
```

- `.llm-wiki/control.json`：持久 `api_token`、`vault_id`（gitignore）
- `.llm-wiki/instance.lock`：单写进程
- 请求头：`X-LLM-Wiki-Token`；写操作支持 `Idempotency-Key`

## 5. 模型配置（config.toml）

仓库根目录（Vault 根）放置 `config.toml`，从 `config.toml.example` 复制：

```toml
[llm]
active = "deepseek"  # deepseek | openai | ollama | custom

[llm.profiles.deepseek]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
```

- CLI `--llm-url` / `--model` / `--api-key` **优先于** 配置文件
- `GET /api/v1/config/llm` 返回非敏感配置状态（不含密钥）
- Web「更多」页展示当前配置与密钥是否已设置

## 6. HTTP API 摘要

### 5.1 公开

| 方法 | 路径 |
| --- | --- |
| GET | `/api/capabilities` |

### 5.2 采集与任务

| 方法 | 路径 | 响应 |
| --- | --- | --- |
| POST | `/api/v1/acquisitions/file` | 202 + job_id |
| POST | `/api/v1/acquisitions/url` | 202 + job_id |
| POST | `/api/v1/acquisitions/paste` | 202 + job_id |
| GET | `/api/v1/acquisitions` | 来源列表 |
| GET | `/api/v1/jobs` | 任务列表 |
| GET | `/api/v1/jobs/{id}` | 阶段、错误、links |
| POST | `/api/v1/jobs/{id}/retry` | 重试 |

### 5.3 页面与图谱

| 方法 | 路径 |
| --- | --- |
| GET | `/api/v1/pages`, `/api/v1/pages/{id}`, `/api/v1/pages/{id}/context` |
| GET | `/api/v1/graph`, `/api/v1/graph/neighborhood` |
| GET | `/api/v1/drafts/{id}/graph-delta` |

### 5.4 兼容层

旧 `/api/status`、`/api/drafts`、`/api/reviews`、`/api/search`、`/api/ask`、`/api/inbox` 继续可用。

资源响应含 `links.web`、`links.obsidian`（服务生成，客户端不拼路由）。

## 6. Web 控制中心 (`web/`)

| 工作区 | 功能 |
| --- | --- |
| **收集** | 文件/URL/粘贴、采集与任务时间线 |
| **待处理** | 草稿、事实核验、待补充、失败任务（筛选） |
| **知识** | 搜索、页面预览、Canvas 局部图、问答 |
| **更多** | 健康检查、回收站 |

Hash 路由：`#/jobs/{id}`、`#/drafts/{id}`、`#/knowledge/{page_id}`、`#/graph?focus={page_id}`

PWA：`web/manifest.json` + `sw.js`（仅缓存静态资源）。

## 7. Obsidian 插件

路径：`clients/obsidian-llm-wiki/`

- v0.1：连接、待办角标、打开控制台
- v0.2：侧栏当前页上下文、URL/粘贴模态框
- 构建：`npm install && npm run build`（手工安装，非 CI 门禁）

边界：不运行 LLM、不写 `.llm-wiki/`、不接受草稿、不永久删除。

## 8. MCP 只读工具

| 工具 | 转发 |
| --- | --- |
| `status_summary` | `/api/v1/status/summary` |
| `search` | `/api/search` |
| `list_drafts` | `/api/drafts` |
| `list_acquisitions` | `/api/v1/acquisitions` |

不提供 `apply_draft`、`remove` 等写操作。

## 9. 长文分析

1. `chunk_document()` 按标题/段落切分（目标 ~8000 字符）
2. 每块独立第一阶段 LLM 分析
3. `merge_chunk_analyses()` 去重合并
4. 第二阶段生成草稿（仅消费合并结果）

已消除 `content[:14000]` 静默截断。

## 10. 测试门禁

```powershell
python -B -m unittest discover -s tests -v   # 56 项
python -B tools/wiki.py lint
python -B tools/wiki.py --help
```

| 套件 | 覆盖 |
| --- | --- |
| `test_phase0.py` | 分块、repository、control |
| `test_jobs.py` / `test_api_acquisitions.py` | 采集、Job、幂等 |
| `test_graph_relations.py` | 语义边、graph delta |
| `test_api_v1.py` | 认证、capabilities |
| `test_mcp.py` | MCP 白名单与转发 |
| `test_wiki.py` | 原有集成行为 |

## 11. 阶段完成状态

| 阶段 | 状态 | 备注 |
| --- | --- | --- |
| Phase 0 | 完成 | 分块、schema、control、v1、静态前端 |
| Phase 1 | 完成 | URL/粘贴/文件采集、Job、收集 UI |
| Phase 2 | 完成 | page/graph API、知识工作区、Canvas 图 |
| Phase 3 | 完成 | relations、语义图、graph-delta |
| Phase 4 | 大部分完成 | MCP、PWA、插件源码；Playwright/社区发布待做 |

## 12. 明确未实现

- Playwright 浏览器自动化验收
- Obsidian 社区插件商店发布
- 浏览器剪藏器独立扩展
- Tauri 桌面壳
- `entitie` 历史页批量迁移草稿（需对现有 24 页执行 `refine` 或专用迁移命令）
- Obsidian Mobile 远程访问桌面服务

## 13. 相关文档

- 验收步骤：[ACCEPTANCE.md](ACCEPTANCE.md)
- 目标设计：[INTERACTION_AND_GRAPH_DESIGN.md](INTERACTION_AND_GRAPH_DESIGN.md)
- 路线图：[ROADMAP.md](ROADMAP.md)
- 插件安装：[../clients/obsidian-llm-wiki/README.md](../clients/obsidian-llm-wiki/README.md)
