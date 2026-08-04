---
title: Local LLM Wiki 后续路线图
status: active
updated: 2026-08-03
implementation_version: "0.2.0"
---

# 后续路线图

**实施版本 0.2.0** 已完成设计文档 Phase 0–4 的主体能力。技术说明见 [TECHNICAL.md](TECHNICAL.md)，验收见 [ACCEPTANCE.md](ACCEPTANCE.md)。

## 当前已实现

- `llm_wiki/` 业务包：分块分析、采集、Job、关系、语义图谱、MCP
- 长文分块（消除 14000 字符截断）、schema v2、`control.json`、单实例锁
- `/api/v1` 采集、任务、页面、图谱、graph-delta
- Web 三工作区（`web/`）：收集、待处理、知识 + Canvas 局部图
- 语义 relations（frontmatter + `## 关系`）、graph delta
- Obsidian 插件源码（侧栏、URL/粘贴、待办角标）
- 薄 MCP（`wiki.py mcp`）、PWA manifest/service worker
- 56 项自动化测试

## Phase 0：正确性、并发与客户端基础

状态：**完成**

- [x] 长文分块与证据合并
- [x] `type: entity` 新建页修复
- [x] 静态前端 `web/`
- [x] schema v2、单实例锁、`control.json`
- [x] `/api/v1` 基础合同

遗留：`entitie` 历史页需通过可审阅草稿或专用迁移命令批量修正。

## Phase 1：统一采集闭环 + 插件 v0.1

状态：**完成**

- [x] 文件、URL、粘贴适配器与 Job 阶段机
- [x] URL 安全边界、幂等键、快照版本去重
- [x] Web 收集工作区
- [x] 插件连接、待办、URL/粘贴（源码）

## Phase 2：知识浏览、导航图 + 插件 v0.2

状态：**完成**

- [x] page/list/context/graph API
- [x] Web 知识工作区（搜索、预览、Canvas 图）
- [x] 插件侧栏当前页上下文

遗留：Playwright 浏览器自动化验收。

## Phase 3：证据化语义图谱

状态：**完成**

- [x] 受控 relations 提取与页面渲染
- [x] 语义图边元数据（谓词、证据）
- [x] `GET /api/v1/drafts/{id}/graph-delta`
- [x] 插件语义图深链（打开 Web `#/graph`）

## Phase 4：体验与受控扩展

状态：**大部分完成**

- [x] PWA manifest + service worker（静态缓存）
- [x] 薄 MCP（只读转发）
- [x] 插件打包配置（esbuild）
- [ ] 浏览器剪藏器独立扩展
- [ ] Playwright CI 门禁
- [ ] Obsidian 社区插件发布
- [ ] Tauri（仅当系统托盘等成为硬需求）

## 暂不纳入

- 公众号/X 登录抓取、Cookie 持久化
- Obsidian Mobile 远程访问
- 多人协作、云端账号、RBAC
- PostgreSQL、pgvector、独立图数据库
- 插件内 LLM / 第二套 pipeline
- 替代 Obsidian 编辑器
- 自动合并概念 / 自动接受草稿
