# CockroachDB v19.1.11 Docker 部署流程

## 1. 目录结构

在任意目录下建立 `cockroach_docker/`，包含以下文件：

```text
cockroach-docker/
├── Dockerfile
├── cockroach         # v19.1.11 Linux 二进制文件
└── cockroach.sh      # 启动包装脚本
```

> **注意**：构建时需进入 `cockroach_docker/` 目录执行 `docker build`，确保构建上下文包含上述三个文件。

---

## 2. `Dockerfile`（完整内容）

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libc6 ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r cockroach && useradd -r -g cockroach cockroach
RUN mkdir -p /cockroach

COPY cockroach.sh cockroach /cockroach/

RUN chmod +x /cockroach/cockroach.sh /cockroach/cockroach && \
    chown -R cockroach:cockroach /cockroach

WORKDIR /cockroach/
VOLUME ["/cockroach/cockroach-data"]
USER cockroach

ENV COCKROACH_CHANNEL=official-docker
EXPOSE 26257 8080

ENTRYPOINT ["/cockroach/cockroach.sh"]
```

---

## 3. `cockroach.sh`（完整内容与获取方式）

### 3.1 获取方式
* **推荐推荐**：在 GitHub 官方仓库中获取：[cockroachdb/cockroach/tree/v19.1.11/build/deploy](https://github.com/cockroachdb/cockroach/tree/v19.1.11/build/deploy)，直接下载并命名为 `cockroach.sh` 放入 `cockroach_docker/` 目录。
* **本地自建**：在 `cockroach_docker/` 下新建文件 `cockroach.sh`，将下面内容原样粘贴保存。

### 3.2 完整内容
```sh
#!/bin/sh
set -eu
if [ "${1-}" = "shell" ]; then
  shift
  exec /bin/sh "$@"
else
  exec /cockroach/cockroach "$@"
fi
```

---

## 4. cockroach 二进制获取（Linux）

1. 打开 Cockroach 官方历史版本发行页：[v19.1 发行日志](https://www.cockroachlabs.com/docs/releases/v19.1)。
2. 下载 Linux 对应的归档包（需与运行环境架构一致，通常为 `amd64`）。
3. 解压压缩包，将其中的可执行文件 `cockroach` 复制到 `cockroach_docker/` 目录下（与 `Dockerfile` 同级）。


---

## 5. 构建镜像

```bash
cd cockroach_docker
docker build -t cockroach:v19.1.11 .
```

---

## 6. 命名卷权限（避免 permission denied）

由于镜像内部采用非 root 用户 `cockroach` 运行，而 Docker 新建的匿名卷/命名卷默认属于 root 用户，直接运行会导致权限不足。需提前修改挂载卷的属主。请将下面命令中的 `XXX`、`YYY` 替换为容器内部查出来的实际 `uid` 和 `gid`。

```bash
# 1. 查看容器内 cockroach 用户的实际 uid 和 gid
docker run --rm cockroach:v19.1.11 shell -c 'id cockroach'

# 2. 临时以 root 身份启动容器，将命名卷的数据目录 chown 给上面查到的 uid:gid
docker run --rm --user root \
  -v cockroach-data:/cockroach/cockroach-data \
  cockroach:v19.1.11 shell -c \
  "chown -R XXX:YYY /cockroach/cockroach-data"
```

---

## 7. 启动容器（必须带 start）

镜像名后的参数会自动通过 `cockroach.sh` 透传给后端的 `cockroach` 二进制文件。**切记不要省略 `start` 参数**，否则只会打印帮助信息。

```bash
# 清理旧容器（若存在）
docker rm -f crdb 2>/dev/null || true

# 启动新容器
docker run -d --name crdb \
  -p 26257:26257 \
  -p 8080:8080 \
  -v cockroach-data:/cockroach/cockroach-data \
  cockroach:v19.1.11 start --insecure \
  --listen-addr=0.0.0.0:26257 \
  --http-addr=0.0.0.0:8080 \
  --advertise-addr=localhost:26257 \
  --store=/cockroach/cockroach-data
```

> 💡 **运维提示**：
> * 远程访问或组建集群时，请将 `--advertise-addr` 修改为客户端可达的实际宿主机 IP 地址。
> * `--insecure` 为非安全开发模式（免密免 TLS 证书），生产环境请务必配置安全证书并改用 `--certs-dir` 参数。

---

## 8. 验证

* **查看运行日志**：
  ```bash
  docker logs -f crdb
  ```
* **访问管理控制台（Admin UI）**：在浏览器中打开 `http://<宿主机IP>:8080`。
* **进入本地 SQL 命令行控制台**：
  ```bash
  docker exec -it crdb /cockroach/cockroach sql --insecure
  ```

---

## 9. 常用命令汇总

| 功能说明 | 具体执行命令 |
| :--- | :--- |
| **停止数据库** | `docker stop crdb` |
| **启动已停止的数据库** | `docker start crdb` |
| **删除容器实体** | `docker rm crdb` |
| **彻底销毁数据卷** | `docker volume rm cockroach-data` *(危险操作，数据全丢)* |
| **交互式进入容器 Shell** | `docker run --rm -it cockroach:v19.1.11 shell` |