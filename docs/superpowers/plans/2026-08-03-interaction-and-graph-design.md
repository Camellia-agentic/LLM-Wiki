# 采集、交互与知识图谱 — 完整实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 [INTERACTION_AND_GRAPH_DESIGN.md](../INTERACTION_AND_GRAPH_DESIGN.md) 将 LLM Wiki 从单文件原型演进为「本机 API + Web 控制中心 + Obsidian 薄插件」的完整采集—证据—草稿—图谱闭环。

**Architecture:** 以 Markdown Vault 为唯一知识真相源；Python `llm_wiki/` 包为唯一业务层；`tools/wiki.py` 仅做 CLI 分发。Web 与 Obsidian 插件通过版本化 loopback `/api/v1` 交互，不复制 pipeline。分 Phase 0→4 交付，每阶段结束可独立验收。

**Tech Stack:** Python 3.10+ 标准库、SQLite FTS5、静态 HTML/JS（Cytoscape.js vendor）、Obsidian Plugin API（TypeScript）、unittest、Playwright（Phase 2+）

**权威参考:** [INTERACTION_AND_GRAPH_DESIGN.md](../INTERACTION_AND_GRAPH_DESIGN.md)、[ROADMAP.md](../ROADMAP.md)、[obsidian.md](../obsidian.md)、[TESTING.md](../TESTING.md)

---

## 文件结构总览

实施完成后目标布局（小步迁移，非一次性大爆炸）：

```text
llm_wiki/
  __init__.py           包版本与公共导出
  paths.py              Vault 路径常量
  text.py               read_text/write_text/slug 等纯函数
  repository.py         schema 版本、JSON 原子读写、迁移器、短事务锁
  acquisition.py        文件/URL/粘贴、快照、URL 安全、FetchedDocument
  chunking.py           标题/段落分块、行号、证据锚点
  pipeline.py           Job 阶段机、分块分析、合并、草稿触发
  graph.py              页面解析、references/supported_by/语义边、graph delta
  search.py             FTS5、BM25、ask（从 Wiki 类迁出）
  control.py            control.json、Vault ID、稳定 token、单实例锁
  server.py             /api/v1 路由、鉴权、错误结构、静态资源
  wiki_core.py          Wiki 类剩余编排（逐步变薄）

web/
  index.html            三工作区壳
  app.js                收集/待处理/知识路由与 API 客户端
  graph.js              Cytoscape 局部图与边检查器
  styles.css
  vendor/cytoscape.min.js
  vendor/marked.min.js
  vendor/dompurify.min.js

clients/obsidian-llm-wiki/
  manifest.json
  main.ts
  settings.ts
  api-client.ts
  sidebar-view.ts
  styles.css
  versions.json
  esbuild.config.mjs

tools/wiki.py           argparse + 调用 llm_wiki

tests/
  test_chunking.py
  test_repository.py
  test_acquisition.py
  test_pipeline.py
  test_graph.py
  test_api_v1.py
  test_control_auth.py
  test_wiki.py            保留现有集成测试，逐步改 import
  browser/                Playwright（Phase 2+）
```

**拆分原则:** 先从 `tools/wiki.py` 无行为变化抽取模块；每抽一块跑全量 `unittest`；新能力只加在新模块。

---

## Phase 0：正确性、并发与客户端基础

**完成标准（设计 §16 Phase 0）:** 长文无静默截断；模型调用不阻塞只读 API/watcher；CLI/旧 API 兼容；`control.json` + `/api/v1` 契约通过测试；插件尚不宣称可用。

---

### Task 0.1: 包骨架与纯函数抽取

**Files:**
- Create: `llm_wiki/__init__.py`, `llm_wiki/paths.py`, `llm_wiki/text.py`
- Modify: `tools/wiki.py`（改为 `from llm_wiki.text import read_text, write_text, ...`）
- Test: `tests/test_text.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_text.py
import unittest
from llm_wiki.text import slug, compact

class TextUtilTests(unittest.TestCase):
    def test_slug_preserves_cjk(self) -> None:
        self.assertEqual(slug("纠删码 Erasure Code"), "纠删码-erasure-code")

    def test_compact_truncates_with_ellipsis(self) -> None:
        self.assertTrue(compact("a" * 400, 50).endswith("…"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_text -v`  
Expected: FAIL `ModuleNotFoundError: No module named 'llm_wiki'`

- [ ] **Step 3: Write minimal implementation**

创建 `llm_wiki/text.py`，从 `tools/wiki.py` 复制 `read_text`, `write_text`, `sha256`, `slug`, `yaml_quote`, `compact`, `tokenize` 等无 `Wiki` 依赖函数。在 `tools/wiki.py` 顶部改为 `from llm_wiki.text import ...` 并删除重复定义。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m unittest tests.test_text tests.test_wiki -v`  
Expected: PASS（现有 `test_wiki.py` 仍通过）

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/ tests/test_text.py tools/wiki.py
git commit -m "refactor: extract llm_wiki.text utilities from wiki.py"
```

---

### Task 0.2: 修复 `type: entitie` 生成错误

**Files:**
- Modify: `llm_wiki/wiki_core.py` 或暂留 `tools/wiki.py` 内 `render_topic_page`（随 Task 0.1 迁移路径而定）
- Test: `tests/test_entity_type.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entity_type.py
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from llm_wiki.wiki_core import Wiki  # 或从 wiki_tool 导入，取决于迁移进度

class EntityTypeTests(unittest.TestCase):
    def test_new_entity_page_uses_entity_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = Wiki(root)
            wiki.ensure_layout()
            path, content, _ = wiki.render_topic_page(
                "entities",
                {"name": "MinIO", "summary": "对象存储。"},
                "raw/sources/minio.md",
                "MinIO 资料",
            )
            self.assertIsNotNone(path)
            self.assertIn("type: entity", content)
            self.assertNotIn("type: entitie", content)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_entity_type -v`  
Expected: FAIL `AssertionError: 'type: entitie' in ...`

- [ ] **Step 3: Write minimal implementation**

在 `render_topic_page` 将 `kind[:-1]` 替换为显式映射：

```python
PAGE_TYPES = {"concepts": "concept", "entities": "entity", "sources": "source_summary"}

# inside render_topic_page when creating new page:
page_type = PAGE_TYPES.get(kind, kind.rstrip("s"))
content = frontmatter(name, page_type, [source_path]) + ...
```

- [ ] **Step 4: Run tests**

Run: `python -B -m unittest discover -s tests -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_entity_type.py tools/wiki.py llm_wiki/
git commit -m "fix: generate type entity instead of entitie for entity pages"
```

---

### Task 0.3: 长文分块（chunking 模块）

**Files:**
- Create: `llm_wiki/chunking.py`
- Test: `tests/test_chunking.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chunking.py
import unittest
from llm_wiki.chunking import chunk_document

SAMPLE = "# Title\n\n" + ("段落内容。\n\n" * 2000) + "\n## Late Section\n\n关键证据在第 14000 字符之后。\n"

class ChunkingTests(unittest.TestCase):
    def test_late_evidence_in_last_chunk(self) -> None:
        chunks = chunk_document(SAMPLE, target_size=8000)
        self.assertGreater(len(chunks), 1)
        joined = "\n".join(c.content for c in chunks)
        self.assertIn("关键证据在第 14000 字符之后", joined)
        last = chunks[-1]
        self.assertIn("Late Section", last.heading_path)
        self.assertGreaterEqual(last.end_line, last.start_line)

    def test_code_fence_not_split(self) -> None:
        doc = "# Doc\n\n```python\nprint('x')\nprint('y')\n```\n"
        chunks = chunk_document(doc, target_size=20)
        for ch in chunks:
            if "```" in ch.content:
                self.assertEqual(ch.content.count("```"), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_chunking -v`  
Expected: FAIL `ModuleNotFoundError` 或 `chunk_document not defined`

- [ ] **Step 3: Write minimal implementation**

```python
# llm_wiki/chunking.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Chunk:
    id: str
    heading_path: list[str]
    start_line: int
    end_line: int
    content: str
    content_digest: str  # sha256 hex of content

def chunk_document(text: str, *, target_size: int = 8000, overlap: int = 200) -> list[Chunk]:
    # 1) 按 ## / ### 标题切段；2) 超大段按段落再切；3) 保护 ``` 围栏；
    # 4) 仅必要时小幅 overlap；5) 分配 chunk_0001..n 与 1-based 行号
    ...
```

实现须满足设计 §7.2：目标 6000–10000 字符、保留标题路径、代码块完整。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m unittest tests.test_chunking -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/chunking.py tests/test_chunking.py
git commit -m "feat: add semantic document chunking with line anchors"
```

---

### Task 0.4: 分块分析与证据合并（替换 14000 截断）

**Files:**
- Create: `llm_wiki/pipeline.py`（`merge_chunk_analyses`, `analyze_snapshot`）
- Modify: `Wiki.llm_analysis` 调用路径
- Test: `tests/test_pipeline_merge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_merge.py
import unittest
from llm_wiki.pipeline import merge_chunk_analyses

class MergeTests(unittest.TestCase):
    def test_merge_dedupes_concepts_and_keeps_chunk_ids(self) -> None:
        a = {"concepts": [{"name": "RDMA", "summary": "a", "chunk_id": "chunk_0001"}],
             "relations": [], "review_items": []}
        b = {"concepts": [{"name": "RDMA", "summary": "b", "chunk_id": "chunk_0002"}],
             "relations": [], "review_items": []}
        merged = merge_chunk_analyses([a, b])
        names = [c["name"] for c in merged["concepts"]]
        self.assertEqual(names.count("RDMA"), 1)
        self.assertIn("chunk_id", merged["concepts"][0])

    def test_merge_cannot_invent_new_fact(self) -> None:
        merged = merge_chunk_analyses([{"concepts": [], "relations": [], "review_items": []}])
        self.assertEqual([], merged.get("concepts", []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_pipeline_merge -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

- `analyze_snapshot(wiki, snapshot_path, args)`：分块 → 每块调 `llm_json` → `merge_chunk_analyses`
- 删除 `tools/wiki.py` 中 `content[:14000]` 硬截断（约 L773）
- 合并规则：同名 concept/entity 归并 summaries；relation 按 `(subject, predicate, object, evidence_quote)` 去重；**禁止**合并阶段新增块中不存在的 claim

- [ ] **Step 4: Run full suite**

Run: `python -B -m unittest discover -s tests -v`  
Expected: PASS；新增 `tests/test_long_document.py` 验证第 15000 字符处的引句进入 `review_items`

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/pipeline.py tests/test_pipeline_merge.py tests/test_long_document.py tools/wiki.py
git commit -m "feat: chunked LLM analysis replaces 14000-char silent truncation"
```

---

### Task 0.5: Repository 层与 schema 迁移

**Files:**
- Create: `llm_wiki/repository.py`
- Modify: `.llm-wiki/state.json`, `.llm-wiki/queue.json` 读写路径
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repository.py
import json
import tempfile
import unittest
from pathlib import Path
from llm_wiki.repository import Repository, SCHEMA_VERSION

class RepositoryTests(unittest.TestCase):
    def test_migrate_legacy_sources_to_acquisitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            runtime = root / ".llm-wiki"
            runtime.mkdir(parents=True)
            legacy = {"sources": {"abc": {"title": "T", "raw_path": "raw/sources/t.md", "digest": "abc"}}}
            (runtime / "state.json").write_text(json.dumps(legacy), encoding="utf-8")
            repo = Repository(root)
            state = repo.load_state()
            self.assertEqual(SCHEMA_VERSION, state["schema_version"])
            self.assertIn("acquisitions", state)
            self.assertEqual("abc", state["acquisitions"][0]["latest_snapshot_id"] or state["snapshots"][0]["id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_repository -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`repository.py` 提供：
- `SCHEMA_VERSION = 2`
- `load_state()` / `save_state()` 带 `threading.RLock` 短临界区
- `migrate_state(raw: dict) -> dict`：旧 `sources[digest]` → `acquisitions[]` + `snapshots[]`；旧 `queue.tasks[]` 补 `kind: "file"`, `stage`
- 幂等：已迁移则跳过

领域模型字段对齐设计 §5.1–5.3。

- [ ] **Step 4: Run tests**

Run: `python -B -m unittest tests.test_repository tests.test_wiki -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/repository.py tests/test_repository.py
git commit -m "feat: add schema v2 migration for acquisitions and snapshots"
```

---

### Task 0.6: 全局锁拆分为短事务锁 + 后台 worker 边界

**Files:**
- Modify: `llm_wiki/server.py`（或 `tools/wiki.py` 内 `LocalControl`）
- Test: `tests/test_concurrency.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_concurrency.py
import threading
import tempfile
import time
import unittest
from pathlib import Path
# 使用 test server helper

class ConcurrencyTests(unittest.TestCase):
    def test_read_api_not_blocked_by_slow_llm_job(self) -> None:
        # 启动 serve；POST 触发 mock 慢 LLM job；并行 GET /api/v1/health 应在 <1s 返回 200
        ...
        self.assertLess(elapsed, 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_concurrency -v`  
Expected: FAIL（当前 `with control.lock` 包裹整个 GET handler）

- [ ] **Step 3: Write minimal implementation**

- `repository.lock` 仅包裹 `load_json`/`save_json`/文件 `replace`
- `LocalControl.lock` 从 HTTP GET 路径移除；watcher 扫描与入队用独立短锁
- 模型调用在 `pipeline.run_job()` 后台线程，不持 repository 锁
- `status` 读预计算计数，不在每次请求跑 `lint()`

- [ ] **Step 4: Run tests**

Run: `python -B -m unittest tests.test_concurrency tests.test_wiki -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/server.py tests/test_concurrency.py tools/wiki.py
git commit -m "refactor: shorten repository locks; do not block reads during LLM jobs"
```

---

### Task 0.7: control.json、稳定 Vault ID 与单实例锁

**Files:**
- Create: `llm_wiki/control.py`
- Modify: `.gitignore`（加入 `.llm-wiki/control.json`）
- Test: `tests/test_control_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_control_auth.py
import json
import tempfile
import unittest
from pathlib import Path
from llm_wiki.control import ControlState, vault_id_for

class ControlAuthTests(unittest.TestCase):
    def test_vault_id_stable_for_same_root(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "vault"
            root.mkdir()
            self.assertEqual(vault_id_for(root), vault_id_for(root))

    def test_control_persists_token_across_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "vault"
            root.mkdir()
            first = ControlState.load_or_create(root, port=8765)
            second = ControlState.load_or_create(root, port=8765)
            self.assertEqual(first.token, second.token)
            self.assertEqual(first.vault_id, second.vault_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_control_auth -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`ControlState` 写入 `.llm-wiki/control.json`（gitignore）：

```json
{
  "schema_version": 1,
  "vault_id": "sha256(root.resolve())[:16]",
  "api_token": "...",
  "base_url": "http://127.0.0.1:8765",
  "api_version": "v1",
  "updated_at": "..."
}
```

- `serve` 启动时：若另一实例持有 `.llm-wiki/instance.lock` 则拒绝启动
- Web 页面仍注入 token；插件只读 `control.json`（设计 §4.4）

- [ ] **Step 4: Run tests**

Run: `python -B -m unittest tests.test_control_auth -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/control.py .gitignore tests/test_control_auth.py
git commit -m "feat: persistent control.json with stable vault id and instance lock"
```

---

### Task 0.8: `/api/v1` 基础端点与错误结构

**Files:**
- Create: `llm_wiki/server.py`, `llm_wiki/errors.py`
- Modify: `tools/wiki.py` `make_control_handler` 委托 `server.route`
- Test: `tests/test_api_v1.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_v1.py
import json
import threading
import unittest
from urllib.request import Request, urlopen
# helper: start_test_server()

class ApiV1Tests(unittest.TestCase):
    def test_capabilities_public_without_token(self) -> None:
        base, _ = start_test_server()
        with urlopen(base + "/api/capabilities", timeout=3) as resp:
            data = json.loads(resp.read())
        self.assertEqual("v1", data["api_version"])
        self.assertIn("vault_id", data)

    def test_health_requires_token(self) -> None:
        base, token = start_test_server()
        req = Request(base + "/api/v1/health", headers={"X-LLM-Wiki-Token": token})
        with urlopen(req, timeout=3) as resp:
            self.assertEqual(200, resp.status)

    def test_error_payload_shape(self) -> None:
        base, _ = start_test_server()
        try:
            urlopen(base + "/api/v1/health", timeout=3)
        except Exception as exc:
            body = json.loads(exc.read().decode())  # HTTPError
            self.assertIn("code", body)
            self.assertIn("message", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m unittest tests.test_api_v1 -v`  
Expected: FAIL 404 on `/api/capabilities`

- [ ] **Step 3: Write minimal implementation**

实现设计 §10.1 首批端点：
- `GET /api/capabilities`（匿名）
- `GET /api/v1/health`
- `GET /api/v1/status/summary`（含 `revision`, drafts/facts/research/failed 计数）
- 统一错误：`{"code","message","retryable","stage","details"}`

保留旧 `/api/status` 等路由转发到 v1 或原实现（兼容期）。

- [ ] **Step 4: Run tests**

Run: `python -B -m unittest tests.test_api_v1 tests.test_wiki -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_wiki/server.py llm_wiki/errors.py tests/test_api_v1.py tools/wiki.py
git commit -m "feat: add /api/v1 capabilities, health, and status summary"
```

---

### Task 0.9: 静态前端从 wiki.py 拆出

**Files:**
- Create: `web/index.html`, `web/app.js`, `web/styles.css`
- Modify: `llm_wiki/server.py` 静态文件服务
- Test: `tests/test_static_web.py`

- [ ] **Step 1: Write the failing test**

```python
def test_serve_static_index_without_inline_template(self):
    base, token = start_test_server()
    with urlopen(base + "/", timeout=3) as resp:
        html = resp.read().decode("utf-8")
    self.assertIn('src="/static/app.js"', html)
    self.assertNotIn("CONTROL_CENTER_TEMPLATE", html)
```

- [ ] **Step 2–4:** 将 `CONTROL_CENTER_TEMPLATE` 迁到 `web/`；`/` 返回 `index.html` 并注入 meta token；删除 `tools/wiki.py` 内嵌 HTML 字符串

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor: extract control center static assets to web/"
```

---

### Task 0.10: Phase 0 门禁与文档同步

- [ ] 运行 `python -B -m unittest discover -s tests -v`
- [ ] 运行 `python -B tools/wiki.py --help` 与 `python -B tools/wiki.py lint`
- [ ] 更新 [ROADMAP.md](../ROADMAP.md) Phase 0 状态（仅写已实现项）
- [ ] Commit: `docs: mark Phase 0 complete in ROADMAP`

---

## Phase 1：统一采集闭环 + Obsidian 插件 v0.1

**完成标准:** 公开 URL → 不可变快照 → 草稿；失败可粘贴降级；插件从正确 Vault 提交且幂等重试不重复建任务。

---

### Task 1.1: URL 安全抓取与 FetchedDocument

**Files:**
- Create: `llm_wiki/acquisition.py`（`fetch_url`, `validate_url`, `FetchedDocument`）
- Test: `tests/test_acquisition_url.py`

- [ ] **Step 1: Write the failing test**

```python
def test_rejects_private_ip_url(self):
    with self.assertRaises(ValueError) as ctx:
        validate_url("http://127.0.0.1/admin")
    self.assertEqual("private_network", ctx.exception.args[0])

def test_html_main_extractor_prefers_article(self):
    html = "<html><nav>x</nav><article><h1>T</h1><p>Body</p></article></html>"
    doc = extract_html_main(html, "text/html")
    self.assertIn("Body", doc.text)
    self.assertNotIn("nav", doc.text.lower())
```

- [ ] **Step 2–5:** 实现设计 §6.2、§6.4 全部安全边界（scheme、私网、重定向 5 次、15s 超时、10MB、Content-Type 白名单、DNS 重绑定校验）

---

### Task 1.2: 粘贴采集与快照 frontmatter

**Files:**
- Modify: `llm_wiki/acquisition.py`（`create_paste_snapshot`）
- Test: `tests/test_acquisition_paste.py`

- [ ] 验证 `source_kind: paste`、用户粘贴说明、`captured_at` 不可变

---

### Task 1.3: Job 阶段机与异步 worker

**Files:**
- Modify: `llm_wiki/pipeline.py`（`JobRunner`）
- Test: `tests/test_job_stages.py`

- [ ] **关键测试**

```python
def test_url_acquisition_returns_202_and_completes_in_background(self):
    # POST /api/v1/acquisitions/url -> 202 + job_id
    # poll GET /api/v1/jobs/{id} until awaiting_review or failed

def test_idempotency_key_reuses_job(self):
    # 相同 Idempotency-Key 两次 POST 返回同一 job_id
```

- [ ] 阶段：`queued → acquiring → archived → chunking → analyzing → merging → drafting → awaiting_review`

---

### Task 1.4: 采集 API v1

**Files:**
- Modify: `llm_wiki/server.py`
- Test: `tests/test_api_acquisitions.py`

实现 §10.2：
- `POST /api/v1/acquisitions/file|url|paste`
- `GET /api/v1/acquisitions`
- `GET/POST /api/v1/jobs/{id}[/retry]`

响应含 `links.web`, `links.obsidian`（Vault 相对路径 URI）。

---

### Task 1.5: Web「收集」工作区

**Files:**
- Modify: `web/app.js`, `web/styles.css`

- [ ] 文件/URL/粘贴分段控制
- [ ] 来源时间线显示真实 `stage`（非假进度条）
- [ ] 失败项：重试、详情、改用粘贴

---

### Task 1.6: Obsidian 插件 v0.1 脚手架

**Files:**
- Create: `clients/obsidian-llm-wiki/*`

- [ ] **Step 1:** `manifest.json`（`id: llm-wiki`, `minAppVersion`）
- [ ] **Step 2:** `api-client.ts` 读取 `.llm-wiki/control.json`，校验 `vault_id`
- [ ] **Step 3:** 状态栏图标 + 设置页（base URL 诊断）
- [ ] **Step 4:** 命令「提交 URL」「粘贴正文」→ POST acquisitions
- [ ] **Step 5:** 待办角标（轮询 `/api/v1/status/summary`，15–30s，无变化不重绘）

插件验收见设计 §15.4（离线、token 失效、Vault 不匹配降级）。

---

### Task 1.7: Phase 1 门禁

- [ ] 端到端：公开技术文档 URL → 草稿（可用 httpbin 或本地 fixture server 测试）
- [ ] 插件手工验收清单写入 `docs/TESTING.md`
- [ ] `unittest` + `lint` 全绿

---

## Phase 2：知识浏览、导航图 + 插件 v0.2

**完成标准:** 搜索可预览、看来源/反链、Obsidian 打开；插件当前页与 Web 同页；图谱断链与 lint 一致。

---

### Task 2.1: Page API 与链接生成

**Files:**
- Create: `llm_wiki/graph.py`（初版：parse wikilinks, frontmatter sources）
- Test: `tests/test_graph.py`

- [ ] `GET /api/v1/pages`, `GET /api/v1/pages/{id}`, `GET /api/v1/pages/{id}/context`
- [ ] 响应 `revision`/ETag；`links.obsidian` 使用 vault_id + 相对路径

---

### Task 2.2: 导航图谱索引（references + supported_by）

**Files:**
- Modify: `llm_wiki/graph.py`, 缓存 `.llm-wiki/graph.json`（可重建）

- [ ] `GET /api/v1/graph`, `GET /api/v1/graph/neighborhood?page_id=...&hops=2`
- [ ] 默认隐藏 index/overview/log/review_queue 节点

---

### Task 2.3: 安全 Markdown 预览

**Files:**
- Add: `web/vendor/marked.min.js`, `web/vendor/dompurify.min.js`
- Test: `tests/test_markdown_sanitize.py`（Python 侧仅测 API 不返回 script）

- [ ] 禁止未清理 `innerHTML`；拦截 `javascript:` iframe

---

### Task 2.4: Web「知识」工作区

**Files:**
- Modify: `web/app.js`, `web/graph.js`

- [ ] 列表 / 阅读 / 图谱三视图共享选中页
- [ ] 页脚：来源、反链、关系（初版仅 references）
- [ ] 「编辑」按钮 → `links.obsidian`

---

### Task 2.5: Obsidian 插件 v0.2

**Files:**
- Modify: `clients/obsidian-llm-wiki/sidebar-view.ts`

- [ ] 当前活动文件若在 `wiki/` 下，拉取 `/api/v1/pages/{id}/context`
- [ ] 显示来源、入链/出链、相关待办
- [ ] 「打开局部图」→ `links.web` graph 路由

---

### Task 2.6: Playwright 浏览器验收（首批）

**Files:**
- Create: `tests/browser/test_collect_and_knowledge.py`

- [ ] 桌面 + 移动视口 smoke
- [ ] 布局稳定（图谱画布不跳动）

---

### Task 2.7: Phase 2 门禁

- [ ] `lint` 断链与 `/api/v1/graph` 一致
- [ ] 更新 README（仅已实现能力）

---

## Phase 3：证据化语义图谱

**完成标准:** 语义边可回到逐字引句；草稿 graph delta 完整；Obsidian 与 Web 共享 Markdown 双链。

---

### Task 3.1: 分块分析输出受控 relations

**Files:**
- Modify: `llm_wiki/pipeline.py` LLM schema
- Test: `tests/test_relations_extract.py`

- [ ] 谓词白名单（设计 §5.5）；每条 relation 含 `chunk_id`, `evidence_quote`, `evidence_anchor`

---

### Task 3.2: Wiki 页面 relations frontmatter + `## 关系` 渲染

**Files:**
- Modify: `Wiki.render_topic_page` / 草稿生成

```yaml
relations:
  - predicate: uses
    target: wiki/concepts/纠删码
    source: raw/sources/minio-....md
    evidence_quote: "..."
    evidence_anchor: "L120-L123"
```

```markdown
## 关系
- `uses` [[wiki/concepts/纠删码]]（[[raw/sources/minio-...#L120]]）
```

- [ ] 草稿中原子更新 frontmatter 与渲染段；基线冲突拒绝

---

### Task 3.3: 图谱语义边与边检查器

**Files:**
- Modify: `llm_wiki/graph.py`, `web/graph.js`

- [ ] 边类型 `references` | `supported_by` | 受控谓词
- [ ] 点击边：主体、谓词、客体、引句、来源、verification
- [ ] Cytoscape 局部图默认 1–2 跳

---

### Task 3.4: 草稿 graph delta API

**Files:**
- Modify: `llm_wiki/graph.py`（`graph_delta(draft_id)`）
- Test: `tests/test_graph_delta.py`

- [ ] `GET /api/v1/drafts/{id}/graph-delta` 返回 `nodes_added/removed`, `edges_added/removed`, `broken_links_*`

---

### Task 3.5: `entitie → entity` 迁移草稿

**Files:**
- Create: 一次性迁移命令或 `wiki.py migrate-entity-types`

- [ ] 通过可审阅草稿批量修正现有 24 页；保留 `## 人工补充`

---

### Task 3.6: 插件语义图深链

- [ ] 侧栏「打开语义图」→ Web `graph?focus={page_id}`；不在插件内嵌 Cytoscape

---

### Task 3.7: Phase 3 门禁

- [ ] 演示场景设计 §19 步骤 1–6 可手工走通
- [ ] Playwright 覆盖边证据面板

---

## Phase 4：体验与受控扩展

**完成标准:** 新客户端不复制业务逻辑；版本不兼容可降级；写入仍经草稿/删除闸门。

---

### Task 4.1: PWA manifest 与离线壳

**Files:**
- Create: `web/manifest.json`, `web/sw.js`（仅缓存静态资源，不缓存 API）

---

### Task 4.2: 浏览器剪藏器（可选）

**Files:**
- Create: `clients/browser-clipper/`（调用 `POST /api/v1/acquisitions/paste`）

---

### Task 4.3: 导入历史与 SSE/WebSocket 事件（二选一）

- [ ] `GET /api/v1/events` 或轮询 `jobs?since=revision` 增量更新收集时间线

---

### Task 4.4: 薄 MCP 服务

**Files:**
- Create: `llm_wiki/mcp_server.py`

- [ ] 仅转发：ingest、search、ask、draft list、status；**禁止** apply/remove 无确认
- [ ] 依赖 Phase 0–3 API 稳定

---

### Task 4.5: 插件发布打包

- [ ] `esbuild` 构建、`versions.json`、仓库内手工安装文档
- [ ] 社区发布为可选，非阻塞

---

### Task 4.6: Phase 4 门禁

- [ ] 全量 `unittest` + Playwright + 插件桌面验收
- [ ] README / ROADMAP / INTERACTION 文档状态一致

---

## 项目级验证命令（每 Task 完成后建议执行）

```powershell
python -B -m unittest discover -s tests -v
python -B tools/wiki.py --help
python -B tools/wiki.py lint
```

Phase 2+ 追加：

```powershell
# 静态检查（引入后）
# npx playwright test tests/browser
```

---

## 规范自检（Plan Self-Review）

### 1. Spec 覆盖

| 设计章节 | 对应 Task |
| --- | --- |
| §5 领域模型 | 0.5, 1.3 |
| §6 采集 | 1.1–1.4 |
| §7 长文分块 | 0.3–0.4 |
| §8 图谱 | 2.2, 3.3–3.4 |
| §9 交互（Web + 插件） | 1.5–1.6, 2.4–2.5, 3.6 |
| §10 API | 0.8, 1.4, 2.1, 3.4 |
| §11 并发 | 0.6 |
| §12 代码组织 | 0.1, 0.9, 全 Phase 文件结构 |
| §13 迁移 | 0.5, 3.5 |
| §14 安全 | 0.7, 1.1 |
| §15 测试 | 各 Task 内 TDD + 1.7/2.6/3.7/4.6 |
| §16 分阶段 | Phase 0–4 全文 |
| §19 演示场景 | 3.7 验收 |

### 2. Placeholder 扫描

- 无 TBD/TODO/“稍后实现”类占位
- Task 0.9 Step 2–4 已标明具体迁移动作（内联模板 → `web/`）

### 3. 类型一致性

- 统一使用 `acquisition_id`, `snapshot_id`, `job_id`, `chunk_id`
- API 路径统一 `/api/v1/...`；旧 `/api/*` 仅作兼容层
- `PAGE_TYPES` 映射固定 `concept`/`entity`，不再使用 `kind[:-1]`

---

## 执行交接

**Plan complete and saved to `docs/superpowers/plans/2026-08-03-interaction-and-graph-design.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 每个 Task 派发独立 subagent，Task 间人工/主 agent 审查，迭代最快

**2. Inline Execution** — 在本会话用 executing-plans 按 Phase 0 Task 0.1 起顺序执行，每 2–3 个 Task 设检查点

**Which approach?**
