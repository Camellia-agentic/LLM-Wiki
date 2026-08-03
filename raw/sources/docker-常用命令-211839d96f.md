# Docker 常用命令 (Cheat Sheet)

本文档整理了日常运维与开发中最常用的 Docker 命令，按使用场景分类，方便快速查阅和复制。

## 1. 镜像管理 (Image Management)

镜像（Image）是容器运行的只读模板。


| 命令场景       | 命令示例                                             | 参数说明                                           |
| ---------- | ------------------------------------------------ | ---------------------------------------------- |
| **拉取镜像**   | `docker pull <image>:<tag>`                      | 从 Registry 拉取镜像。若不加 tag，默认拉取 `latest`。         |
| **查看本地镜像** | `docker images` 或 `docker image ls`              | `-a` 查看所有镜像；`-q` 仅显示镜像 ID。                     |
| **删除镜像**   | `docker rmi <image_id>`                          | `-f` 强制删除（即使有容器依赖）。                            |
| **构建镜像**   | `docker build -t <name>:<tag> .`                 | `-f <Dockerfile>` 指定特定 Dockerfile；`.` 表示当前上下文。 |
| **镜像打标签**  | `docker tag <source_image> <target_image>:<tag>` | 为本地镜像创建新的标签，常用于推送到远端仓库。                        |
| **推送镜像**   | `docker push <registry>/<image>:<tag>`           | 将本地镜像推送到远程镜像仓库。                                |
| **导出镜像**   | `docker save -o <file.tar> <image>`              | 将镜像打包为 tar 文件（用于离线迁移）。                         |
| **导入镜像**   | `docker load -i <file.tar>`                      | 从 tar 文件加载镜像。                                  |
| **清理无用镜像** | `docker image prune`                             | `-a` 删除所有没有被容器使用的镜像。                           |


---

## 2. 容器生命周期管理 (Container Lifecycle)

容器（Container）是镜像的运行实例。


| 命令场景        | 命令示例                                                                  | 参数说明                                                                                    |
| ----------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **创建并运行容器** | `docker run -d --name <name> -p <host_port>:<container_port> <image>` | `-d` 后台运行；`-p` 端口映射；`-v` 挂载目录；`--gpus all` 挂载所有GPU（AI/深度学习常用）；`--shm-size=8g` 设置共享内存大小。 |
| **启动/停止容器** | `docker start <container>` / `docker stop <container>`                | `<container>` 可以是容器名或容器 ID。                                                             |
| **重启容器**    | `docker restart <container>`                                          | 停止并重新启动容器。                                                                              |
| **强制停止容器**  | `docker kill <container>`                                             | 直接发送 SIGKILL 信号强制终止。                                                                    |
| **删除容器**    | `docker rm <container>`                                               | `-f` 强制删除正在运行的容器；`-v` 同时删除关联的匿名数据卷。                                                     |
| **暂停/恢复容器** | `docker pause <container>` / `docker unpause <container>`             | 暂停/恢复容器内的所有进程。                                                                          |


---

## 3. 容器运维与调试 (Operations & Debugging)


| 命令场景          | 命令示例                                       | 参数说明                                                                                                    |
| ------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| **查看运行中的容器**  | `docker ps`                                | `-a` 查看所有（包括已停止的）；`-q` 仅显示容器 ID。                                                                        |
| **进入容器内部**    | `docker exec -it <container> /bin/bash`    | `-it` 分配交互式伪终端。如果是 alpine 系统可能需要用 `/bin/sh`。                                                            |
| **查看容器日志**    | `docker logs -f --tail 100 <container>`    | `-f` 实时跟踪日志；`--tail 100` 仅查看最后 100 行。                                                                   |
| **查看容器详细信息**  | `docker inspect <container>`               | 输出 JSON 格式详情（包含 IP 挂载点、环境变量等）。可通过 `-f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'` 过滤输出。 |
| **容器与主机间拷文件** | `docker cp <host_path> <container>:<path>` | 反之也可 `docker cp <container>:<path> <host_path>`。                                                        |
| **查看容器资源占用**  | `docker stats`                             | 实时查看 CPU、内存、网络 IO 等使用情况（类似 `top`）。                                                                      |
| **查看容器内进程**   | `docker top <container>`                   | 显示容器内运行的进程信息。                                                                                           |


---

## 4. 数据卷管理 (Volumes)

数据卷用于容器数据的持久化，独立于容器的生命周期。


| 命令场景        | 命令示例                                  | 参数说明                              |
| ----------- | ------------------------------------- | --------------------------------- |
| **列出数据卷**   | `docker volume ls`                    | 列出所有由 Docker 管理的 Volume。          |
| **创建数据卷**   | `docker volume create <volume_name>`  | 手动创建一个 Volume。                    |
| **查看数据卷详情** | `docker volume inspect <volume_name>` | 查看 Volume 的实际宿主机挂载路径（Mountpoint）。 |
| **删除数据卷**   | `docker volume rm <volume_name>`      | 删除指定的数据卷（必须先删除挂载它的容器）。            |
| **清理无用数据卷** | `docker volume prune`                 | 批量删除未被任何容器使用的数据卷。                 |


---

## 5. 网络管理 (Network)

Docker 网络用于容器间的隔离与通信。


| 命令场景         | 命令示例                                              | 参数说明                              |
| ------------ | ------------------------------------------------- | --------------------------------- |
| **列出网络**     | `docker network ls`                               | 查看现有网络列表（默认有 bridge, host, none）。 |
| **创建自定义网络**  | `docker network create <network_name>`            | 创建 bridge 网络，处于同一网络的容器可通过容器名互通。   |
| **查看网络详情**   | `docker network inspect <network_name>`           | 查看连接到该网络的容器列表及其 IP。               |
| **将容器连接到网络** | `docker network connect <network> <container>`    | 将运行中的容器接入指定网络。                    |
| **将容器断开网络**  | `docker network disconnect <network> <container>` | 将容器从指定网络中移除。                      |


---

## 6. 系统状态与深度清理 (System & Cleanup)


| 命令场景         | 命令示例                               | 说明                                                |
| ------------ | ---------------------------------- | ------------------------------------------------- |
| **查看磁盘使用情况** | `docker system df`                 | 查看镜像、容器、数据卷的磁盘空间占用情况。                             |
| **一键清理**     | `docker system prune`              | **高频命令**：清理所有停止的容器、未被使用的网络和悬空镜像（dangling images）。 |
| **深度清理**     | `docker system prune -a --volumes` | **慎用**：不仅清理停止的容器，还会清理所有**未被使用的镜像和数据卷**。           |
| **查看系统信息**   | `docker info`                      | 查看 Docker 整体配置信息（如存储驱动、Cgroup 状态等）。               |


---

## 7. 高级技巧与组合命令 (Advanced & Combos)

- **停止所有运行中的容器：**
  ```bash
  docker stop $(docker ps -q)
  ```
- **删除所有容器：**
  ```bash
  docker rm -f $(docker ps -aq)
  ```
- **格式化输出以供脚本处理：**
  ```bash
  docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Status}}"
  ```

