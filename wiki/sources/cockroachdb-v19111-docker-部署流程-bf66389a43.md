---
title: "CockroachDB v19.1.11 Docker 部署流程"
type: source_summary
sources:
  - "raw/sources/cockroach部署流程-af5626b479.md"
updated: 2026-07-20
---

# CockroachDB v19.1.11 Docker 部署流程

## 摘要

本文档详细记录了使用 Docker 部署 CockroachDB v19.1.11 的完整流程，包括目录结构、Dockerfile 编写、启动脚本、二进制文件获取、镜像构建、命名卷权限处理、容器启动命令及验证方法。

## 原始资料

[raw/sources/cockroach部署流程-af5626b479.md](../../raw/sources/cockroach部署流程-af5626b479.md)

## 原文结构

- CockroachDB v19.1.11 Docker 部署流程
- 1. 目录结构
- 2. `Dockerfile`（完整内容）
- 3. `cockroach.sh`（完整内容与获取方式）
- 3.1 获取方式
- 3.2 完整内容
- 4. cockroach 二进制获取（Linux）
- 5. 构建镜像
- 6. 命名卷权限（避免 permission denied）
- 1. 查看容器内 cockroach 用户的实际 uid 和 gid
- 2. 临时以 root 身份启动容器，将命名卷的数据目录 chown 给上面查到的 uid:gid
- 7. 启动容器（必须带 start）
- 清理旧容器（若存在）
- 启动新容器
- 8. 验证
- 9. 常用命令汇总

## 相关页面

- [[wiki/concepts/cockroachdb]]
- [[wiki/concepts/docker-部署]]
- [[wiki/concepts/命名卷权限]]
- [[wiki/concepts/非安全模式---insecure]]
- [[wiki/entities/admin-ui]]
- [[wiki/entities/cockroachdb-v19111]]
- [[wiki/entities/cockroachsh]]
