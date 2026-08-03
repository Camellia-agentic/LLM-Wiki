---
title: "知识库索引"
type: index
sources:
updated: 2026-07-20
---

# 知识库索引

> 本页由 `tools/wiki.py` 维护。先从这里定位主题，再阅读相关页面。

## 资料摘要

- [[wiki/sources/cockroachdb-v19111-docker-部署流程-bf66389a43|CockroachDB v19.1.11 Docker 部署流程]] - 本文档详细记录了使用 Docker 部署 CockroachDB v19.1.11 的完整流程，包括目录结构、Dockerfile 编写、启动脚本、二进制文件获取、镜像构建、命名卷权限处理、容器启动命令及验证方法。 [raw/sources/cockroach部署流程-af5626b479.md](../../raw…
- [[wiki/sources/docker-常用命令-cheat-sheet-b0d7e4a21f|Docker 常用命令 (Cheat Sheet)]] - 本文档整理了日常运维与开发中最常用的 Docker 命令，按使用场景分类，方便快速查阅和复制。 [raw/sources/docker-常用命令-211839d96f.md](../../raw/sources/docker-常用命令-211839d96f.md)
- [[wiki/sources/infiniband-技术详解从架构到原理-8faf392256|InfiniBand 技术详解：从架构到原理]] - InfiniBand 是一种高性能、低延迟、高可靠性的网络互连技术，主要用于 HPC、AI 和大规模数据中心场景。其核心设计目标是为计算节点和存储设备之间提供极速稳定的数据传输通道。 [raw/sources/infiniband-8ddb39301e.md](../../raw/sources/infiniband…
- [[wiki/sources/kubernetes-常用命令-cheat-sheet-3cb5abaf25|Kubernetes 常用命令 (Cheat Sheet)]] - 本文档整理了日常运维与云原生开发中最常用的 kubectl 命令，按资源类型和操作场景分类，方便快速查阅。 [raw/sources/kubernetes-常用命令-9ce92c5186.md](../../raw/sources/kubernetes-常用命令-9ce92c5186.md)
- [[wiki/sources/深度复盘slime-分布式强化学习框架与-grpo-算法底层原理-d6dda5d350|深度复盘：Slime 分布式强化学习框架与 GRPO 算法底层原理]] - 本文深度复盘了清华大学THUDM团队开源的Slime分布式强化学习框架与GRPO算法。Slime通过异步Actor-Learner架构、高带宽权重同步和精确掩码，解决了大模型RL训练中的算力闲置与显存瓶颈。GRPO算法用组内相对优势计算替代传统Critic模型，大幅降低显存消耗。两者结合，利用SGLang的Radix…
- [[wiki/sources/深度复盘报告dspark--置信度调度的半自回归高并发投机解码系统-388c00de77|深度复盘报告：DSpark —— 置信度调度的半自回归高并发投机解码系统]] - DSpark 是 DeepSeek-AI 提出的高并发投机解码系统，通过半自回归草稿生成、置信度校准与异步调度，在无损前提下大幅提升大模型推理吞吐量。 [raw/sources/dspark-99b8b08bc7.md](../../raw/sources/dspark-99b8b08bc7.md)
- [[wiki/sources/深度复盘报告minio--云原生与-ai-时代的高性能去中心化对象存储-65539e51da|深度复盘报告：MinIO —— 云原生与 AI 时代的高性能去中心化对象存储]] - 本文深度复盘了 MinIO 作为云原生与 AI 时代高性能去中心化对象存储的核心架构、底层存储引擎、高可用部署与并发控制机制，并总结了其在 LLM 基础设施中的定位。 [raw/sources/minio-7a661c20f7.md](../../raw/sources/minio-7a661c20f7.md)
- [[wiki/sources/深度技术复盘kubernetes-核心组件的底层链路与生命周期-220a9e8021|深度技术复盘：Kubernetes 核心组件的底层链路与生命周期]] - 本文深度复盘了 Kubernetes 核心组件 kubeadm、kubectl、containerd 和 Calico 的底层链路与生命周期，从系统初始化、Pod 创建及网络包流转三个物理视角拆解其协作机制。 [raw/sources/kubernetes-核心组件-13d6171753.md](../../raw/…
- [[wiki/sources/项目级-codex-约束-1030211684|项目级 Codex 约束]] - - 默认使用简体中文回复。 - 代码标识符、文件路径、命令、API 名称、错误原文等保持英文或原文。 - 不要主动提交 git。 - 只有用户明确要求提交，或明确确认提交后，才可以执行 `git commit`。 [raw/sources/agents-68282cd50d.md](../../raw/sources…

## 概念

- [[wiki/concepts/bgp-路由|BGP 路由]] - Calico 使用 BIRD 守护进程广播 Pod IP 路由，实现跨主机三层路由，支持 Native BGP（无封包）和 IPIP/VXLAN 隧道模式。
- [[wiki/concepts/cni-与-cri|CNI 与 CRI]] - CRI 是 Kubelet 与容器运行时（如 containerd）的 gRPC 接口；CNI 是 Kubelet 与网络插件（如 Calico）的接口，负责 Pod 网络分配。
- [[wiki/concepts/cockroachdb|CockroachDB]] - 一种分布式 SQL 数据库，支持水平扩展、强一致性和高可用性。本文档部署的是 v19.1.11 版本。
- [[wiki/concepts/deployment|Deployment]] - 管理 Pod 副本和滚动更新的控制器，支持声明式扩缩容和回滚。
- [[wiki/concepts/docker-网络-network|Docker 网络 (Network)]] - 用于容器间的隔离与通信，支持 bridge、host、none 等模式。
- [[wiki/concepts/docker-部署|Docker 部署]] - 使用 Docker 容器化技术部署应用，包括编写 Dockerfile、构建镜像、管理卷和端口映射。
- [[wiki/concepts/dsync-去中心化锁|dsync 去中心化锁]] - MinIO 内置的轻量级分布式锁，通过哈希将锁定向到特定纠删集合，并采用多数派共识加锁，实现无中心化的强一致性。
- [[wiki/concepts/grpo算法|GRPO算法]] - Group Relative Policy Optimization，用组内奖励的均值和标准差计算相对优势，替代传统PPO中的Critic模型，减少约50%显存消耗。
- [[wiki/concepts/ingress|Ingress]] - 管理集群外部访问的七层路由规则，通常与域名和 TLS 配合使用。
- [[wiki/concepts/kubectl|kubectl]] - Kubernetes 的命令行工具，用于与集群交互和管理资源。
- [[wiki/concepts/mnmd-高可用架构|MNMD 高可用架构]] - 多节点多驱动器架构下，MinIO 通过读写仲裁法则（读仲裁 N，写仲裁 N/2+1）防止脑裂，确保 CAP 定理中的 CP 属性。
- [[wiki/concepts/pause-容器|Pause 容器]] - containerd 在启动业务容器前先启动的极简容器，用于持有 Linux Namespace（网络、IPC、UTS），后续容器共享该命名空间。
- [[wiki/concepts/pod|Pod]] - Kubernetes 中最小的部署单元，包含一个或多个容器，共享网络和存储。
- [[wiki/concepts/radixattention|RadixAttention]] - SGLang中的注意力机制，在生成多条同前缀轨迹时共享KV Cache，将Prefill成本从O(G)降为O(1)。
- [[wiki/concepts/rdma|RDMA]] - 远程直接内存访问，数据直接从一台机器的内存传输到另一台，绕过操作系统内核和 CPU，实现零拷贝，延迟低于 2 微秒。
- [[wiki/concepts/service|Service]] - 为 Pod 提供稳定的网络访问入口，支持 ClusterIP、NodePort 等类型。
- [[wiki/concepts/simd-硬件加速|SIMD 硬件加速]] - MinIO 利用 CPU 的 SIMD 指令集（如 AVX-512）加速纠删码计算和哈希校验，使读写速度可跑满 100GbE 网卡和 NVMe 固态硬盘的物理极限。
- [[wiki/concepts/slime框架|Slime框架]] - 清华大学THUDM团队开源的分布式强化学习框架，采用异步Actor-Learner架构，通过NCCL直连广播和双缓冲切换实现零停机权重同步，并支持Agentic轨迹的精确掩码。
- [[wiki/concepts/static-pod-机制|Static Pod 机制]] - kubeadm 通过将控制面组件 YAML 写入 /etc/kubernetes/manifests，由 Kubelet 直接调用 containerd 拉起，无需依赖 API Server。
- [[wiki/concepts/typha|Typha]] - Calico 的汇聚层组件，用于解决大规模集群中 Felix 直接连接 API Server 的性能瓶颈，通过扇出架构减少管控面压力。
- [[wiki/concepts/上下文-context|上下文 (Context)]] - kubeconfig 中定义的集群、用户和命名空间的组合，用于切换管理环境。
- [[wiki/concepts/信用流控|信用流控]] - 基于信用的链路层流控机制，接收方预先告知发送方可用缓冲区大小，发送方严格按信用值发送数据，从根本上杜绝丢包，实现无损网络。
- [[wiki/concepts/半自回归生成|半自回归生成]] - DSpark 的草稿生成架构，分为并行骨干网络（O(1) 生成基础 Logits）和轻量马尔可夫串行头（低秩偏置修正多模态碰撞）。
- [[wiki/concepts/去中心化元数据|去中心化元数据]] - MinIO 彻底消灭中心化元数据节点，通过一致性哈希算法将元数据与实际数据绑定，实现 O(1) 时间复杂度的对象定位。
- [[wiki/concepts/命名卷权限|命名卷权限]] - Docker 命名卷默认由 root 用户拥有，当容器以非 root 用户运行时需手动修改卷目录的属主，否则会导致权限不足错误。
- [[wiki/concepts/命名空间-namespace|命名空间 (Namespace)]] - Kubernetes 中用于隔离资源的虚拟集群，常用于多租户或环境划分。
- [[wiki/concepts/声明式配置|声明式配置]] - 通过 YAML 文件定义期望状态，使用 kubectl apply 进行管理的方式。
- [[wiki/concepts/子网管理器-sm|子网管理器 (SM)]] - InfiniBand 网络的集中管理组件，负责发现拓扑、分配 LID、计算路由表并监控网络状态。
- [[wiki/concepts/容器-container|容器 (Container)]] - 镜像的运行实例，提供隔离的进程运行环境。
- [[wiki/concepts/投机解码|投机解码]] - 用小模型起草、大模型验证的加速推理机制，核心延迟公式为 L = (T_draft + T_verify) / τ。
- [[wiki/concepts/数据卷-volume|数据卷 (Volume)]] - 用于容器数据的持久化存储，独立于容器生命周期。
- [[wiki/concepts/纠删码-erasure-code|纠删码 (Erasure Code)]] - MinIO 采用纠删码替代传统三副本，将对象切分为数据块和校验块，在允许同时损坏一半硬盘的情况下，磁盘利用率提升至 50% 以上。
- [[wiki/concepts/置信度校准与异步调度|置信度校准与异步调度]] - 通过序列温度缩放校准概率，硬件感知调度器全局贪心准入，零开销异步调度利用历史信息决定验证预算，保证无损解码。
- [[wiki/concepts/节点-node|节点 (Node)]] - Kubernetes 集群中的工作机器，可以是物理机或虚拟机。
- [[wiki/concepts/虚拟通道-vl|虚拟通道 (VL)]] - 物理链路上划分的逻辑通道，每个 VL 有独立缓冲区和信用流控，用于隔离流量、提供 QoS 保障和防止队头阻塞。
- [[wiki/concepts/镜像-image|镜像 (Image)]] - 容器运行的只读模板，包含应用程序及其依赖环境。
- [[wiki/concepts/队列对-qp|队列对 (QP)]] - 应用程序与 HCA 硬件通信的接口，由发送队列和接收队列组成，应用程序通过工作请求提交任务，HCA 硬件自动完成传输。
- [[wiki/concepts/非安全模式---insecure|非安全模式 (--insecure)]] - CockroachDB 的一种开发模式，免密免 TLS 证书，生产环境应避免使用。

## 实体

- [[wiki/entities/admin-ui|Admin UI]] - CockroachDB 的管理控制台，默认监听 8080 端口，可通过浏览器访问。
- [[wiki/entities/calico|Calico]] - 基于三层路由的 CNI 网络插件，提供 IPAM、BGP 路由广播及 NetworkPolicy 执行。
- [[wiki/entities/ceph|Ceph]] - 分布式存储系统，使用 MDS 管理元数据，与 MinIO 相比架构更复杂。
- [[wiki/entities/cockroachdb-v19111|CockroachDB v19.1.11]] - 本文档部署的 CockroachDB 版本，基于 debian:bookworm-slim 镜像构建 Docker 镜像。
- [[wiki/entities/cockroachsh|cockroach.sh]] - 启动包装脚本，支持 shell 模式和默认模式，用于透传参数给 cockroach 二进制。
- [[wiki/entities/containerd|containerd]] - 实现 CRI 标准的容器运行时，负责容器沙箱创建、镜像拉取与进程管理。
- [[wiki/entities/deepseek-ai|DeepSeek-AI]] - DSpark 论文的出处机构，负责千万级生产环境部署。
- [[wiki/entities/deepseek-v4|DeepSeek-V4]] - DSpark 实际部署的大模型，用于验证系统在高并发场景下的性能。
- [[wiki/entities/docker|Docker]] - 开源的容器化平台，用于自动化应用部署、扩展和管理。
- [[wiki/entities/hca|HCA]] - 主机通道适配器，服务器端的智能网卡，执行 RDMA 等硬件卸载任务，是性能核心。
- [[wiki/entities/hdfs|HDFS]] - 传统分布式文件系统，依赖中心化 NameNode 管理元数据，存在性能瓶颈。
- [[wiki/entities/ib-交换机|IB 交换机]] - 负责子网内部数据包快速转发，只实现物理层和链路层，保证极致转发速度。
- [[wiki/entities/ibta|IBTA]] - InfiniBand 行业协会，1999 年由 Compaq、IBM、Intel、Microsoft 等牵头成立，负责制定 InfiniBand 标准。
- [[wiki/entities/kubeadm|kubeadm]] - Kubernetes 集群引导工具，负责生成 PKI 证书、配置 Static Pod 启动控制面组件。
- [[wiki/entities/kubectl|kubectl]] - 用户级命令行工具，通过 HTTP/2 REST API 向 kube-apiserver 提交声明式配置。
- [[wiki/entities/kubelet|Kubelet]] - 节点上的核心代理，负责监听 Pod 分配、调用 CRI/CNI 接口管理容器生命周期。
- [[wiki/entities/megatron-lm|Megatron-LM]] - Slime框架中负责梯度更新的训练引擎，支持张量并行和流水线并行。
- [[wiki/entities/metrics-server|Metrics Server]] - Kubernetes 集群资源使用指标的聚合器，提供 kubectl top 命令所需的数据。
- [[wiki/entities/minio|MinIO]] - 高性能去中心化对象存储系统，兼容 S3 协议，广泛应用于云原生和 AI 场景。
- [[wiki/entities/nvidiamellanox|NVIDIA/Mellanox]] - InfiniBand 技术的主要供应商，提供 HCA、交换机等硬件产品。
- [[wiki/entities/sglang|SGLang]] - Slime框架中负责高吞吐量轨迹生成的推理引擎，利用PagedAttention和RadixAttention。
- [[wiki/entities/simd|SIMD]] - 单指令多数据流指令集，用于硬件级并行计算，MinIO 利用其加速纠删码运算。
- [[wiki/entities/清华大学thudm团队|清华大学THUDM团队]] - Slime框架和GRPO算法的开源团队。
- [[wiki/entities/纠删码-erasure-code|纠删码 (Erasure Code)]] - 一种数据冗余技术，将数据切分为数据块和校验块，允许部分硬盘损坏时恢复数据。

## 分析与问答

- [[wiki/queries/2026-07-17-这个知识库和传统-rag-有何区别|问答：这个知识库和传统 RAG 有何区别？]] - 根据提供的 Wiki 页面，知识库中没有关于“这个知识库和传统 RAG 有何区别”的信息。这些页面主要介绍了 MinIO、DSpark、InfiniBand、Kubernetes 和 Docker 等技术细节，未涉及知识库系统本身的架构对比。因此，我无法回答这个问题。 - wiki/sources/深度复盘报告min…

## 综合分析

- [[wiki/synthesis/云原生基础设施|云原生基础设施]] - 云原生基础设施涵盖容器编排、高性能存储、高速网络和分布式计算框架，以支持弹性、可扩展的现代应用。Kubernetes 作为核心编排平台，通过 kubeadm、kubectl、containerd 和 Calico 等组件管理 Pod 生命周期与网络。MinIO 提供去中心化对象存储，利用纠删码、SIMD 加速和 ds…
