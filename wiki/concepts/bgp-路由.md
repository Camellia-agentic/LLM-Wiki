---
title: "BGP 路由"
type: concept
sources:
  - "raw/sources/kubernetes-核心组件-13d6171753.md"
updated: 2026-07-17
---
# BGP 路由

## 概念说明

Calico 使用 BIRD 守护进程广播 Pod IP 路由，实现跨主机三层路由，支持 Native BGP（无封包）和 IPIP/VXLAN 隧道模式。
