---
title: "CNI 与 CRI"
type: concept
sources:
  - "raw/sources/kubernetes-核心组件-13d6171753.md"
updated: 2026-07-17
---
# CNI 与 CRI

## 概念说明

CRI 是 Kubelet 与容器运行时（如 containerd）的 gRPC 接口；CNI 是 Kubelet 与网络插件（如 Calico）的接口，负责 Pod 网络分配。
