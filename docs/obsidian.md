---
title: Obsidian 集成决策记录
status: accepted
updated: 2026-08-03
superseded_by: INTERACTION_AND_GRAPH_DESIGN.md
---

# Obsidian 集成决策记录

本文记录“Obsidian 为家 + 本机 API 为引擎 + 双端薄客户端”方案的决策理由与校准结果。完整架构、数据模型、API、交互和实施阶段以 [Obsidian 优先的采集、交互与知识图谱设计](INTERACTION_AND_GRAPH_DESIGN.md) 为唯一权威，实施状态以 [ROADMAP](ROADMAP.md) 为准。本文不再复制完整路线图，避免两套设计分叉。

## 决策

```text
Obsidian（知识主场）
  - 阅读、编辑、人工补充、双链、反向链接、导航图
  - 薄插件提供采集入口、待办角标、当前页上下文和跳转
                    |
                    | 同一 Vault + 版本化 loopback API
                    v
Python 本机服务（唯一业务层）
  - 来源身份、不可变快照、Job、分块分析、草稿闸门、检索、图谱派生
                    |
                    v
Web 控制中心（任务与证据主场）
  - 来源时间线、失败重试、草稿 Diff、事实核验、待补充、语义图谱
```

核心原则：Markdown Vault 是唯一知识真相源；Python 是唯一业务实现；客户端可以替换，业务逻辑不能复制。

## 为什么不是纯 Web 或纯插件

| 方案 | 主要问题 | 结论 |
| --- | --- | --- |
| 纯 Web | 重做 Markdown 深度编辑、双链和阅读体验 | Web 不替代 Obsidian |
| 纯 Obsidian 插件 | 需要在 TypeScript 中重做 URL 安全、Diff、任务恢复和图谱 | 插件保持薄 |
| 双端薄客户端 | 用同一 API 分配最合适的交互面 | 采用 |

Web 是完整任务界面，Obsidian 是完整知识界面。插件的价值是降低切换成本，不是把 Web 塞进 Obsidian。

## 对原建议的工程校准

### 1. 日常只运行一个服务模式

`python tools/wiki.py serve` 当前默认已经包含 inbox watcher。不能同时再启动同一 Vault 的 `watch`。无界面时才单独使用 `watch`；只审阅时可使用 `serve --no-watch`。

### 2. 插件必须先解决稳定认证

当前服务 token 每次启动随机生成，只适合同源 Web 页面。插件交付前必须先完成稳定 Vault ID、Git 忽略的本机发现/凭证文件、token 轮换、错误 Vault 校验和 API 主版本协商。这些属于路线图 Phase 0。

### 3. 插件按 API 依赖分步交付

- Phase 1 插件 v0.1：连接、待办角标、URL/粘贴提交、打开任务或草稿。
- Phase 2 插件 v0.2：当前页来源、入链/出链、相关待办、打开 Web 局部图。
- Phase 3：只增加语义图深链，不在插件中重做 Cytoscape。

### 4. 服务离线时不制造假象

服务未启动时，用户仍可手工把本地文件放入 `raw/inbox/`，但不会自动处理。插件必须显示正确启动命令并保留未提交内容，不能声称 watcher 正在运行。

### 5. 首版仅支持 Obsidian Desktop

移动端 `localhost` 指向移动设备本身，无法直接访问桌面 Python 服务。支持移动端意味着引入远程访问、认证和网络安全新边界，近期不纳入。

## 最终职责边界

插件可以：

- 只读 `.llm-wiki/control.json` 做本机服务发现。
- 调用版本化 loopback API。
- 显示连接、计数和当前页上下文。
- 提交 URL/粘贴采集意图。
- 打开服务返回的 Web/Obsidian 路由。

插件不可以：

- 直接写 state、queue、analysis、draft 或 search 数据。
- 运行 LLM、抓取网页或自行归档来源。
- 接受草稿、永久删除或绕过确认闸门。
- 实现独立 Markdown 解析、Diff 或语义图谱数据库。

## 推荐日常流程

```text
1. 运行 serve（已包含 watcher）
2. 在 Obsidian 阅读/写笔记，或把本地资料放入 raw/inbox
3. 用插件提交 URL/粘贴正文，查看待办角标
4. 进入 Web 完成 Diff、核验、失败恢复和语义图探索
5. 应用草稿后回到 Obsidian 深度阅读与人工补充
```

在插件尚未实现前，步骤 3 由当前 Web 控制中心或手工保存 Markdown/TXT 替代；不能把本决策记录描述成当前功能。
