# 知识库平台

## 本地一键运行

前置：Docker（含 compose v2）。在仓库根目录执行：

```bash
docker compose up -d
```

首次会构建 4 个镜像（后端 iam/kb/open + 前端），约 2 分钟；之后秒级启动。启动内容：

- 中间件：`kbp-postgres`（15432）、`kbp-redis`（16379）、`kbp-minio`（19000/19001），数据在 `./.docker-data/`
- 一次性任务（退出码 0 属正常）：`init`（生成开发 JWT 密钥到 `backend/.secrets`、创建 MinIO 桶）、`iam-migrate`（迁移 + seed）、`kb-migrate`、`open-migrate`，均幂等
- 应用：`iam`、`kb`、`kb-worker`、`open`、`web`（Nginx + 前端）

访问：<http://localhost:8300>（可用环境变量 `WEB_PORT` 改端口）。账号 `admin`，初始密码 `Admin12345`，首次登录强制改密。iam/kb/open 不映射宿主机端口。

常用命令：

```bash
docker compose ps -a                       # 状态
docker compose logs -f kb-worker           # 查看日志（可换 iam / kb / open / web）
docker compose up -d --build               # 改代码后重建并重启（可指定服务，如 kb kb-worker）
docker compose stop                        # 停止（保留容器与数据）
docker compose down                        # 停止并删除容器，数据保留（不要加 -v 与删除 .docker-data）
docker compose up -d postgres redis minio  # 只起中间件，配合本机 devctl 开发
```

注意：

- 应用容器使用 `APP_ENV=dev` 与开发默认密钥（`MODEL_SECRET_KEY` 等），仅限本机。开发库中已加密的模型 API Key 依赖该默认值，不要随意更换。
- 容器版与本机 `devctl.py up` 不能同时运行（两套 kb-worker 会消费同一个 Redis Stream），devctl 检测到容器在运行会拒绝启动。切换到本机开发：`docker compose stop iam kb kb-worker open web`。
- 容器网络固定为 `172.31.78.0/24`，Nginx 固定 `172.31.78.10`，后端 `TRUSTED_PROXIES` 只信任它；若该网段与本机冲突，同步修改 `docker-compose.yml` 中的子网、`web` 的 IP 与 `TRUSTED_PROXIES`。

本机开发（不进容器）与生产部署分别见 `CLAUDE.md` 第 9 节与 `deploy/README.md`。
