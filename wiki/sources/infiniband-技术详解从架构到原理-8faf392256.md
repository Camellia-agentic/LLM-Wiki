---
title: "InfiniBand 技术详解：从架构到原理"
type: source_summary
sources:
  - "raw/sources/infiniband-8ddb39301e.md"
updated: 2026-07-17
---

# InfiniBand 技术详解：从架构到原理

## 摘要

InfiniBand 是一种高性能、低延迟、高可靠性的网络互连技术，主要用于 HPC、AI 和大规模数据中心场景。其核心设计目标是为计算节点和存储设备之间提供极速稳定的数据传输通道。

## 原始资料

[raw/sources/infiniband-8ddb39301e.md](../../raw/sources/infiniband-8ddb39301e.md)

## 原文结构

- InfiniBand 技术详解：从架构到原理
- 1. 概述
- 2. 诞生背景
- 3. 核心架构
- 3.1 点对点交换架构
- 3.2 核心硬件组件
- 4. 分层协议栈（Protocol Stack）
- 5. 核心通信机制：应用程序直接访问硬件
- 5.1 队列对（QP, Queue Pair）
- 5.2 Verbs 接口
- 5.3 RDMA 与零拷贝（Zero-Copy）
- 6. 无损网络的基石：信用流控
- 6.1 基于信用的链路层流控
- 6.2 虚拟通道（VL, Virtual Lane）
- 7. 拥塞控制与网络管理
- 7.1 拥塞控制
- 7.2 子网管理器（SM, Subnet Manager）
- 8. 代际演进与性能对比

## 相关页面

- [[wiki/concepts/rdma]]
- [[wiki/concepts/信用流控]]
- [[wiki/concepts/子网管理器-sm]]
- [[wiki/concepts/虚拟通道-vl]]
- [[wiki/concepts/队列对-qp]]
- [[wiki/entities/hca]]
- [[wiki/entities/ib-交换机]]
- [[wiki/entities/ibta]]
- [[wiki/entities/nvidiamellanox]]

## 建议关联

- [[wiki/sources/infiniband-技术详解从架构到原理-8faf392256]]
