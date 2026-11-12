# 生产部署说明

编排文件：`deploy/docker-compose.prod.yml`；变量模板：`deploy/.env.prod.example`（复制为 `deploy/.env.prod`，不进 git）。

## 组成

| 服务 | 镜像 | 说明 |
|---|---|---|
| nginx | `kbp-frontend` | 前端静态资源 + 反向代理（唯一对宿主机暴露端口，`NGINX_HOST_PORT`）；不代理 `/internal/` |
| iam / kb / open | `kbp-iam` / `kbp-kb` / `kbp-open` | 容器内端口 8301 / 8302 / 8303，不映射到宿主机 |
| kb-worker | `kbp-kb` | `command: python worker.py`，文档处理与 HNSW 索引维护，无 HTTP 端口 |
| iam-migrate / kb-migrate / open-migrate | 同上 | 一次性迁移任务（iam 另跑 `python -m app.seed`），业务服务等待其成功后启动 |
| minio-init | `kbp-kb` | 一次性建桶 |
| postgres / redis / minio | pgvector/pgvector:pg16 / redis:7-alpine / minio | 数据卷 `pgdata`、`redisdata`、`miniodata`；不映射宿主机端口 |

网络为独立 bridge（默认 `172.31.77.0/24`），nginx 固定 `172.31.77.10`，`TRUSTED_PROXIES` 只包含该地址。

## 首次部署

```bash
# 1. 准备 JWT 密钥对（iam 持私钥签发，其他服务只挂载公钥）
mkdir -p /opt/kbp/secrets && cd /opt/kbp/secrets
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
# 容器内以 uid 10001 运行，文件须对其可读
chown 10001:10001 jwt_private.pem jwt_public.pem && chmod 400 jwt_private.pem && chmod 444 jwt_public.pem

# 2. 准备环境变量
cp deploy/.env.prod.example deploy/.env.prod   # 替换全部 <...> 占位符，chmod 600

# 3. 构建并启动（在仓库根目录）
docker compose -p kbp-prod --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d --build
docker compose -p kbp-prod -f deploy/docker-compose.prod.yml ps
```

启动后访问 `http://<主机>:<NGINX_HOST_PORT>/`，用 `admin` + `SEED_ADMIN_PASSWORD` 登录，首次登录强制改密。
之后在"模型配置"中添加 Embedding / Rerank / LLM 模型（kb-worker 会自动创建对应 HNSW 索引）。

## 构建镜像

```bash
docker build --build-arg SERVICE=iam  -t kbp-iam:<ver>  backend
docker build --build-arg SERVICE=kb   -t kbp-kb:<ver>   backend    # kb-worker 复用此镜像
docker build --build-arg SERVICE=open -t kbp-open:<ver> backend
docker build -t kbp-frontend:<ver> frontend
```

`.env.prod` 中 `KBP_VERSION=<ver>` 决定 compose 使用的镜像标签。镜像内不含 `.env`、`.secrets`、`tests`（见 `backend/.dockerignore`）。

## 升级与扩容

```bash
# 单服务升级（先构建新镜像并改 KBP_VERSION；有迁移时迁移任务会先于服务重跑）
docker compose -p kbp-prod --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d --build kb kb-worker
# 只重跑迁移
docker compose -p kbp-prod --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml run --rm kb-migrate
# 扩容 worker（HNSW 建索引与定时任务内部有分布式锁，多实例安全）
docker compose -p kbp-prod --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d --scale kb-worker=4
```

注意：kb / open / iam 水平扩容时 nginx 需改为指向负载均衡地址；每个 kb 实例连接池 20，扩容后同步评估 `PG_MAX_CONNECTIONS`。

## 数据库账号与 schema 授权

PostgreSQL 容器首次初始化（空数据卷）时执行 `deploy/prod/initdb/00-init-roles.sh`，为每个服务创建独立登录角色并作为其 schema 的 owner：

```sql
CREATE EXTENSION IF NOT EXISTS vector;                  -- 需超级用户；迁移中的 IF NOT EXISTS 因已存在而跳过
CREATE ROLE kbp_iam  LOGIN PASSWORD '...';
CREATE ROLE kbp_kb   LOGIN PASSWORD '...';
CREATE ROLE kbp_open LOGIN PASSWORD '...';
GRANT CONNECT, CREATE ON DATABASE kbp TO kbp_iam, kbp_kb, kbp_open;   -- 迁移环境的 CREATE SCHEMA IF NOT EXISTS 需要
CREATE SCHEMA iam  AUTHORIZATION kbp_iam;
CREATE SCHEMA kb   AUTHORIZATION kbp_kb;
CREATE SCHEMA open AUTHORIZATION kbp_open;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kbp_iam, kbp_kb, kbp_open;
```

- **kb 迁移必须以 `kbp_kb` 执行**（`kb-migrate` 已如此配置），这样 kb 表的 owner 就是 `kbp_kb`；kb-worker 使用同一账号，才能在运行时 `CREATE/DROP INDEX CONCURRENTLY` 维护 HNSW 索引（tech-design-m2 3.10.2）。不要用超级用户跑 kb 迁移。
- 对已有实例（数据卷已存在，init 脚本不再执行）：手工执行上述 SQL；若表 owner 不对：`ALTER TABLE kb.<表> OWNER TO kbp_kb`（含序列、视图）。
- 核对 owner：`SELECT tablename, tableowner FROM pg_tables WHERE schemaname='kb';`

## PostgreSQL 参数与换算

默认值对应 16 核 / 64GB 专用 DB 主机（样例文件：`deploy/prod/postgres-params.example.conf`），通过 `.env.prod` 的 `PG_*` 覆盖。按内存 `M` 换算：

| 参数 | 换算 |
|---|---|
| `PG_SHARED_BUFFERS` | M × 25% |
| `PG_EFFECTIVE_CACHE_SIZE` | M × 75% |
| `PG_MAINTENANCE_WORK_MEM` | M × 12%（HNSW 构建尽量内存内完成） |
| `PG_SHM_SIZE` | 不小于 `maintenance_work_mem`（建议与 shared_buffers 相同量级）；Docker 默认 64MB 会导致并行查询/并行建索引失败 |
| `PG_WORK_MEM` | 注意 × 并发连接 × 每查询排序节点数 |
| `PG_MAX_PARALLEL_*`、`PG_MAX_WORKER_PROCESSES` | 按 CPU 核数缩放 |
| `PG_MAX_CONNECTIONS` | 各服务连接池之和 + 余量（kb 每实例 20+10，iam/open 各 10+10，kb-worker 另计） |

## 安全基线与上线前检查清单

- [ ] 所有服务 `APP_ENV=prod`（编排已固定）；`INTERNAL_API_TOKEN` 已换成 >= 32 位随机串（默认值或过短时服务拒绝启动）
- [ ] `MODEL_SECRET_KEY`（Fernet）、`API_KEY_PEPPER`（一经设置不可更换，请备份）、数据库 / Redis / MinIO 密码均已替换，且 `.env.prod` 权限为 600、不进 git
- [ ] JWT 私钥只挂载到 iam；其余服务只有公钥；密钥文件权限正确
- [ ] `TRUSTED_PROXIES` 只含 nginx 容器地址（`NGINX_IP/32`），不含 `127.0.0.1`、`0.0.0.0/0`、宿主机网段
- [ ] `SEED_ADMIN_PASSWORD` 已改为强密码，首次登录已改密（admin 的 `must_change_password` 由 seed 置为 true）
- [ ] 除 nginx 外没有端口映射；`/internal/` 经 nginx 访问返回 404
- [ ] PostgreSQL `PG_*` 参数与主机内存匹配；`shm_size` 足够
- [ ] `kb` schema 下表的 owner 为 `kbp_kb`
- [ ] 备份：`pgdata`、`miniodata`（含上传文件）、`redisdata`（Redis Streams 未消费消息）；`API_KEY_PEPPER` 与 JWT 密钥单独备份
- [ ] 前面有负载均衡 / HTTPS 终结时：见下节

## 前置负载均衡 / HTTPS

nginx 以 `$remote_addr` **覆盖** `X-Forwarded-For`，因此在 nginx 前再加一层负载均衡时，nginx 看到的 `$remote_addr` 是 LB 地址，日志与 API 密钥 IP 白名单会失真。处理方式：

1. 在 `frontend/nginx/default.conf.template` 增加 `set_real_ip_from <LB 地址>; real_ip_header X-Forwarded-For; real_ip_recursive on;`（只信任 LB），使 `$remote_addr` 还原为真实客户端；
2. `TRUSTED_PROXIES` 仍只填 nginx 的地址（后端只信任直连对端 nginx）。

不要把 LB 地址或 `0.0.0.0/0` 直接写入 `TRUSTED_PROXIES`，也不要让 nginx 改为"追加"模式而不限制来源。

## 清理（仅限测试环境）

```bash
docker compose -p kbp-prod --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml down -v   # -v 会删除全部数据卷
```
