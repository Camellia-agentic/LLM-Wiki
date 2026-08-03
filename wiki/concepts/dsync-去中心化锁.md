---
title: "dsync 去中心化锁"
type: concept
sources:
  - "raw/sources/minio-7a661c20f7.md"
updated: 2026-07-17
---
# dsync 去中心化锁

## 概念说明

MinIO 内置的轻量级分布式锁，通过哈希将锁定向到特定纠删集合，并采用多数派共识加锁，实现无中心化的强一致性。
