---
title: "Static Pod 机制"
type: concept
sources:
  - "raw/sources/kubernetes-核心组件-13d6171753.md"
updated: 2026-07-17
---
# Static Pod 机制

## 概念说明

kubeadm 通过将控制面组件 YAML 写入 /etc/kubernetes/manifests，由 Kubelet 直接调用 containerd 拉起，无需依赖 API Server。
