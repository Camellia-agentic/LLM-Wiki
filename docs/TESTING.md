---
title: Local LLM Wiki 测试说明
status: current
updated: 2026-08-03
---

# 测试说明

本文区分当前已有门禁和规划能力的验收要求。完整目标测试矩阵见 [Obsidian 优先的采集、交互与知识图谱设计](INTERACTION_AND_GRAPH_DESIGN.md#15-测试与验收)。

## 当前自动化门禁

```powershell
python -B -m unittest discover -s tests -v
python -B tools/wiki.py --help
python -B tools/wiki.py lint
```

当前 `tests/test_wiki.py` 覆盖：

- 无模型导入、搜索与健康检查。
- 收件箱稳定检测、队列持久化、失败重试和中断恢复。
- 两阶段重新提炼、跨资料综合和引用约束问答。
- 草稿生成、应用、丢弃、基线冲突和回滚。
- 人工补充和未知 frontmatter 保留。
- 回收站恢复、显式别名和重复候选。
- 带原文引句的事实核验、无引句问题降级和旧审核项迁移。
- 本机控制中心状态、文件上传、审核详情和队列 API。
- 生成索引时不截断 Obsidian 双链。

当前没有覆盖 URL 采集、长文分块、版本化客户端认证、页面预览、语义关系、图谱渲染、Obsidian 插件或浏览器交互；这些能力仍处于规划状态。

## 当前手工验收

1. 在配置模型的 PowerShell 中运行 `python tools/wiki.py serve`。`serve` 已包含 watcher，不要另启同一 Vault 的 `watch`。
2. 打开 `http://127.0.0.1:8765/`，拖入一个 Markdown 或 TXT 文件。
3. 确认收件箱出现文件，稳定时间后出现待确认草稿。
4. 打开草稿 Diff；应用后确认 Wiki 页面、索引和搜索结果出现。丢弃另一草稿，确认 Wiki 不变。
5. 在资料页添加 `## 人工补充` 和自定义 frontmatter，重新提炼后确认保留。
6. 将一份资料移入回收站，确认搜索不再命中；恢复后确认再次出现。
7. 确认只有带逐字引句的断言进入事实核验，无引句问题进入待补充。
8. 在审核详情中核对引句、原始资料、Wiki 页面和 Obsidian 跳转，并填写处理记录。
9. 运行 `python -B tools/wiki.py lint`，记录断链、孤儿页和缺失来源结果。

测试不使用真实 API Key。模型路径使用替身响应；连接实际模型时只通过当前进程的 `LLM_WIKI_API_KEY` 或 `--api-key` 提供密钥。

## 规划能力的测试门禁

### Phase 0

- 第 14,000 字符后的证据仍能进入分析与草稿。
- 分块保留标题路径、行号、代码块、表格、列表和逐字引句，并能证明正文覆盖率。
- 失败块阻止完整草稿；重试只重跑失败块。
- `entitie -> entity` 通过草稿执行并保留人工内容。
- 模型调用期间 status、页面读取和 watcher 不被全局锁阻塞。
- 状态摘要不执行全库 lint，revision/ETag 无变化时稳定。
- schema 迁移幂等且不改写不可变来源。
- 同一 Vault 的第二个写进程被明确拒绝。
- `control.json` 跨重启保持 Vault ID/token，轮换使旧 token 失效，capabilities 不泄漏秘密。
- `/api/v1` 错误、幂等和跨端链接合同通过兼容测试。

### Phase 1

- 同 URL 同正文不创建新 Snapshot；正文变化创建新版本。
- 不同 URL 相同正文保留不同来源身份。
- URL scheme、私网、DNS rebinding、重定向、超时、大小和 Content-Type 安全测试。
- 403、登录页、空正文和低质量正文产生可执行错误。
- 文件、URL 和粘贴任务中断后恢复或重试不重复归档。
- 插件离线、发现文件缺失、token 失效、Vault 不匹配和 API 不兼容均安全降级。
- 插件 URL/粘贴超时重试使用同一 Idempotency-Key，不重复建任务。
- 插件待办轮询不触发 lint、不阻塞 watcher、不泄漏 token。

### Phase 2-3

- 页面 API 正确返回 frontmatter、正文、来源、入链和出链。
- 普通双链、来源边和语义关系解析一致，关系段链接不重复计边。
- graph delta 正确报告节点、边和断链变化。
- 每条语义边都能回到逐字引句和原始资料。
- Markdown 预览不执行脚本、危险 HTML 或非允许 URL scheme。
- 中文、空格和特殊字符页面的 Web/Obsidian 深链正确。
- 插件当前页上下文与 Web/图谱聚焦同一稳定 page ID。

### 浏览器与插件验收

引入 Web 新界面后使用 Playwright 覆盖桌面和移动视口：

- 文件、URL、粘贴三种采集入口。
- 任务阶段、失败重试、草稿 Diff、审核详情和基线冲突。
- 图谱非空、局部聚焦、类型/关系筛选、边证据和侧栏联动。
- 画布、工具栏、文本和侧栏无重叠，状态变化不导致布局跳动。
- 页面预览安全，跨端链接准确且不含 token。

Obsidian 插件首版只验收桌面端，使用可重复集成脚本或记录版本的手工矩阵覆盖安装、升级、离线、错误 Vault、采集和当前页跳转。移动端不作为近期完成条件。

未实现的测试不得写成已通过；每个路线图阶段只有在对应自动化和手工验收完成后才能改为 `done`。
