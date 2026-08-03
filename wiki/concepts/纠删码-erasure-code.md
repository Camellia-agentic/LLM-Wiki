---
title: "纠删码 (Erasure Code)"
type: concept
sources:
  - "raw/sources/minio-7a661c20f7.md"
updated: 2026-07-17
---
# 纠删码 (Erasure Code)

## 概念说明

MinIO 采用纠删码替代传统三副本，将对象切分为数据块和校验块，在允许同时损坏一半硬盘的情况下，磁盘利用率提升至 50% 以上。
