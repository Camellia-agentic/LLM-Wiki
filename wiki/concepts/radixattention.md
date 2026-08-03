---
title: "RadixAttention"
type: concept
sources:
  - "raw/sources/slime-cdce34acd2.md"
updated: 2026-07-17
---
# RadixAttention

## 概念说明

SGLang中的注意力机制，在生成多条同前缀轨迹时共享KV Cache，将Prefill成本从O(G)降为O(1)。
