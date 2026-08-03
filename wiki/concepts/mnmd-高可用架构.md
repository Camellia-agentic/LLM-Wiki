---
title: "MNMD 高可用架构"
type: concept
sources:
  - "raw/sources/minio-7a661c20f7.md"
updated: 2026-07-17
---
# MNMD 高可用架构

## 概念说明

多节点多驱动器架构下，MinIO 通过读写仲裁法则（读仲裁 N，写仲裁 N/2+1）防止脑裂，确保 CAP 定理中的 CP 属性。
