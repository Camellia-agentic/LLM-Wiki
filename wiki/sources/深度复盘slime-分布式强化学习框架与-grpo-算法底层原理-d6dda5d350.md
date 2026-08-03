---
title: "深度复盘：Slime 分布式强化学习框架与 GRPO 算法底层原理"
type: source_summary
sources:
  - "raw/sources/slime-cdce34acd2.md"
updated: 2026-07-17
---

# 深度复盘：Slime 分布式强化学习框架与 GRPO 算法底层原理

## 摘要

本文深度复盘了清华大学THUDM团队开源的Slime分布式强化学习框架与GRPO算法。Slime通过异步Actor-Learner架构、高带宽权重同步和精确掩码，解决了大模型RL训练中的算力闲置与显存瓶颈。GRPO算法用组内相对优势计算替代传统Critic模型，大幅降低显存消耗。两者结合，利用SGLang的RadixAttention实现高效组采样，成为顶级逻辑推理模型后训练的黄金标准。

## 原始资料

[raw/sources/slime-cdce34acd2.md](../../raw/sources/slime-cdce34acd2.md)

## 原文结构

- 深度复盘：Slime 分布式强化学习框架与 GRPO 算法底层原理
- Slime 框架
- 1. 异步 Actor-Learner 架构 (A2C 思想的分布式延伸)
- 2. 高带宽权重同步 (Weight Synchronization)
- 3. Agentic 轨迹切分与精确掩码 (Precise Loss Masking)
- GRPO 算法
- 1. 组采样 (Group Sampling)
- 2. 组内相对优势计算 (Relative Advantage)
- 3. 释放极端的显存红利
- 软硬协同：为什么 Slime 是 GRPO 的终极载体？

## 相关页面

- [[wiki/concepts/grpo算法]]
- [[wiki/concepts/radixattention]]
- [[wiki/concepts/slime框架]]
- [[wiki/entities/megatron-lm]]
- [[wiki/entities/sglang]]
- [[wiki/entities/清华大学thudm团队]]

## 建议关联

- [[wiki/sources/深度复盘报告dspark--置信度调度的半自回归高并发投机解码系统-388c00de77]]
- [[wiki/sources/深度复盘报告minio--云原生与-ai-时代的高性能去中心化对象存储-65539e51da]]
- [[wiki/sources/infiniband-技术详解从架构到原理-8faf392256]]
