---
title: LLM Wiki 全流程验收测试（可复制执行）
status: active
updated: 2026-08-04
version: "0.2.1"
---

# LLM Wiki 全流程验收测试

本文档所有命令可在 **PowerShell** 中直接复制执行。每节包含：**操作 → 预期效果 → 失败时排查**。

> 将 `<REPO>` 替换为你的仓库根目录，例如 `D:\Cusor_workspace\LLM-Wiki`。

---

## 0. 门禁（每次验收前先跑）

```powershell
Set-Location "<REPO>"
python -B -m unittest discover -s tests -v
python -B tools/wiki.py lint
```

| 预期 | 说明 |
| --- | --- |
| `Ran 59 tests` 或更多，末尾 `OK` | 自动化回归通过 |
| `断链：0`（新库） | 健康检查无异常 |

---

## 1. 模型配置（config.toml）

### 1.1 创建配置文件

```powershell
Set-Location "<REPO>"
Copy-Item config.toml.example config.toml -ErrorAction SilentlyContinue
notepad config.toml
```

在 `config.toml` 中确认：

```toml
[llm]
active = "deepseek"   # 或 openai | ollama
```

### 1.2 设置 API Key（DeepSeek 示例）

```powershell
$env:DEEPSEEK_API_KEY = "sk-你的密钥"
# OpenAI 则使用：
# $env:OPENAI_API_KEY = "sk-..."
```

| 预期 | 说明 |
| --- | --- |
| 环境变量在当前 PowerShell 会话有效 | 关闭终端后需重新设置 |
| **不要**把密钥写入 `config.toml` 或 Git | 只通过 `api_key_env` 引用环境变量名 |

### 1.3 验证配置被 CLI 读取

```powershell
Set-Location "<REPO>"
$env:DEEPSEEK_API_KEY = "test-key-placeholder"
python -B -m unittest tests.test_config.ConfigTests.test_apply_config_fills_args -v
```

| 预期 | 说明 |
| --- | --- |
| `test_apply_config_fills_args ... ok` | config.toml 正确填充 llm_url / model / api_key |
| 若失败 | 检查 `config.toml` 是否存在且 `active` 正确 |

---

## 2. 启动控制中心

```powershell
Set-Location "<REPO>"
$env:DEEPSEEK_API_KEY = "sk-你的密钥"   # 若已配置
python -B tools/wiki.py serve --no-browser
```

| 预期 | 说明 |
| --- | --- |
| 输出 `本地控制中心：http://127.0.0.1:8765/` | 服务监听 loopback |
| 生成 `.llm-wiki/control.json` | 含稳定 `api_token` |
| 浏览器打开后：**浅色科技风界面**，白底 + 蓝紫渐变点缀 | 顶部有 LW 徽标、胶囊导航 |
| 右上角模型胶囊显示 **「已连接 DeepSeek · deepseek-chat」**（绿点） | 读取 config + 环境变量 |
| **来源与任务时间线** 显示空状态文案，**不是** `[object HTMLDivElement]` | 修复 DOM 渲染 bug |

**未配置模型时预期：** 胶囊显示「未配置 config.toml」或「待密钥」；文件归档仍可用，但不会生成 LLM 草稿。

**失败排查：**

- 第二实例报 already running → 关闭旧 `serve`
- 页面样式错乱 → 硬刷新 `Ctrl+F5`，确认 `/static/styles.css` 可访问

---

## 3. API 与认证

新开 PowerShell 窗口：

```powershell
Set-Location "<REPO>"

# 3.1 匿名 capabilities
curl -s http://127.0.0.1:8765/api/capabilities | python -m json.tool

# 3.2 读取 token
$token = (Get-Content .llm-wiki/control.json | ConvertFrom-Json).api_token

# 3.3 鉴权 health
curl -s -H "X-LLM-Wiki-Token: $token" http://127.0.0.1:8765/api/v1/health | python -m json.tool

# 3.4 模型配置（不含密钥）
curl -s -H "X-LLM-Wiki-Token: $token" http://127.0.0.1:8765/api/v1/config/llm | python -m json.tool
```

| 步骤 | 预期 |
| --- | --- |
| 3.1 | `"api_version": "v1"`，含 `routes` |
| 3.3 | `"status": "ok"` |
| 3.4 | `"configured": true`，`active.label` 为 DeepSeek/OpenAI 等，`api_key_set: true/false` |

---

## 4. 采集闭环

### 4.1 粘贴采集（无需外网）

在 Web **收集 → 粘贴正文**：

- 标题：`验收粘贴`
- 正文：`这是粘贴采集验收正文，包含唯一标记 PASTE-VERIFY-001。`

| 预期 | 说明 |
| --- | --- |
| 提交后 notice 提示成功 | 返回 202 job |
| 时间线出现新任务行，阶段从「排队中」→「已归档」等 | 真实阶段名，非假进度条 |
| `raw/sources/` 新增归档，frontmatter 含 `source_kind: paste` | 不可变快照 |

### 4.2 URL 采集

```powershell
curl -s -X POST `
  -H "X-LLM-Wiki-Token: $token" `
  -H "Content-Type: application/json" `
  -d '{"url":"https://example.com"}' `
  http://127.0.0.1:8765/api/v1/acquisitions/url | python -m json.tool
```

| 预期 | 说明 |
| --- | --- |
| HTTP 202，`job_id` 非空 | 异步任务 |
| 时间线可点开详情 | 右侧检查器显示阶段 |

### 4.3 私网 URL 拒绝

```powershell
curl -s -w "\nHTTP:%{http_code}\n" -X POST `
  -H "X-LLM-Wiki-Token: $token" `
  -H "Content-Type: application/json" `
  -d '{"url":"http://127.0.0.1/secret"}' `
  http://127.0.0.1:8765/api/v1/acquisitions/url
```

| 预期 | 说明 |
| --- | --- |
| 4xx 错误，`private_network` 或类似 code | SSRF 防护生效 |

---

## 5. 草稿与审核（需模型）

> 前提：`config.toml` + API Key 已配置，`serve` 已重启。

```powershell
Set-Location "<REPO>"
@"
# 验收草稿

传送带每周检查张力，并记录异常。唯一句 VERBOSE-DRAFT-999。
"@ | Set-Content -Encoding utf8 "raw\inbox\draft-verify.md"
```

等待 watcher（约 4–10 秒），然后：

1. Web → **待处理** → 筛选「草稿」
2. 点击「查看差异」

| 预期 | 说明 |
| --- | --- |
| 出现新草稿 | 未配置模型时只有资料摘要，无概念页草稿 |
| Diff 弹窗显示变更文件列表 | 应用前 Wiki 不变 |
| 点击「应用」后 `wiki/sources/` 更新 | `wiki/log.md` 有记录 |

**事实核验：** 待处理 → 事实核验 →「查看」→ 并排原文与 Wiki，Obsidian 深链可点。

---

## 6. 知识工作区

1. 切换到 **知识**
2. 搜索已有主题关键词
3. 点击结果 → **阅读** 视图
4. 点击 **局部图谱**

| 预期 | 说明 |
| --- | --- |
| 预览 HTML 已转义，无脚本执行 | 安全 Markdown |
| 「在 Obsidian 编辑」可打开对应页 | `links.obsidian` |
| Canvas 图谱聚焦当前节点 | 浅蓝背景 + 节点连线 |

```powershell
curl -s -H "X-LLM-Wiki-Token: $token" `
  "http://127.0.0.1:8765/api/v1/graph/neighborhood?page_id=sources&hops=2" | python -m json.tool
```

| 预期 | `pages` 与 `edges` 非空（有 Wiki 内容时） |

---

## 7. 更多 → 模型配置面板

Web → **更多** → 「模型配置」卡片

| 预期 | 说明 |
| --- | --- |
| 显示当前 profile、model、endpoint_host | 来自 `/api/v1/config/llm` |
| 密钥状态：已设置 / 未检测到 | 不显示密钥明文 |
| 下方有 `copy config.toml.example` 命令提示 | 便于首次配置 |

---

## 8. MCP 只读代理

```powershell
# 终端 1 保持 serve 运行
# 终端 2：
Set-Location "<REPO>"
python -B tools/wiki.py mcp --http --no-browser 2>$null
# 另开终端 3 测试（若 HTTP MCP 在 8766）：
curl -s http://127.0.0.1:8766/health 2>$null
```

或运行自动化：

```powershell
python -B -m unittest tests.test_mcp -v
```

| 预期 | 7 tests OK；工具列表不含 apply/remove |

---

## 9. 设计 §19 主线场景（端到端）

| 步骤 | 操作 | 预期效果 |
| --- | --- | --- |
| 1 | 配置 `config.toml` + 环境变量，重启 `serve` | 模型胶囊绿色「已连接」 |
| 2 | 收集 → 提交 URL 或粘贴 | 时间线显示阶段推进 |
| 3 | 待处理 → 草稿 Diff | 可见页面变更与关系（有模型时） |
| 4 | 应用草稿 | 知识搜索可命中新内容 |
| 5 | Obsidian 打开 Wiki 页 | 双链、人工补充保留 |
| 6 | 知识 → 局部图谱 | 节点可点击导航 |
| 7 | 重复提交未变化 URL | 不创建重复 Snapshot |
| 8 | 停止 `serve` | 插件/状态显示离线，不假装处理中 |

---

## 10. 验收记录模板

```markdown
## 验收记录

- 日期：2026-08-04
- 执行人：
- 提交哈希：git rev-parse --short HEAD
- unittest：__/59+ OK
- lint：通过 / 未通过

| 章节 | 结果 | 备注 |
| --- | --- | --- |
| 0 门禁 | ☐ | |
| 1 config.toml | ☐ | |
| 2 控制中心 UI | ☐ | |
| 3 API | ☐ | |
| 4 采集 | ☐ | |
| 5 草稿 | ☐ | |
| 6 知识 | ☐ | |
| 7 配置面板 | ☐ | |
| 8 MCP | ☐ | |
| 9 主线 | ☐ | |
```

---

## 附录 A. 常见 LLM 错误排查

### HTTP 401

| 检查项 | 操作 |
| --- | --- |
| `api_key_env` 是否为环境变量**名** | 应为 `DEEPSEEK_API_KEY`，不能写 `sk-...` 密钥本身 |
| 环境变量是否在**同一终端**设置 | `$env:DEEPSEEK_API_KEY = "sk-..."` 后同一窗口启动 `serve` |

### HTTP 503（DeepSeek 服务繁忙）

用探测脚本确认（与终端测试相同）：

```powershell
python -B -c @"
import json, os
from urllib.request import Request, urlopen
from urllib.error import HTTPError
key = os.environ['DEEPSEEK_API_KEY']
body = json.dumps({'model':'deepseek-chat','messages':[{'role':'user','content':'ping'}],'max_tokens':5}).encode()
req = Request('https://api.deepseek.com/v1/chat/completions', data=body,
    headers={'Content-Type':'application/json','Authorization':f'Bearer {key}'}, method='POST')
try:
    with urlopen(req, timeout=30) as r:
        print('OK', r.status)
except HTTPError as e:
    print('FAIL', e.code)
    print(e.read().decode('utf-8','replace')[:400])
"@
```

| 响应体关键词 | 含义 | 处理 |
| --- | --- | --- |
| `Service is too busy` | DeepSeek 官方容量不足 | **非本地配置问题**；稍后重试或换提供商 |
| `service_unavailable_error` | 同上 | 工具会对 503 自动退避重试最多 4 次 |
| 持续 503 超过 1 小时 | 高峰期或区域拥堵 | 见下方切换方案 |

**切换 OpenAI（示例）：**

```powershell
# config.toml: active = "openai"
$env:OPENAI_API_KEY = "sk-..."
python -B tools/wiki.py serve
```

**切换本地 Ollama（示例）：**

```powershell
# config.toml: active = "ollama"
ollama serve   # 另开终端
python -B tools/wiki.py serve
```

---

## 相关文档

- [TECHNICAL.md](TECHNICAL.md)
- [config.toml.example](../config.toml.example)
- [INTERACTION_AND_GRAPH_DESIGN.md](INTERACTION_AND_GRAPH_DESIGN.md)
