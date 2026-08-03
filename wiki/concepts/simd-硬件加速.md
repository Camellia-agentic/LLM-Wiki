---
title: "SIMD 硬件加速"
type: concept
sources:
  - "raw/sources/minio-7a661c20f7.md"
updated: 2026-07-17
---
# SIMD 硬件加速

## 概念说明

MinIO 利用 CPU 的 SIMD 指令集（如 AVX-512）加速纠删码计算和哈希校验，使读写速度可跑满 100GbE 网卡和 NVMe 固态硬盘的物理极限。
