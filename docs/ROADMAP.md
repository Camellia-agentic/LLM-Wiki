---
title: Local LLM Wiki 后续路线图
status: planned
updated: 2026-07-20
---

# 后续路线图

P0-P2 已实现：本机控制中心、草稿 Diff 与恢复、状态与回收站、人工内容保护、重复概念候选及显式别名/合并 API。

## P3：薄 MCP 集成

目标是让 Agent 使用与控制中心相同的本地操作面，而不是复制业务逻辑或直接编辑运行时 JSON。

- 以本机控制中心 API 为唯一后端；MCP 仅做参数校验和请求转发。
- 第一阶段只暴露 `status`、`search`、`draft list/show`、`review list`、`lint` 等只读工具。
- 写操作必须保留草稿与确认边界：Agent 可以创建草稿、读取 Diff，但不能绕过 `accept`、回收站和永久删除确认。
- 密钥继续只从本地进程环境变量读取；MCP 不持久化模型密钥，也不监听非本机地址。
- 在 UI/API 契约稳定、草稿恢复与并发测试补齐后再开始实现。

不在 P3 范围内：多人空间、Git 分支协作、Tauri 桌面应用、PostgreSQL/pgvector、完整 OKF 迁移或云端权限系统。
