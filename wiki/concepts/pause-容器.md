---
title: "Pause 容器"
type: concept
sources:
  - "raw/sources/kubernetes-核心组件-13d6171753.md"
updated: 2026-07-17
---
# Pause 容器

## 概念说明

containerd 在启动业务容器前先启动的极简容器，用于持有 Linux Namespace（网络、IPC、UTS），后续容器共享该命名空间。
