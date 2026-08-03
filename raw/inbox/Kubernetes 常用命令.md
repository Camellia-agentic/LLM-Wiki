# Kubernetes 常用命令 (Cheat Sheet)

本文档整理了日常运维与云原生开发中最常用的 `kubectl` 命令，按资源类型和操作场景分类，方便快速查阅。

## 1. 基础与集群上下文 (Cluster & Context)


| 命令场景          | 命令示例                                        | 参数说明                                              |
| ------------- | ------------------------------------------- | ------------------------------------------------- |
| **查看集群信息**    | `kubectl cluster-info`                      | 显示 Master 节点和常用服务的地址。                             |
| **查看所有上下文**   | `kubectl config get-contexts`               | 列出 `kubeconfig` 中配置的所有集群上下文。                      |
| **切换上下文**     | `kubectl config use-context <context-name>` | 切换到指定集群上下文（常用于多测试/生产环境切换）。                        |
| **查看当前配置**    | `kubectl config view`                       | 显示合并后的 kubeconfig 设置。                             |
| **查看 API 资源** | `kubectl api-resources`                     | 列出集群支持的所有资源类型及其简写（如 pods/po, deployments/deploy）。 |


---

## 2. 命名空间管理 (Namespaces)


| 命令场景         | 命令示例                                                    | 参数说明                                |
| ------------ | ------------------------------------------------------- | ----------------------------------- |
| **查看命名空间**   | `kubectl get ns`                                        | 列出所有命名空间。                           |
| **创建命名空间**   | `kubectl create ns <namespace-name>`                    | 快速创建一个新的命名空间。                       |
| **切换默认命名空间** | `kubectl config set-context --current --namespace=<ns>` | 将当前上下文的默认命名空间切换为指定值，省去每次敲 `-n` 的麻烦。 |


---

## 3. Pod 运维与排障 (Pods & Debugging)


| 命令场景          | 命令示例                                                      | 参数说明                                                                      |
| ------------- | --------------------------------------------------------- | ------------------------------------------------------------------------- |
| **查看 Pod 列表** | `kubectl get pods -n <ns>`                                | `-A` 查看所有命名空间；`-o wide` 显示 IP 和所在节点。                                      |
| **查看 Pod 详情** | `kubectl describe pod <pod-name>`                         | 核心排障命令：详细输出事件 (Events)、状态和资源请求/限制（排查 GPU 分配不足或 OOM 的首选）。                  |
| **查看 Pod 日志** | `kubectl logs -f <pod-name>`                              | `-f` 持续跟踪；`--tail 100` 查看最后 100 行；`-c <container-name>` 指定多容器 Pod 中的具体容器。 |
| **进入 Pod 终端** | `kubectl exec -it <pod-name> -- /bin/bash`                | 分配交互式终端。如果是 alpine 系统请使用 `/bin/sh`。                                       |
| **删除 Pod**    | `kubectl delete pod <pod-name>`                           | `--force --grace-period=0` 用于强制删除一直卡在 Terminating 状态的 Pod。                |
| **本地端口转发**    | `kubectl port-forward <pod-name> <local_port>:<pod_port>` | 将本地端口流量转发到 Pod，常用于不暴露外部 IP 的情况下直连数据库或中间件进行调试。                             |
| **容器与本地拷文件**  | `kubectl cp <local_path> <ns>/<pod-name>:<path>`          | 反向拷贝为 `kubectl cp <ns>/<pod-name>:<path> <local_path>`。                   |


---

## 4. 部署与应用生命周期 (Deployments)


| 命令场景        | 命令示例                                                  | 参数说明                                             |
| ----------- | ----------------------------------------------------- | ------------------------------------------------ |
| **查看部署状态**  | `kubectl get deploy`                                  | 查看当前命名空间下 Deployment 的副本和就绪状态。                   |
| **应用扩缩容**   | `kubectl scale deploy <deploy-name> --replicas=<num>` | 快速手动调整应用的实例副本数量。                                 |
| **滚动重启**    | `kubectl rollout restart deploy <deploy-name>`        | 触发 Deployment 的无缝滚动重启（常用于重新拉取 `latest` 镜像或刷新配置）。 |
| **查看回滚历史**  | `kubectl rollout history deploy <deploy-name>`        | 查看部署的修订版本历史记录。                                   |
| **回滚到上个版本** | `kubectl rollout undo deploy <deploy-name>`           | 撤销上一次的发布；可通过 `--to-revision=<num>` 指定回滚到特定版本。    |


---

## 5. 服务与网络 (Services & Ingress)


| 命令场景           | 命令示例                                                                | 参数说明                                   |
| -------------- | ------------------------------------------------------------------- | -------------------------------------- |
| **查看服务列表**     | `kubectl get svc`                                                   | 查看 Service 的 ClusterIP、映射端口及外部 IP。     |
| **暴露服务**       | `kubectl expose deploy <deploy-name> --port=<port> --type=NodePort` | 快速为现有的 Deployment 声明一个 Service 进行网络暴露。 |
| **查看 Ingress** | `kubectl get ing`                                                   | 查看七层路由规则和绑定的域名。                        |


---

## 6. 节点管理与资源监控 (Nodes & Resources)


| 命令场景       | 命令示例                                            | 参数说明                                                                 |
| ---------- | ----------------------------------------------- | -------------------------------------------------------------------- |
| **查看节点列表** | `kubectl get nodes -o wide`                     | 查看节点状态、版本、内外部 IP 及 OS 版本（常用于系统迁移前后核对）。                               |
| **查看节点详情** | `kubectl describe node <node-name>`             | 重点查看 Capacity/Allocatable（如显卡数量 `nvidia.com/gpu` 等）及节点的 Taints (污点)。 |
| **查看资源消耗** | `kubectl top nodes` / `kubectl top pods`        | 查看实时的 CPU 和内存使用率（前提：集群已安装 Metrics Server）。                           |
| **封锁节点**   | `kubectl cordon <node-name>`                    | 将节点标记为不可调度（新 Pod 将不会被分配到此节点，但已有的不受影响）。                               |
| **驱逐节点**   | `kubectl drain <node-name> --ignore-daemonsets` | 腾空节点用于硬件维护或系统升级，安全驱逐该节点上的所有 Pod。                                     |
| **解除封锁**   | `kubectl uncordon <node-name>`                  | 恢复节点的正常调度。                                                           |


---

## 7. 声明式配置管理 (Declarative Management)


| 命令场景              | 命令示例                                                    | 参数说明                                      |
| ----------------- | ------------------------------------------------------- | ----------------------------------------- |
| **应用配置**          | `kubectl apply -f <file.yaml>`                          | 创建或更新 YAML 文件中定义的资源（GitOps 与生产环境的标准推荐方式）。 |
| **批量应用配置**        | `kubectl apply -f <dir/>`                               | 批量应用目录下所有的 YAML 配置文件。                     |
| **删除配置**          | `kubectl delete -f <file.yaml>`                         | 干净地清理 YAML 文件中定义的所有相关资源。                  |
| **试运行 (Dry Run)** | `kubectl apply -f <file.yaml> --dry-run=client -o yaml` | 校验 YAML 语法及配置是否正确而不向集群实际提交修改。             |
| **导出资源配置**        | `kubectl get <resource> <name> -o yaml > export.yaml`   | 将集群中现有运行的资源导出为 YAML 格式，方便备份或二次修改。         |


