# 深度技术复盘：Kubernetes 核心组件的底层链路与生命周期

**复盘对象：** `kubeadm`、`kubectl`、`containerd`、`Calico`
**核心视角：** 摒弃表层概念，从系统初始化、Pod 生命周期及网络包流转三个物理视角，深度拆解 K8s 黄金搭档的协作机制。

---

## 宏观架构


| 组件名称           | 角色隐喻        | 核心职责与底层协议                                                                                                                                     |
| -------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **kubeadm**    | **造物主/包工头** | 负责集群的**引导（Bootstrap）**。生成 PKI 证书体系，通过修改配置触发 Kubelet 的隐藏机制拉起控制面。                                                                               |
| **kubectl**    | **指挥官的对讲机** | 用户级命令行工具。通过读取 `kubeconfig`，将 YAML 意图转化为 JSON，通过 **HTTP/2 REST API** 传递给 `kube-apiserver`。                                                     |
| **containerd** | **底层车间主任**  | 剥离了 Docker 臃肿组件的纯粹容器引擎。实现 **CRI (Container Runtime Interface)** 标准，接收 Kubelet 的 gRPC 指令，负责容器沙箱创建、镜像拉取与物理进程管理。                                 |
| **Calico**     | **全球路由枢纽**  | 基于三层路由（L3）的高级网络插件。实现 **CNI (Container Network Interface)** 标准。负责 Pod IP 分配 (IPAM)、跨主机 BGP 路由广播及基于 `iptables/eBPF` 的网络安全策略 (NetworkPolicy) 落地。 |


---

## `kubeadm` （Static Pod 机制）

很多人在学习 K8s 时的第一个疑问是：既然 `kube-apiserver`、`etcd` 也是容器跑在集群里的，那是谁在集群还没建立时启动了它们？

`kubeadm init` 的底层魔法叫做 **Static Pod（静态 Pod）机制**：

1. **环境准备与发证 (PKI)：** `kubeadm` 首先在宿主机上生成集群 CA 根证书，以及 `apiserver`、`etcd` 等所需的各种 SSL 证书，并生成 `kubeconfig`。
2. **植入“种子” (Manifests)：** 这是最关键的一步。`kubeadm` 会在宿主机的 `/etc/kubernetes/manifests` 目录下生成四个 YAML 文件：`etcd.yaml`、`kube-apiserver.yaml`、`kube-controller-manager.yaml`、`kube-scheduler.yaml`。
3. **Kubelet 直接越权启动：**

- 作为系统守护进程启动的 `Kubelet`，具有一个特殊的轮询机制：它会定期检查 `--pod-manifest-path`（即上述目录）。
- 一旦发现这些 YAML，`Kubelet` **不会去向还在沉睡的 API Server 汇报**，而是直接调用本地的 `containerd` (CRI)，将这四个组件作为静态 Pod 强行拉起。
- 等到 API Server 启动并提供服务后，控制面才算真正建立，集群开始接收外部请求。

---

## Pod 创建 (CRI & CNI 的握手)

当我们敲下 `kubectl apply -f app.yaml` 时，背后是一场跨越多个组件的精密调度：

### 阶段 1：管控面指令下发

1. `kubectl` 解析 YAML，向 API Server 发送 POST 请求。
2. API Server 将期望状态（Desired State）写入 `etcd`。
3. 调度器 (`kube-scheduler`) 监听到新 Pod，根据算法将其分配至 Node-A，并将调度结果写回 API Server。

### 阶段 2：数据面认领与启动沙箱 (Kubelet -> containerd)

1. Node-A 的 `Kubelet` 监听到有 Pod 分配给自己。
2. `Kubelet` 通过 gRPC 调用 `containerd` (CRI 接口)，下发 `RunPodSandbox` 指令。
3. **Pause 容器机制：** `containerd` 并非直接启动业务代码，而是先启动一个极小的 **Pause 容器（沙箱）**。它的唯一作用是**占坑并持有 Linux Namespace (如 Network, IPC, UTS)**。后续所有的业务容器都会加入这个已创建的 Namespace 中共享网络。

### 阶段 3：注入灵魂——网络分配 (Kubelet -> Calico)

1. 沙箱启动后，`Kubelet` 发现有了网络命名空间，立即触发 CNI 钩子，调用 Calico 二进制文件。
2. **IPAM 分配：** Calico 为该 Pod 分配一个集群内唯一的 IP。
3. **Veth Pair 连通：** 创建一对虚拟网卡，一头叫 `eth0` 塞入 Pod，另一头（如 `cali-xxx`）挂在宿主机上，打通微观网络通道。

### 阶段 4：业务正式上线

1. 网络就绪后，`Kubelet` 再次通过 CRI 接口调用 `containerd` 执行 `StartContainer`。
2. `containerd` 拉起实际业务容器（此时挂载进 Pause 容器的网络和存储环境中）。Pod 状态正式跃迁为 `Running`。

---

## Calico 核心网络层 (L3 Routing)

当集群拥有数百个节点、数万个 Pod 时，网络包是如何跨主机精准投递的？Calico 将每一台 Node 都变成了一台“软路由”。

### 1. 核心守护组件 (DaemonSet)

在每台节点上，Calico 都运行着 `calico-node`：

- **Felix（执行层）：** 负责监听 K8s 资源变化，动态修改宿主机的 Linux 路由表，并管理 `iptables` / `eBPF` 规则以执行 NetworkPolicy（网络隔离）。
- **BIRD（控制层）：** 工业级 BGP (Border Gateway Protocol) 路由守护进程。当 Felix 为本地 Pod 分配了 IP 后，**BIRD 立刻向全网所有节点广播这条路由信息**。

### 2. 跨主机传输模式解析

- **Native BGP 模式 (无封包/高性能)：**
- **前提：** 所有宿主机位于同一个二层网络（物理交换机相连）。
- **机制：** Pod-A 访问跨主机的 Pod-B 时，数据包走出宿主机时无需任何伪装。物理交换机直接根据 BGP 广播的路由表，将包路由至 Node-B。这是损耗最低的模式。
- **IPIP / VXLAN 隧道模式 (Overlay 封包)：**
- **前提：** 部署在公有云（AWS/阿里云）等跨可用区/跨子网环境。底层云厂商的路由器会丢弃无法识别的 Pod IP 数据包。
- **机制：** Calico 启用隧道技术。在原始数据包外部，**再套上一层宿主机 Node-A 发往 Node-B 的合法 IP 报文头**。数据包顺利穿过云端路由器，到达 Node-B 后被解包剥离，露出真实的内部 Pod IP。

### 3. 大规模集群的架构瓶颈突破：Typha

在节点数极多（如 >100）时，每个节点上的 `Felix` 都去向 `kube-apiserver` (或 etcd) 发起长连接拉取状态，会引发严重的性能风暴。

- **解决方案：** 引入 **Typha** 组件（部署 3~5 个即可）。Typha 作为“汇聚层”统一监听 API Server，而成百上千的 Felix 转而与 Typha 建立连接。这种扇出（Fan-out）架构完美解决了管控面的并发瓶颈。

---

## 总结

这四大组件分别代表了云原生时代的四个核心基座：**集群生命周期管理 (kubeadm)**、**声明式 API 交互 (kubectl)**、**计算资源抽象 (containerd)** 与 **全球网络拓扑 (Calico)**。

它们互不干涉内部实现，仅依靠极度克制与严谨的接口标准（CRI、CNI、REST API、BGP）进行弱耦合协作。正是这种架构哲学，赋予了 Kubernetes 统治整个云计算时代的无限扩展能力。