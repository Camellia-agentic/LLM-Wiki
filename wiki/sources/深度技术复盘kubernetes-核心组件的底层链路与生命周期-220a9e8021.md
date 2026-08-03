---
title: "深度技术复盘：Kubernetes 核心组件的底层链路与生命周期"
type: source_summary
sources:
  - "raw/sources/kubernetes-核心组件-13d6171753.md"
updated: 2026-07-17
---

# 深度技术复盘：Kubernetes 核心组件的底层链路与生命周期

## 摘要

本文深度复盘了 Kubernetes 核心组件 kubeadm、kubectl、containerd 和 Calico 的底层链路与生命周期，从系统初始化、Pod 创建及网络包流转三个物理视角拆解其协作机制。

## 原始资料

[raw/sources/kubernetes-核心组件-13d6171753.md](../../raw/sources/kubernetes-核心组件-13d6171753.md)

## 原文结构

- 深度技术复盘：Kubernetes 核心组件的底层链路与生命周期
- 宏观架构
- `kubeadm` （Static Pod 机制）
- Pod 创建 (CRI & CNI 的握手)
- 阶段 1：管控面指令下发
- 阶段 2：数据面认领与启动沙箱 (Kubelet -> containerd)
- 阶段 3：注入灵魂——网络分配 (Kubelet -> Calico)
- 阶段 4：业务正式上线
- Calico 核心网络层 (L3 Routing)
- 1. 核心守护组件 (DaemonSet)
- 2. 跨主机传输模式解析
- 3. 大规模集群的架构瓶颈突破：Typha
- 总结

## 相关页面

- [[wiki/concepts/bgp-路由]]
- [[wiki/concepts/cni-与-cri]]
- [[wiki/concepts/pause-容器]]
- [[wiki/concepts/static-pod-机制]]
- [[wiki/concepts/typha]]
- [[wiki/entities/calico]]
- [[wiki/entities/containerd]]
- [[wiki/entities/kubeadm]]
- [[wiki/entities/kubectl]]
- [[wiki/entities/kubelet]]

## 建议关联

- [[wiki/sources/kubernetes-常用命令-cheat-sheet-3cb5abaf25]]
- [[wiki/sources/docker-常用命令-cheat-sheet-b0d7e4a21f]]
- [[wiki/sources/infiniband-技术详解从架构到原理-8faf392256]]
