# 企业级知识库管理平台 技术方案（总体）

- 关联 PRD：`./prd.md`（v0.3，F-01 ~ F-20，AC-01 ~ AC-74；Q-09 ~ Q-15 按推荐确认，TQ-06/TQ-07 已确认）
- 状态：草稿（待用户确认第 14 节"关键架构决策"与第 13 节"规范变更建议"）
- 文档组织：

| 文件 | 内容 |
|---|---|
| `tech-design.md`（本文） | 需求范围、服务拆分、跨服务约定（鉴权、通信、错误码、数据权限、事件）、中间件选型、数据模型总览、接口总览、权限总表、里程碑与任务依赖、风险、测试要点、**规范变更建议**、关键架构决策 |
| `tech-design-m1.md` | M1 平台地基：工程脚手架、共享库、IAM 服务（认证/组织/用户/角色/数据权限/日志）、前端骨架。**可直接开工** |
| `tech-design-m2.md` | M2 知识库：KB 服务 + 文档处理 Worker（模型配置、知识库、分配、上传分段、处理、检索、召回测试、管理视图） |
| `tech-design-m3.md` | M3 开放检索：Open 服务（个人 API 密钥、开放检索 API、调用日志与限流）、生产部署 |

> 约定：本文与分册冲突时，以**分册中的接口契约**为准（分册更具体）；分册之间的跨服务约定以本文为准。

---

## 1. 需求理解与范围

| 功能点 | 本次覆盖 | 里程碑 / 归属服务 | 说明 |
|---|---|---|---|
| F-01 登录认证与会话 | ✅ | M1 / iam | JWT(RS256) + 可吊销会话（Redis）+ 刷新令牌轮换 |
| F-02 组织管理 | ✅ | M1 / iam | `iam.sys_org` |
| F-03 用户管理 | ✅ | M1 / iam | 停用/删除的"影响提示"在 M2/M3 接入 kb/open 计数 |
| F-04 角色与权限 | ✅ | M1 / iam | 授权上限校验 |
| F-05 数据权限 | ✅ | M1 / 共享库 + iam | iam 计算"已解析数据范围"，各服务用共享函数生成 where |
| F-06 操作/登录日志 | ✅ | M1 / iam（存储与查询），各服务产生 | 操作日志经 Redis Stream 异步汇聚到 iam |
| F-07 模型配置 | ✅ | M2 / kb | |
| F-08 我的知识库 | ✅ | M2 / kb | |
| F-09 知识库增删改 | ✅ | M2 / kb | |
| F-10 知识库分配 | ✅ | M2 / kb | 资源级 ACL，不走 data_scope |
| F-11 上传与分段设置 | ✅ | M2 / kb | |
| F-12 文档处理任务 | ✅ | M2 / kb-worker | |
| F-13 文档管理 | ✅ | M2 / kb | |
| F-14 分段查看与编辑 | ✅ | M2 / kb + kb-worker | |
| F-15 检索设置 | ✅ | M2 / kb | |
| F-16 召回测试 | ✅ | M2 / kb | |
| F-20 管理视图与所有权转移 | ✅ | M2 / kb | |
| F-17 个人 API 密钥 | ✅ | M3 / open | |
| F-18 开放检索 API | ✅ | M3 / open → kb | |
| F-19 调用日志与限流 | ✅ | M3 / open | |
| 聊天（二期） | ❌ 预留 | chat 服务（二期） | 预留端口、路由前缀、目录、错误码段、调用 kb 内部检索接口的方式 |

## 2. 现状分析

- 仓库只有 `CLAUDE.md`、`.claude/`（5 个智能体 + 2 个流程命令）、`docs/templates/`、本需求的 `prd.md`。**`frontend/`、`backend/` 均不存在**，无迁移、无代码，本需求从零搭建。
- 本机环境（只读核查）：`python3.12` 3.12.3 ✅、`node` v24.18.0 ✅、`docker` ✅、**`pnpm` 未安装**（FE-01 前需由主会话执行 `corepack enable && corepack prepare pnpm@9 --activate`，或 `npm i -g pnpm@9`；需要用户授权安装）。
- `.gitignore` 已按单 `backend/` 编写，拆分后需要调整（见第 13 节）。
- 可复用能力：无（本需求即建设地基，M1 产出的共享库 `platform_common` 将是之后所有服务复用的基础）。

---

## 3. 整体设计

### 3.1 服务拆分

```
                        浏览器（单一前端应用 frontend/，React SPA）
                                   │  同源 /api/v1/*
              ┌────────────────────┴─────────────────────┐
   本地：Vite dev proxy          生产：Nginx（前端镜像内，静态资源 + 反向代理）
              └──────┬──────────────┬──────────────┬─────┘
       /api/v1/auth  │ /api/v1/kb   │ /api/v1/open-platform     外部业务系统
       /api/v1/system│              │ /api/v1/open  ◄──────────── (API 密钥)
                     ▼              ▼              ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐      ┌───────────┐
              │   iam    │   │    kb    │◄──│   open   │      │ chat(二期)│
              │  :8301   │   │  :8302   │   │  :8303   │      │  :8304    │
              └────┬─────┘   └────┬─────┘   └────┬─────┘      └─────┬─────┘
                   │  内部 HTTP /internal/v1（X-Internal-Token）      │
                   │              │                                 │
                   │         ┌────┴─────┐                           │
                   │         │kb-worker │（无端口，消费任务流）       │
                   │         └────┬─────┘                           │
     ┌─────────────┴──────────────┴─────────────────────────────────┴────┐
     │ PostgreSQL 16 + pgvector（库 kbp：schema iam / kb / open / chat）    │
     │ Redis 7（会话、权限上下文缓存、限流、Streams 事件与任务）             │
     │ MinIO（原始文件、解析文本）                                          │
     └───────────────────────────────────────────────────────────────────┘
```

| 服务 | 端口 | 职责 | 拥有的数据（schema） | 扩容方式 |
|---|---|---|---|---|
| `iam` 认证与权限 | 8301 | 登录/令牌/会话、组织、用户、角色、权限点与菜单、**数据范围解析**、权限上下文下发、操作日志与登录日志的汇聚与查询、用户/组织变更事件发布 | `iam` | 无状态，水平扩容 |
| `kb` 知识库 | 8302 | 模型配置、知识库、分配（资源 ACL）、上传/预览、文档与分段管理、检索设置、**检索引擎**（召回测试 + 内部检索接口）、管理视图与所有权转移 | `kb` | 无状态，水平扩容；生产可将同一镜像部署为"管理组"和"检索组"两组实例，`open`/`chat` 通过配置指向检索组，实现检索独立扩容 |
| `kb-worker` 文档处理 | — | 消费文档处理任务：解析 → 分段 → 向量化与建索引；分段重建索引；超时巡检；召回次数落库；用户/组织只读副本同步 | `kb`（与 kb 同 schema，同代码包，独立进程） | 按队列积压水平扩容；与 kb API 互不影响 |
| `open` 开放平台 | 8303 | 个人 API 密钥管理与校验、开放检索 API（鉴权、IP 白名单、限流、调用 kb 检索）、调用日志与审计 | `open` | 无状态，水平扩容 |
| `chat`（二期预留） | 8304 | 用户与模型聊天、会话管理；通过 kb 内部检索接口按用户身份检索 | `chat` | — |
| 前端 `frontend` | 5174（dev） | 单一 SPA：登录、知识库、开放平台、系统管理 | — | 静态资源，Nginx |

**拆分依据**：按"数据所有权 + 变化频率 + 负载特征"划分。

- 认证权限是所有业务的公共底座，变化少、读多，必须独立且被所有服务复用 → `iam`。
- 文档处理是 CPU/IO 重、耗时长的批处理，峰值不可预测，必须与在线请求隔离，避免上传高峰拖垮检索 → `kb-worker` 独立进程。
- 开放检索面向外部系统，有独立的鉴权方式（API 密钥）、限流和高频日志，安全边界与内部用户不同 → `open` 独立部署，可单独放在 DMZ/独立域名。
- 知识库管理与检索共享同一份数据（分段、向量、ACL），强行拆开会导致跨库强一致问题；因此**代码同服务、部署可分组**（见上表 kb 扩容方式），是"能独立扩容"和"不过度设计"的折中。
- 聊天（二期）是新的业务域，有自己的会话数据和 LLM 调用，单独成服务，只依赖 iam（鉴权）和 kb（检索）。

**明确不做**：不自研 API 网关（Nginx/Vite 路由足够）、不引入服务网格、注册中心、配置中心、分布式事务框架、Kafka/RabbitMQ。服务地址通过配置项注入（本地 localhost，生产为 compose/k8s 服务名）。

### 3.2 仓库结构（拆分后）

```
.
├── CLAUDE.md
├── .venv/                              # 唯一 Python 虚拟环境（所有后端服务共用）
├── docker-compose.yml                  # 本地中间件：PostgreSQL16+pgvector、Redis7、MinIO
├── deploy/                             # 生产部署（M3 BE-29 产出）
│   ├── docker-compose.prod.yml
│   ├── .env.prod.example
│   └── local/postgres-init.sql         # 本地初始化：建 kbp/kbp_test 库、vector 扩展
├── backend/
│   ├── requirements.txt                # 所有服务共用，版本固定
│   ├── requirements-dev.txt
│   ├── pyproject.toml                  # 仅放 ruff / mypy / pytest 配置（不是 poetry）
│   ├── Dockerfile                      # 多服务共用，构建参数 SERVICE 选择服务（M3）
│   ├── scripts/devctl.py               # 本地一键：init / migrate / up / down / status
│   ├── libs/platform_common/           # 共享库（pip install -e 安装进 .venv）
│   │   ├── pyproject.toml              # setuptools 构建，仅用于 pip 安装
│   │   └── platform_common/
│   │       ├── config.py  db.py  redis.py  errors.py  response.py  pagination.py
│   │       ├── logging.py  app_factory.py  http_client.py  client_ip.py
│   │       ├── auth/  (jwt.py  context.py  deps.py  data_scope.py  internal.py)
│   │       ├── events/ (streams.py  publisher.py  consumer.py)
│   │       └── oplog.py
│   └── services/
│       ├── iam/   main.py  alembic.ini  alembic/  app/{core,deps,models,schemas,repositories,services,api/v1,api/internal,seed,jobs}  tests/  .env.example
│       ├── kb/    main.py  worker.py  alembic.ini  alembic/  app/{...,engine,parsers,splitters,storage,model_clients,worker}  tests/  .env.example
│       ├── open/  main.py  alembic.ini  alembic/  app/{...}  tests/  .env.example
│       └── chat/  README.md            # 二期预留，仅说明
├── frontend/                           # 单一 SPA（本期）
└── docs/
```

- 每个服务内部仍严格遵守 CLAUDE.md 4.2 的分层（api → service → repository → model），只是多了 `api/internal`（内部接口）和服务特有目录。
- **服务之间禁止 import 对方代码**，只能通过 `platform_common`（通用能力）+ 内部 HTTP + Redis Streams 交互。`platform_common` **不得包含任何业务模型**。

### 3.3 数据库：一个 PostgreSQL 实例、一个库、按服务分 schema

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 一实例一库，按服务分 schema（`iam`/`kb`/`open`/`chat`） | 运维简单（一套备份、一个连接地址）；本地零成本；将来拆库只需改 DSN + 迁移数据 | 共享实例资源，需要约束防止跨 schema 访问 | **采用** |
| B. 每服务一个库（同实例） | 隔离更强 | 本地/测试要建多库；与 A 的区别主要是约束力度 | 预留升级路径 |
| C. 每服务一个实例 | 完全隔离 | 本期规模下浪费，运维成本高 | 不采用 |

硬约束（写入规范）：

1. 每个服务的 ORM 模型显式声明 `__table_args__ = {"schema": "<服务名>"}`；Alembic 的 `version_table_schema` 也设为该 schema，各服务**独立迁移链**，互不感知。
2. **禁止跨 schema 的外键、JOIN、子查询**。跨服务引用只存 ID（BIGINT，无外键），需要展示/过滤时使用"只读副本表"（见 3.7）或内部接口。
3. 生产为每个服务创建独立 DB 账号（`iam_rw`/`kb_rw`/`open_rw`），只授权自己的 schema；本地开发使用同一账号 `kbp` 以简化。
4. 测试库 `kbp_test` 结构相同，`devctl --env test` 切换。

### 3.4 中间件选型

| 需要的能力 | 选择 | 备选与对比 | 理由 |
|---|---|---|---|
| 向量检索 | **pgvector**（镜像 `pgvector/pgvector:pg16`，`halfvec` 存储） | Milvus：重（standalone 也要 etcd+MinIO），运维成本高；Qdrant：轻量、带过滤的 HNSW 很强，但需要 PG↔Qdrant 双写，分段启停、文档禁用、权限变化要同步到 payload，一致性成本高 | 本期全平台 ≤500 万分段、平均每库约 2,500 分段；"禁用后立即不可检索""删除即生效"需要与业务数据**同事务一致**，pgvector 天然满足；少一个中间件。检索层抽象 `VectorStore` 接口，后续规模上来可替换为 Qdrant |
| 向量检索算法 | **按知识库过滤的精确检索（exact KNN）**，本期不建 ANN 索引 | HNSW：多租户强过滤下（每次只查一个库）召回不稳定，且不同模型维度不同需要按模型建部分索引（运行时 DDL） | 单库 ≤10 万分段时精确扫描在数百毫秒内；100% 召回；无索引维护成本。M2 包含 10 万分段性能验证任务，不达标时启用"按模型建 HNSW 部分索引"或迁移 Qdrant（见风险） |
| 全文检索 | **PostgreSQL `tsvector`（`simple` 配置）+ 应用层 jieba 分词** | Elasticsearch + IK：中文效果最好，但 JVM 重、多一套数据同步；zhparser/pg_jieba 扩展：需自建 PG 镜像，升级维护难 | 数据与向量同表同事务；只增加一个纯 Python 依赖 `jieba`；关键词用 `setweight` 加权；规模内 GIN 索引足够 |
| 异步任务 + 服务间事件 | **Redis Streams**（消费组，至少一次投递） | Celery：同步模型为主，对 asyncio 不友好，组件重；arq：轻量但处于维护模式，且仍需另外做事件总线；RabbitMQ/Kafka：本期过重 | 已有 Redis，无新中间件、无新依赖；消费组 + `XAUTOCLAIM` 处理崩溃恢复；任务状态以 PG 为准（阶段幂等），队列只负责投递。共享库提供统一的发布/消费封装 |
| 对象存储 | **MinIO**（S3 协议，客户端 `aioboto3`；桶由 `devctl.py init` 用 boto3 幂等创建，不依赖 `minio/mc` 镜像） | 本地磁盘：多节点部署需要 NFS；PG bytea：库膨胀、备份变慢 | kb API 接收上传、kb-worker 在其他节点解析，必须共享存储；S3 协议生产可直接换云 OSS |
| 缓存/会话/限流 | Redis 7（已有） | — | — |
| 网关 | 本地 Vite proxy、生产 Nginx | 自研网关 / Kong / APISIX | 路由规则只有 4 条前缀，Nginx 足够 |

新增 Python 依赖（BE-01 安装时取当时稳定版并**固定版本号**）：

| 依赖 | 用途 | 服务 |
|---|---|---|
| `pyjwt[crypto]`、`cryptography` | RS256 JWT；模型凭据对称加密（Fernet） | 共享 |
| `bcrypt` | 密码哈希 | iam |
| `httpx` | 内部 HTTP、模型服务调用（运行时依赖，不只是测试） | 共享 |
| `python-multipart` | FastAPI 文件上传 | kb |
| `pgvector` | SQLAlchemy 向量类型 | kb |
| `aioboto3`（含 `boto3`） | MinIO/S3；`boto3` 同时供 devctl 建桶（BE-01 提前加入并固定版本） | kb、devctl |
| `jieba` | 中文分词（全文检索） | kb |
| `tiktoken` | 分段 token 计数（`cl100k_base`，编码文件随代码分发，不联网） | kb |
| `pypdf`、`python-docx`、`openpyxl`、`xlrd`、`python-pptx`、`beautifulsoup4`、`lxml`、`charset-normalizer` | 文档解析（均为 MIT/BSD 许可，**不使用 AGPL 的 PyMuPDF**） | kb |

前端：**不新增**基线外依赖（`openapi-typescript` 为 CLAUDE.md 已约定的类型生成工具，作为 devDependency）。

### 3.5 服务间鉴权

#### 3.5.1 用户请求（浏览器 → 各服务）

```
登录：iam 用私钥签发 access_token(JWT RS256, 30min, 含 sub=user_id, sid=会话ID)
      + refresh_token(不透明随机串, 哈希存 PG, 7 天滑动)
      并写 Redis：auth:sess:{sid}（TTL 7 天，刷新时续期）

任一服务收到请求（platform_common.auth.deps.get_auth_context）：
 1. 本地用公钥验 JWT 签名与 exp                       → 失败 401001
 2. Redis 一次 MGET：auth:sess:{sid}、authz:ctx:{user_id}、authz:epoch
 3. 会话 key 不存在（已登出/改密/停用/删除）            → 401002
 4. ctx 不存在或 ctx.epoch != 当前 epoch               → 调 iam 内部接口
    GET /internal/v1/authz/contexts/{user_id}（iam 计算并回写缓存）
 5. ctx.usable == false（停用/删除/组织停用）           → 401002
 6. ctx.must_change_password 且接口不在白名单          → 403002
 7. require_perm 检查权限码；repository 用 ctx.data_scope 生成 where
```

- **为什么每次查 Redis**：PRD 要求登出、改密、停用"立即失效"，纯 JWT 无法做到；一次 Redis MGET 成本极低（<1ms），换来强一致的吊销能力。
- **权限上下文 AuthContext**（JSON，缓存在 `authz:ctx:{user_id}`，TTL 10 分钟）：

```json
{
  "user_id": 12, "username": "zhangsan", "name": "张三",
  "status": "enabled", "is_deleted": false, "org_enabled": true, "usable": true,
  "org_id": 5, "company_id": 3, "org_path": [1, 3, 5],
  "is_super_admin": false, "must_change_password": false,
  "permissions": ["kb:dataset:list", "kb:dataset:create"],
  "data_scope": {"all": false, "company_ids": [3, 7], "org_ids": [5, 9], "include_self": true},
  "epoch": 17, "computed_at": "2026-11-11T10:00:00+08:00"
}
```

- `org_path`：从根到本人主组织的 ID 链（含自身），kb 用它判断"部门/公司（含下级）分配"是否覆盖本人。
- `data_scope` 是**已解析**的数据范围（多角色并集已在 iam 算好），任何服务都用同一个函数生成过滤条件（3.6）。
- **缓存失效**（由 iam 在事务提交后同步执行）：
  - 与单个用户有关的变更（改角色、调组织、停用/启用、删除、改密、强制改密标记）→ `DEL authz:ctx:{user_id}`；
  - 影响面大的变更（角色权限/数据范围/状态、自定义组织、组织移动/停用/删除、权限点变更）→ `INCR authz:epoch`，所有上下文在下一次请求时重算。此类操作频率极低，可接受。
- 由于失效是同步的，"权限变化 ≤5 秒生效"（A-24）实际为即时生效。

#### 3.5.2 服务间内部调用

- 内部接口统一挂在 `/internal/v1/*`，**不经过 Nginx 对外暴露**（Nginx 只转发 `/api/`），并要求请求头 `X-Internal-Token: <INTERNAL_API_TOKEN>`（每个环境一个随机密钥，所有服务共享配置）。校验依赖 `platform_common.auth.internal.require_internal`。
- 内部调用涉及用户身份时，**显式传 `user_id`**，被调方自行通过共享缓存取该用户的 AuthContext 并做判断，不信任调用方传来的权限结论。
- 传递 `X-Request-Id` 串联日志。
- 不做 mTLS（本期内网部署，成本收益不划算）；二期如上云多租户再评估。

#### 3.5.3 API 密钥（外部系统 → open）

- 密钥由 `open` 服务生成和保存（只存 HMAC-SHA256 哈希），校验在 `open` 本地完成：哈希查缓存/库 → 状态/过期 → 创建人 AuthContext（共享缓存，判断账号可用且仍有 `openapi:apikey:manage`）→ IP 白名单 → 限流 → 指定范围 → 调 kb 内部检索接口（传创建人 `user_id`，由 kb 按创建人**当前**分配关系判定可访问性）。详见 M3。
- 为什么 API 密钥放在 `open` 而不是 `iam`：密钥的唯一用途是开放 API，与调用日志、限流、"近 7 天调用量"统计强内聚；放在 iam 会让密钥列表需要跨服务聚合统计、热路径多一跳。人员身份与权限仍以 iam 为唯一来源（通过 AuthContext）。备选方案见第 14 节 D7。

### 3.6 数据权限的统一实现

- iam 将角色的 `data_scope` 解析为三类集合（多角色并集）：

| 角色数据范围 | 贡献 |
|---|---|
| `ALL` | `all = true` |
| `COMPANY_AND_CHILD` | `company_ids += 本人公司及其下属所有公司（含集团节点时即全部公司）` |
| `COMPANY` | `company_ids += [本人公司]`（集团本部用户的本公司 = 集团节点，只覆盖集团本部，不含子公司） |
| `DEPT_AND_CHILD` | `org_ids += [本人主组织] ∪ 其下属的全部部门（不跨入下属公司）`；本人直属公司/集团节点时 = 该节点 + 其下不经过其他公司节点的全部部门（A-05、PRD v0.3 F-05 规则 4） |
| `DEPT` | `org_ids += [本人主组织]` |
| `SELF` | `include_self = true` |
| `CUSTOM` | `org_ids += 角色勾选的组织`（不自动含下级） |

- 受控表的统一列：`company_id`（数据所属公司）、`dept_id`（**数据所属组织节点**：部门，或直属公司时为公司节点 ID）、"本人"列（一般为 `created_by`；知识库为 `owner_id`）。
- 共享函数（M1 BE-03 实现，签名为契约）：

```python
def data_scope_filter(
    ctx: AuthContext, *, company_col: ColumnElement[int] | ColumnElement[int | None],
    dept_col: ColumnElement[int] | ColumnElement[int | None],
    owner_col: ColumnElement[int] | ColumnElement[int | None],
) -> ColumnElement[bool]:
    """super_admin 或 all → true()；否则 OR(company_col = ANY(company_ids),
    dept_col = ANY(org_ids), owner_col == user_id[若 include_self])；三者皆空 → false()"""
```

- **多角色并集与权限码来源无关**（用户确认）：数据范围取用户**全部启用角色**的并集，不按"哪个角色授予了当前接口的权限码"分别计算。例如 R1 授予 `system:user:list`、数据范围 DEPT，R2 不含任何用户管理权限码、数据范围 COMPANY，则该用户在用户列表中按 DEPT ∪ COMPANY 过滤。
- **SELF 在 iam 管理页的只读特例**（用户确认，仅 iam 实现，见 M1 5.2.0a）：持有 SELF 范围的用户，在用户列表/详情中额外可见本人账号，在组织树/组织选择器中额外可见本人组织链；这些额外可见的数据只读。共享库 `data_scope_filter` 语义**不变**，其他服务、其他业务数据仍严格按 `created_by`/`owner_id`。
- 用 AC-17 样本验证：U1（A 公司研发部）CUSTOM 勾选"测试部、B 公司" → `org_ids=[测试部, B公司节点]` → K2（dept=测试部）、K4（dept=B 公司节点，因 U4 直属 B 公司）命中，K3（dept=A1 的某部门）不命中。✅

### 3.7 服务间通信与数据同步

| 场景 | 方式 | 说明 |
|---|---|---|
| 权限上下文获取 | Redis 共享缓存 + 未命中时同步 HTTP 调 iam | 安全判定只依赖它（强一致） |
| 开放检索 | open → kb 同步 HTTP（`/internal/v1/datasets/{id}/retrieve`） | httpx 长连接池，超时 10s |
| 删除组织前检查是否有知识库、停用用户前的影响提示 | iam → kb / open 同步 HTTP | 下游不可用时返回 503001（删除组织）或"统计暂不可用"（影响提示，降级） |
| 操作日志 | 各服务 → Redis Stream `stream:oplog` → iam 后台消费入库 | 写日志失败不阻塞业务（F-06） |
| 用户/组织变更 | iam → Redis Stream `stream:iam.events` → kb-worker、open 消费，更新本服务的只读副本 `user_ref`/`org_ref` | 用于**展示和筛选**（所有者姓名、"待交接"筛选、分配对象选择器、组织树筛选）；每 10 分钟按 `updated_at` 增量对账兜底 |
| 文档处理任务 | kb → Redis Stream `stream:kb.tasks` → kb-worker | 任务状态以 PG 为准 |
| 调用日志 | open → Redis Stream `stream:open.call_logs` → open 后台批量入库 | 不增加检索延迟 |

**原则**：安全判定（能不能做）只使用强一致来源（AuthContext、本服务数据库）；只读副本只用于"展示与筛选"，允许秒级延迟。

Redis Streams 约定（共享库封装）：

| Stream | 生产者 | 消费组 | 消息体 |
|---|---|---|---|
| `stream:iam.events` | iam | `kb-ref-sync`（kb-worker）、`open-ref-sync`（open） | `{"event_id","type":"user.upserted|org.upserted","occurred_at","payload":{...}}` |
| `stream:oplog` | 所有服务 | `iam-oplog`（iam） | 见 M1 5.8 |
| `stream:kb.tasks` | kb | `kb-worker` | `{"task_id","type":"document.process|segment.reindex|child.reindex|parent.regenerate","payload":{...}}` |
| `stream:open.call_logs` | open | `open-calllog` | 见 M3 |

- 所有消息含 `event_id`（UUID），消费方幂等（唯一约束或版本比较）。`MAXLEN ~ 100000` 近似裁剪。
- 消费者处理成功才 `XACK`；挂起超过 `idle_ms`（默认 10 分钟）的消息由 `XAUTOCLAIM` 转给存活消费者；失败超过 5 次写入 `stream:dead` 并记运行日志。

### 3.8 关键流程（文字时序）

1. **登录**：前端 → `POST /api/v1/auth/login`（iam）→ 校验锁定/密码/状态 → 建会话（PG + Redis）→ 签发令牌 → 写登录日志 → 前端 `GET /api/v1/auth/me` 拿用户、权限码、菜单树。
2. **访问 kb 页面**：前端带 access_token → kb → 共享库验签 + 会话 + 上下文 → `require_perm` → 资源 ACL（所有者/分配）→ 返回。
3. **上传处理**：上传文件（kb 写 MinIO）→ 预览（kb 解析 + 分段，缓存解析文本）→ 提交（kb 建 document，XADD 任务）→ kb-worker 逐阶段处理并更新 PG 状态 → 前端每 3 秒轮询。
4. **开放检索**：外部系统 → Nginx → open（密钥、IP、限流、范围）→ kb 内部检索（按创建人当前权限判定）→ 返回 → XADD 调用日志。
5. **停用员工**：iam 改状态 → 吊销全部会话、删上下文缓存 → 发布 `user.upserted` → kb/open 更新副本（"待交接"标记）；该员工的 API 密钥在下一次调用时因 AuthContext.usable=false 被拒（即时）。

### 3.9 本地开发：一键启动

```bash
# 首次
docker compose up -d                                   # PG(pgvector) :15432 + Redis :16379 + MinIO :19000/:19001
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
.venv/bin/pip install -e backend/libs/platform_common
.venv/bin/python backend/scripts/devctl.py init        # 生成本地 JWT 密钥对到 backend/.secrets/，并幂等创建 MinIO 桶 kbp-files、kbp-test
.venv/bin/python backend/scripts/devctl.py migrate     # 按 iam → kb → open 顺序 alembic upgrade head + iam seed

# 日常
.venv/bin/python backend/scripts/devctl.py up          # 前台启动 iam/kb/kb-worker/open，日志带前缀，Ctrl-C 全部停止
.venv/bin/python backend/scripts/devctl.py up -d       # 后台启动，日志写 logs/<svc>.log，PID 写 .run/<svc>.pid
.venv/bin/python backend/scripts/devctl.py up iam kb   # 只起部分服务
.venv/bin/python backend/scripts/devctl.py down        # 停止全部（按 PID 文件；兜底只匹配 cwd 位于 backend/services/ 下的本项目进程）
.venv/bin/python backend/scripts/devctl.py status
.venv/bin/python backend/scripts/devctl.py --env test migrate|up   # 使用 kbp_test 库、Redis db 1、桶 kbp-test
cd frontend && pnpm dev                                # http://localhost:5174
```

- 宿主机端口：PostgreSQL 15432、Redis 16379、MinIO 19000/19001，可用环境变量 `POSTGRES_PORT`、`REDIS_PORT`、`MINIO_API_PORT`、`MINIO_CONSOLE_PORT` 覆盖（覆盖后需同步各服务 `.env` 中的连接地址）。
- `devctl.py` 使用标准库（`asyncio.subprocess`、`signal`）+ `cryptography`（生成密钥）+ `boto3`（建桶，随 `aioboto3` 安装，在 requirements 中固定版本），**每个服务仍然是 `python main.py` 启动**（cwd = 服务目录），无热加载；修改后 `down` + `up` 重启。
- 单服务手动启动：`cd backend/services/iam && ../../../.venv/bin/python main.py`。

### 3.10 生产部署方向（M3 BE-29 / FE-22 落地）

- 后端一个 `backend/Dockerfile`，构建参数 `SERVICE=iam|kb|open` 产出各自镜像 `kbp-iam`、`kbp-kb`、`kbp-open`（只复制 `libs/` + 对应服务目录，依赖统一来自 `requirements.txt`）；`kb-worker` 复用 `kbp-kb` 镜像，命令为 `python worker.py`。每个镜像独立打标签、独立发布。
- 前端 `frontend/Dockerfile` 多阶段构建 → Nginx 镜像（静态资源 + `/api/` 反向代理，配置模板 `frontend/nginx/default.conf.template`，路由规则同 Vite proxy，不代理 `/internal/`）。
- `deploy/docker-compose.prod.yml` 编排：nginx、iam×N、kb×N、kb-worker×N、open×N、postgres、redis、minio；迁移通过一次性容器（各服务 `alembic upgrade head`，iam 另执行 `python -m app.seed`）执行。后续可平移到 k8s（每服务一个 Deployment），本期不提供 k8s 清单。
- 扩容：`docker compose up --scale kb-worker=4 --scale open=2`；单服务升级只需重建该服务镜像并滚动重启，其它服务不受影响。

---

## 4. 跨服务通用约定

### 4.1 接口约定

| 项 | 约定 |
|---|---|
| 对外前缀 | `/api/v1`；路由前缀与服务的映射：`/api/v1/auth`、`/api/v1/system` → iam；`/api/v1/kb` → kb；`/api/v1/open-platform`（管理）、`/api/v1/open`（外部检索）→ open；`/api/v1/chat` → chat（二期） |
| 内部前缀 | `/internal/v1`，仅服务间，需 `X-Internal-Token` |
| 健康检查 | 每个服务 `GET /healthz`（存活，public）、`GET /readyz`（检查 DB/Redis，public）。public 理由：供容器编排探活，不返回任何业务数据 |
| 响应 | `{"code": 0, "message": "ok", "data": ...}`；分页 `data = {"items": [], "total": n, "page": 1, "page_size": 20}` |
| HTTP 状态码 | 与错误类别一致：400 参数/业务校验、401 未认证、403 无权限、404 不存在或无权限、409 冲突、429 限流、500 内部错误、503 依赖不可用。**响应体格式始终相同** |
| 分页参数 | `page` ≥1 默认 1；`page_size` 1~100 默认 20（超出返回 400001） |
| 排序参数 | `sort_by`（各接口列出可选值）、`sort_order`=`asc|desc` |
| 命名 | JSON 字段 `snake_case`；枚举值小写蛇形（数据范围沿用 CLAUDE.md 大写：`ALL`…） |
| ID | BIGINT，JSON 中为数字 |
| 时间 | 库内 `timestamptz`；JSON 输出 ISO 8601 带时区（`2026-11-11T10:00:00+08:00`），服务时区 `Asia/Shanghai`；查询参数接受 ISO 8601 |
| 并发控制 | 可编辑实体带 `version`（INT），更新/状态变更请求必须携带，不一致返回 409001 |
| 参数校验错误 | FastAPI 422 统一转换为 HTTP 400、`code=400001`，`data={"errors":[{"field":"top_k","message":"取值范围 1~20"}]}` |
| 请求追踪 | 每个请求生成/透传 `X-Request-Id`，响应头返回，日志携带 |
| 客户端 IP | 取 `X-Forwarded-For` 中最靠近可信代理的地址（`TRUSTED_PROXIES` 配置），共享函数 `get_client_ip` |

### 4.2 错误码

格式：`code = HTTP 状态码 × 1000 + 序号`。序号段：`000~099` 通用、`100~299` iam、`300~599` kb、`600~799` open、`800~899` chat（二期）。

通用错误码（共享库定义，所有服务一致）：

| code | HTTP | 含义 / message | 前端处理 |
|---|---|---|---|
| 0 | 200 | ok | — |
| 400001 | 400 | 参数不合法（`data.errors` 给出字段） | 表单字段提示 |
| 401001 | 401 | 未登录或登录已过期 | 尝试刷新令牌，失败跳登录页 |
| 401002 | 401 | 会话已失效，请重新登录 | 直接跳登录页（带 redirect） |
| 403001 | 403 | 无权限执行该操作 | 提示 |
| 403002 | 403 | 请先修改密码 | 跳 `/change-password` |
| 404000 | 404 | 无权限或数据不存在 | 提示 / 404 状态 |
| 409001 | 409 | 数据已被他人修改，请刷新后重试 | 提示并刷新 |
| 429001 | 429 | 请求过于频繁 | 提示 |
| 500000 | 500 | 系统繁忙，请稍后重试 | 提示（不暴露堆栈） |
| 503001 | 503 | 依赖服务暂不可用，请稍后重试 | 提示 |
| 401901 | 401 | 内部调用凭据无效（仅内部接口） | — |

服务专属错误码见各分册。

### 4.3 数据库基类约定

所有表：`id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`，`created_at timestamptz NOT NULL DEFAULT now()`，`updated_at timestamptz NOT NULL DEFAULT now()`，`created_by BIGINT NOT NULL DEFAULT 0`（0 = 系统），`updated_by BIGINT NOT NULL DEFAULT 0`，`is_deleted BOOLEAN NOT NULL DEFAULT false`。

- 共享库提供 `Base`、`AuditMixin`（以上字段）、`VersionMixin`（`version INT NOT NULL DEFAULT 1`）。
- 业务表逻辑删除；**纯关联表**（如 `sys_user_role`、`sys_role_permission`、`sys_role_org`、`api_key_dataset`）为便于唯一约束采用物理删除，仍继承基类字段，变更由操作日志留痕。
- 唯一约束在逻辑删除表上一律使用 `WHERE is_deleted = false` 的部分唯一索引（PRD 明确"已删除也不能复用"的除外，如账号）。
- 跨服务引用列只存 ID，不建外键；同 schema 内可建外键（本期为了逻辑删除简单，同 schema 也不建外键，由 service 层保证）。

### 4.4 操作日志（各服务共用）

- 共享库 `platform_common.oplog`：`async def emit_oplog(event: OpLogEvent) -> None`，内部 XADD `stream:oplog`，**任何异常只记运行日志，不抛出**。
- 推荐用法 `async with oplog_scope(ctx, module=..., action=..., target=...) as op: ...; op.summary = {...}`：正常结束记 `success`，抛出 `BizError` 记 `failure`（含 message）后继续抛出。
- 摘要中禁止出现密码、API 密钥明文、模型凭据；共享库提供 `mask_sensitive(dict)`，对 `password`、`api_key`、`secret`、`token` 等键统一替换为 `"******"`。
- 模块与操作类型枚举见 M1 5.8（各服务新增枚举时在对应分册登记）。

---

## 5. 数据模型总览

| schema.表 | 服务 | 受数据权限控制 | 本人列 | 说明 | 详见 |
|---|---|---|---|---|---|
| `iam.sys_org` | iam | **是** | created_by | 组织树；`dept_id = id`，`company_id = 所属公司（公司/集团节点为自身）` | M1 4.1 |
| `iam.sys_user` | iam | **是** | created_by | `dept_id = org_id` | M1 4.2 |
| `iam.sys_role` | iam | 否（自定义可见规则：集团级全员可见、公司级按所属公司） | — | | M1 4.3 |
| `iam.sys_role_org` | iam | 否 | — | CUSTOM 组织 | M1 4.4 |
| `iam.sys_permission` | iam | 否 | — | 权限点/菜单（系统预置） | M1 4.5 |
| `iam.sys_role_permission` | iam | 否 | — | | M1 4.6 |
| `iam.sys_user_role` | iam | 否 | — | 预留 `org_id` | M1 4.7 |
| `iam.sys_user_session` | iam | 否 | — | 刷新令牌 / 会话 | M1 4.8 |
| `iam.sys_login_log` | iam | **是** | created_by(=user_id) | | M1 4.9 |
| `iam.sys_operation_log` | iam | **是** | created_by(=operator_id) | 各服务汇聚 | M1 4.10 |
| `kb.ai_model` | kb | 否（全局资源） | — | 模型配置 | M2 |
| `kb.dataset` | kb | **是**（仅管理视图/管理员转移）；日常访问按资源 ACL | owner_id | | M2 |
| `kb.dataset_assignment` | kb | 否（随知识库） | — | 分配 | M2 |
| `kb.upload_file` | kb | 否 | — | 上传暂存 | M2 |
| `kb.document` | kb | 否（随知识库） | — | | M2 |
| `kb.segment` | kb | 否（随知识库） | — | 通用分段 / 父块；含向量与全文索引列 | M2 |
| `kb.child_chunk` | kb | 否（随知识库） | — | 子块；含向量与全文索引列 | M2 |
| `kb.retrieval_record` | kb | 否（仅本人可见） | — | 召回测试记录 | M2 |
| `kb.user_ref` / `kb.org_ref` | kb | 否 | — | iam 只读副本 | M2 |
| `open.api_key` | open | **是**（仅审计）；本人管理按 created_by | created_by | | M3 |
| `open.api_key_dataset` | open | 否 | — | 指定范围 | M3 |
| `open.api_call_log` | open | **是** | created_by(=密钥创建人) | 无法识别密钥的记录 company_id 为空，仅数据范围 ALL 可见 | M3 |
| `open.user_ref` | open | 否 | — | iam 只读副本 | M3 |

迁移：每个服务独立 Alembic 链，首个迁移负责 `CREATE SCHEMA IF NOT EXISTS <schema>`（kb 另外 `CREATE EXTENSION IF NOT EXISTS vector`）。本需求为全新建设，无存量数据迁移；回滚 = `alembic downgrade base`（删除 schema 内对象），见第 10 节。

## 6. 接口总览

> 完整契约（参数、响应、错误码）见分册。权限码列中 "login" 表示仅需登录、无需权限码；"public" 已说明理由。

### 6.1 iam（M1）

| METHOD PATH | 权限码 | 数据范围 |
|---|---|---|
| POST /api/v1/auth/login | public（登录入口） | — |
| POST /api/v1/auth/refresh | public（凭刷新令牌） | — |
| POST /api/v1/auth/logout | login | — |
| GET /api/v1/auth/me | login（改密前也可调用） | — |
| PUT /api/v1/auth/password | login（改密前也可调用） | — |
| GET /api/v1/system/orgs/tree | system:org:list | 过滤 |
| GET /api/v1/system/orgs/options | 任一：system:org:list / system:user:list / system:role:list / system:oplog:list / system:loginlog:list / kb:admin:list / openapi:apikey:audit | 过滤 |
| GET /api/v1/system/orgs/{id} | system:org:list | 过滤 |
| POST /api/v1/system/orgs | system:org:create | 上级须在范围内 |
| PUT /api/v1/system/orgs/{id} | system:org:update | 过滤 |
| PUT /api/v1/system/orgs/{id}/move | system:org:update | 过滤 |
| PUT /api/v1/system/orgs/{id}/status | system:org:update | 过滤 |
| DELETE /api/v1/system/orgs/{id} | system:org:delete | 过滤 |
| GET /api/v1/system/users | system:user:list | 过滤 |
| GET /api/v1/system/users/{id} | system:user:list | 过滤 |
| POST /api/v1/system/users | system:user:create | 目标组织须在范围内 |
| PUT /api/v1/system/users/{id} | system:user:update | 过滤 |
| PUT /api/v1/system/users/{id}/status | system:user:status | 过滤 |
| POST /api/v1/system/users/{id}/reset-password | system:user:reset_pwd | 过滤 |
| PUT /api/v1/system/users/{id}/roles | system:user:assign | 过滤 |
| DELETE /api/v1/system/users/{id} | system:user:delete | 过滤 |
| GET /api/v1/system/users/{id}/impact | system:user:list | 过滤 |
| GET /api/v1/system/roles | system:role:list | 角色可见规则 |
| GET /api/v1/system/roles/assignable | 任一：system:user:assign（`user_id` 场景）/ system:user:create（`org_id` 场景） | 角色可见规则 + 授权上限 |
| GET /api/v1/system/roles/{id} | system:role:list | 角色可见规则 |
| POST /api/v1/system/roles | system:role:create | 角色可见规则 |
| PUT /api/v1/system/roles/{id} | system:role:update | 角色可见规则 |
| PUT /api/v1/system/roles/{id}/grants | system:role:grant | 角色可见规则 + 授权上限 |
| DELETE /api/v1/system/roles/{id} | system:role:delete | 角色可见规则 |
| GET /api/v1/system/roles/{id}/users | system:role:list | 用户按范围过滤 |
| GET /api/v1/system/permissions/tree | system:role:list | — |
| GET /api/v1/system/operation-logs | system:oplog:list | 过滤 |
| GET /api/v1/system/operation-logs/{id} | system:oplog:list | 过滤 |
| GET /api/v1/system/login-logs | system:loginlog:list | 过滤 |
| GET /internal/v1/authz/contexts/{user_id} | internal | — |
| POST /internal/v1/authz/contexts/batch | internal | — |
| GET /internal/v1/sync/users | internal | — |
| GET /internal/v1/sync/orgs | internal | — |

### 6.2 kb（M2）

| METHOD PATH | 权限码 | 数据范围 / 资源 ACL |
|---|---|---|
| GET /api/v1/kb/models | system:model:list | — |
| POST /api/v1/kb/models | system:model:create | — |
| PUT /api/v1/kb/models/{id} | system:model:update | — |
| PUT /api/v1/kb/models/{id}/status | system:model:update | — |
| PUT /api/v1/kb/models/{id}/default | system:model:update | — |
| DELETE /api/v1/kb/models/{id} | system:model:delete | — |
| POST /api/v1/kb/models/test | 任一：system:model:create / system:model:update | — |
| GET /api/v1/kb/models/options | 任一：kb:dataset:list / kb:dataset:create | — |
| GET /api/v1/kb/datasets | kb:dataset:list | ACL：所有者+被分配 |
| GET /api/v1/kb/datasets/options | 任一：kb:dataset:list / openapi:apikey:manage | ACL |
| POST /api/v1/kb/datasets | kb:dataset:create | — |
| GET /api/v1/kb/datasets/{id} | kb:dataset:list | ACL 只读 |
| PUT /api/v1/kb/datasets/{id} | kb:dataset:update | ACL 可编辑（改模型须所有者） |
| PUT /api/v1/kb/datasets/{id}/retrieval-config | kb:dataset:update | ACL 可编辑 |
| DELETE /api/v1/kb/datasets/{id} | kb:dataset:delete | 所有者 |
| POST /api/v1/kb/datasets/{id}/transfer | kb:dataset:transfer | 所有者 |
| GET /api/v1/kb/datasets/{id}/assignments | kb:dataset:list | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/assignments | kb:dataset:assign | 所有者 |
| PUT /api/v1/kb/datasets/{id}/assignments/{assignment_id} | kb:dataset:assign | 所有者 |
| DELETE /api/v1/kb/datasets/{id}/assignments/{assignment_id} | kb:dataset:assign | 所有者 |
| GET /api/v1/kb/datasets/{id}/assignable-orgs | 任一：kb:dataset:assign / kb:dataset:transfer | 所有者 |
| GET /api/v1/kb/datasets/{id}/assignable-users | 任一：kb:dataset:assign / kb:dataset:transfer | 所有者 |
| POST /api/v1/kb/datasets/{id}/upload-files | kb:document:upload | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/documents/preview | kb:document:upload | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/documents | kb:document:upload | ACL 可编辑 |
| GET /api/v1/kb/datasets/{id}/documents | kb:dataset:list | ACL 只读 |
| GET /api/v1/kb/datasets/{id}/documents/progress | kb:dataset:list | ACL 只读 |
| GET /api/v1/kb/datasets/{id}/documents/{document_id} | kb:dataset:list | ACL 只读 |
| PUT /api/v1/kb/datasets/{id}/documents/enabled | kb:document:update | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/documents/batch-delete | kb:document:delete | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/documents/{document_id}/reprocess | kb:document:update | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/documents/{document_id}/retry | kb:document:update | ACL 可编辑 |
| GET /api/v1/kb/datasets/{id}/documents/{document_id}/download | kb:document:download | ACL 只读（不含管理视图） |
| GET /api/v1/kb/datasets/{id}/documents/{document_id}/segments | kb:dataset:list | ACL 只读 |
| POST /api/v1/kb/datasets/{id}/documents/{document_id}/segments | kb:segment:update | ACL 可编辑 |
| PUT /api/v1/kb/datasets/{id}/segments/{segment_id} | kb:segment:update | ACL 可编辑 |
| PUT /api/v1/kb/datasets/{id}/segments/{segment_id}/enabled | kb:segment:update | ACL 可编辑 |
| DELETE /api/v1/kb/datasets/{id}/segments/{segment_id} | kb:segment:update | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/segments/{segment_id}/children | kb:segment:update | ACL 可编辑 |
| PUT /api/v1/kb/datasets/{id}/child-chunks/{child_id} | kb:segment:update | ACL 可编辑 |
| DELETE /api/v1/kb/datasets/{id}/child-chunks/{child_id} | kb:segment:update | ACL 可编辑 |
| POST /api/v1/kb/datasets/{id}/retrieve-test | kb:retrieval:test | ACL 只读 |
| GET /api/v1/kb/datasets/{id}/retrieve-records | kb:retrieval:test | ACL 只读，仅本人记录 |
| GET /api/v1/kb/admin/datasets | kb:admin:list | 过滤 |
| GET /api/v1/kb/admin/datasets/{id} | kb:admin:view | 过滤 |
| GET /api/v1/kb/admin/datasets/{id}/documents | kb:admin:view | 过滤 |
| GET /api/v1/kb/admin/datasets/{id}/documents/{document_id} | kb:admin:view | 过滤 |
| GET /api/v1/kb/admin/datasets/{id}/documents/{document_id}/segments | kb:admin:view | 过滤 |
| POST /api/v1/kb/admin/datasets/{id}/transfer | kb:admin:transfer | 过滤（知识库与接收人） |
| POST /api/v1/kb/admin/datasets/batch-transfer | kb:admin:transfer | 过滤 |
| GET /api/v1/kb/admin/receivers | kb:admin:transfer | 过滤（用户副本） |
| GET /api/v1/kb/admin/owners | kb:admin:transfer | 过滤 |
| POST /internal/v1/datasets/{id}/retrieve | internal | 按 user_id 资源 ACL |
| POST /internal/v1/access/accessible-datasets | internal | 按 user_id 资源 ACL |
| POST /internal/v1/datasets/brief | internal | — |
| GET /internal/v1/stats/datasets | internal | — |

### 6.3 open（M3）

| METHOD PATH | 权限码 | 数据范围 |
|---|---|---|
| GET /api/v1/open-platform/api-keys | openapi:apikey:manage | 仅本人 |
| POST /api/v1/open-platform/api-keys | openapi:apikey:manage | — |
| GET /api/v1/open-platform/api-keys/{id} | openapi:apikey:manage | 仅本人 |
| PUT /api/v1/open-platform/api-keys/{id} | openapi:apikey:manage | 仅本人 |
| PUT /api/v1/open-platform/api-keys/{id}/status | openapi:apikey:manage | 仅本人 |
| POST /api/v1/open-platform/api-keys/{id}/regenerate | openapi:apikey:manage | 仅本人 |
| DELETE /api/v1/open-platform/api-keys/{id} | openapi:apikey:manage | 仅本人 |
| GET /api/v1/open-platform/api-keys/{id}/accessible-datasets | openapi:apikey:manage | 仅本人 |
| GET /api/v1/open-platform/call-logs | openapi:log:list | 仅本人密钥 |
| GET /api/v1/open-platform/audit/api-keys | openapi:apikey:audit | 过滤 |
| PUT /api/v1/open-platform/audit/api-keys/{id}/disable | openapi:apikey:audit | 过滤 |
| DELETE /api/v1/open-platform/audit/api-keys/{id} | openapi:apikey:audit | 过滤 |
| GET /api/v1/open-platform/audit/call-logs | openapi:apikey:audit | 过滤（无法识别密钥的记录仅 ALL） |
| GET /api/v1/open-platform/audit/capabilities | openapi:apikey:audit | 不过滤（仅返回当前用户能力标记 `can_view_unknown_calls`） |
| POST /api/v1/open/datasets/{dataset_id}/retrieve | public（API 密钥鉴权，外部系统不登录） | 按密钥创建人资源 ACL |
| GET /internal/v1/stats/api-keys | internal | — |

---

## 7. 权限设计（总表）

- 本期权限点类型只使用 `menu` 与 `button`：**接口权限复用菜单/按钮权限码**（菜单码保护该页的查询接口，按钮码保护写接口），避免三份码同步维护；`api` 类型保留给将来"仅接口、无界面"的能力。
- 知识库"所有者/可编辑/只读"是资源级授权，不用权限码表达；接口同时校验"功能权限码 + 资源 ACL"（F-10 规则 4）。
- 权限点以 iam 的**权限注册表**（`backend/services/iam/app/seed/permission_registry.py`）为唯一来源，由 `python -m app.seed` 幂等写入（按 `code` upsert）。新服务/新模块增加权限点时只改此文件。
- 默认授权只在**权限点首次插入时**写入内置角色，不覆盖管理员之后对内置角色的调整。

| 权限码 | 类型 | 名称 | 父级 / 路由 path | 图标（icon） | 超管 | 集团管理员 | 公司管理员 | 普通员工 |
|---|---|---|---|---|---|---|---|---|
| `kb:dataset:list` | menu | 知识库 | 根 / `/kb/datasets` | `DatabaseOutlined` | ✅ | ✅ | ✅ | ✅ |
| `kb:dataset:create` | button | 新建知识库 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:dataset:update` | button | 编辑知识库设置/检索设置 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:dataset:delete` | button | 删除知识库 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:dataset:assign` | button | 管理分配 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:dataset:transfer` | button | 转移自己的知识库 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:document:upload` | button | 上传文档 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:document:update` | button | 文档启停/重新分段/重试 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:document:delete` | button | 删除文档 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:document:download` | button | 下载原文件 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:segment:update` | button | 分段编辑/新增/启停/删除 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `kb:retrieval:test` | button | 召回测试 | kb:dataset:list | — | ✅ | ✅ | ✅ | ✅ |
| `openapi:menu:root` | menu | 开放平台（目录） | 根 / `/openapi` | `ApiOutlined` | ✅ | ✅ | ✅ | ✅ |
| `openapi:apikey:manage` | menu | 我的 API 密钥 | openapi:menu:root / `/openapi/keys` | `KeyOutlined` | ✅ | ✅ | ✅ | ✅ |
| `openapi:log:list` | menu | 调用日志 | openapi:menu:root / `/openapi/logs` | `FileTextOutlined` | ✅ | ✅ | ✅ | ✅ |
| `openapi:doc:view` | menu | API 文档 | openapi:menu:root / `/openapi/docs` | `ReadOutlined` | ✅ | ✅ | ✅ | ✅ |
| `system:menu:root` | menu | 系统管理（目录） | 根 / `/system` | `SettingOutlined` | ✅ | ✅ | ✅ | |
| `system:org:list` | menu | 组织管理 | system:menu:root / `/system/orgs` | `ApartmentOutlined` | ✅ | ✅ | ✅ | |
| `system:org:create` | button | 新增组织 | system:org:list | — | ✅ | ✅ | ✅ | |
| `system:org:update` | button | 编辑/移动/停用组织 | system:org:list | — | ✅ | ✅ | ✅ | |
| `system:org:delete` | button | 删除组织 | system:org:list | — | ✅ | ✅ | ✅ | |
| `system:user:list` | menu | 用户管理 | system:menu:root / `/system/users` | `UserOutlined` | ✅ | ✅ | ✅ | |
| `system:user:create` | button | 新增用户 | system:user:list | — | ✅ | ✅ | ✅ | |
| `system:user:update` | button | 编辑用户 | system:user:list | — | ✅ | ✅ | ✅ | |
| `system:user:status` | button | 停用/启用用户 | system:user:list | — | ✅ | ✅ | ✅ | |
| `system:user:reset_pwd` | button | 重置密码 | system:user:list | — | ✅ | ✅ | ✅ | |
| `system:user:assign` | button | 分配角色 | system:user:list | — | ✅ | ✅ | ✅ | |
| `system:user:delete` | button | 删除用户 | system:user:list | — | ✅ | ✅ | ✅ | |
| `system:role:list` | menu | 角色管理 | system:menu:root / `/system/roles` | `TeamOutlined` | ✅ | ✅ | ✅ | |
| `system:role:create` | button | 新增角色 | system:role:list | — | ✅ | ✅ | ✅ | |
| `system:role:update` | button | 编辑/停用角色 | system:role:list | — | ✅ | ✅ | ✅ | |
| `system:role:grant` | button | 分配权限与数据范围 | system:role:list | — | ✅ | ✅ | ✅ | |
| `system:role:delete` | button | 删除角色 | system:role:list | — | ✅ | ✅ | ✅ | |
| `kb:admin:list` | menu | 知识库管理 | system:menu:root / `/system/datasets` | `AppstoreOutlined` | ✅ | ✅ | ✅ | |
| `kb:admin:view` | button | 审计查看内容 | kb:admin:list | — | ✅ | ✅ | ✅ | |
| `kb:admin:transfer` | button | 转移所有权（管理员） | kb:admin:list | — | ✅ | ✅ | ✅ | |
| `openapi:apikey:audit` | menu | API 密钥审计（含停用/删除/看日志） | system:menu:root / `/system/api-keys` | `AuditOutlined` | ✅ | ✅ | ✅ | |
| `system:model:list` | menu | 模型配置 | system:menu:root / `/system/models` | `CloudServerOutlined` | ✅ | ✅ | | |
| `system:model:create` | button | 新增模型 | system:model:list | — | ✅ | ✅ | | |
| `system:model:update` | button | 编辑/启停/设默认 | system:model:list | — | ✅ | ✅ | | |
| `system:model:delete` | button | 删除模型 | system:model:list | — | ✅ | ✅ | | |
| `system:log:root` | menu | 日志（目录） | system:menu:root / `/system/logs` | `FileSearchOutlined` | ✅ | ✅ | ✅ | |
| `system:oplog:list` | menu | 操作日志 | system:log:root / `/system/logs/operation` | `HistoryOutlined` | ✅ | ✅ | ✅ | |
| `system:loginlog:list` | menu | 登录日志 | system:log:root / `/system/logs/login` | `LoginOutlined` | ✅ | ✅ | ✅ | |

- 图标：`menu` 类型权限点必须配置 `icon`，取值**只能**来自前端白名单（`frontend/src/components/menuIcons.tsx` 的 `MENU_ICON_NAMES`：ApartmentOutlined、ApiOutlined、AppstoreOutlined、AuditOutlined、CloudServerOutlined、DatabaseOutlined、FileSearchOutlined、FileTextOutlined、HistoryOutlined、KeyOutlined、LoginOutlined、ProfileOutlined、ReadOutlined、SafetyOutlined、SettingOutlined、TeamOutlined、UserOutlined）；`button` 类型 `icon` 为空。新增图标需前后端同时登记（契约变更）。权限注册表（`permission_registry.py`）每个条目字段：`code`、`name`、`perm_type`、`parent_code`、`path`、`icon`、`sort_order`、`service`、`default_roles`。
- 菜单排序 `sort_order`（同级升序）：根级 知识库 1、开放平台 2、系统管理 9；开放平台下 我的 API 密钥 1、调用日志 2、API 文档 3；系统管理下 组织管理 1、用户管理 2、角色管理 3、知识库管理 4、API 密钥审计 5、模型配置 6、日志 7；日志下 操作日志 1、登录日志 2；按钮按表中顺序。

- 内置角色（M1 seed 创建，`is_builtin=true` 不可删除）：`super_admin`（集团级，数据范围不受限，跳过所有校验，权限不可调整）、`group_admin`（集团级，ALL）、`company_admin`（集团级，COMPANY_AND_CHILD，**不含模型配置**）、`employee`（集团级，SELF）。
- 子公司管理员边界：能管理本公司及下属的组织/用户/公司级角色；能把**自己拥有的**权限授予他人；不能创建 ALL 数据范围的角色；看不到模型配置（无权限码）；管理视图/审计/日志按其数据范围过滤。
- `super_admin` 角色只能由超级管理员分配（授权上限校验天然保证：其他人"不拥有 super_admin 身份"）。

## 8. 里程碑与任务总览

| 里程碑 | 后端任务 | 前端任务 | 交付物 |
|---|---|---|---|
| M1 平台地基 | BE-01 ~ BE-10（工程、共享库、iam） | FE-01 ~ FE-08（骨架、登录、布局、系统管理、日志） | 可登录、可管理组织/用户/角色、数据权限生效、日志可查 |
| M2 知识库 | BE-11 ~ BE-23（kb、kb-worker） | FE-09 ~ FE-17 | 建库、上传、分段、处理、检索、分配、管理视图 |
| M3 开放检索 | BE-24 ~ BE-29（open、部署） | FE-18 ~ FE-22 | API 密钥、开放检索、调用日志、生产镜像 |

### 8.1 任务依赖（跨里程碑）

```
BE-01 工程脚手架 ──► BE-02 共享库(基础) ──► BE-03 共享库(鉴权/事件/日志)
                                              │
                         ┌────────────────────┼──────────────────────────┐
                         ▼                    ▼                          ▼
                BE-04 iam 模型+迁移+seed   BE-11 kb 脚手架(M2)        BE-24 open 脚手架(M3)
                         │
     ┌──────────┬────────┼────────┬──────────┐
     ▼          ▼        ▼        ▼          ▼
   BE-05      BE-06    BE-07    BE-08      BE-09 ... BE-10
   (认证)   (上下文)  (组织)   (用户)     (角色)     (日志)

FE-01 前端骨架 ──► FE-02 请求/权限基础 ──► FE-03 登录 / FE-04 布局 ──► FE-05~FE-08（对契约并行）
```

- **前端与后端对契约并行**：FE-01、FE-02 可与 BE-01~BE-03 同时开始；FE-03~FE-08 只依赖本方案契约，可与对应 BE 并行开发，联调在对应 BE 完成后进行。
- M2 可在 M1 的 BE-01~BE-06 完成（共享库 + 认证 + 上下文可用）后启动后端；M2 的验收依赖 M1 全部完成。
- M3 依赖 M2 的 BE-22（kb 内部检索接口）才能联调开放检索；M3 的密钥管理部分（BE-25/26）可与 M2 后半程并行。
- 详细的任务内依赖见各分册第 9 节。

## 9. 自检（总表）

| F-xx | 后端任务 | 前端任务 |
|---|---|---|
| F-01 | BE-05、BE-06、BE-03 | FE-02、FE-03 |
| F-02 | BE-07 | FE-05 |
| F-03 | BE-08 | FE-06 |
| F-04 | BE-09、BE-04 | FE-07、FE-04 |
| F-05 | BE-03、BE-06、BE-07~BE-10、BE-23、BE-26 | FE-07、FE-17、FE-20 |
| F-06 | BE-10、BE-03 | FE-08 |
| F-07 | BE-13 | FE-09 |
| F-08 | BE-14 | FE-10 |
| F-09 | BE-14 | FE-10、FE-15 |
| F-10 | BE-15 | FE-16 |
| F-11 | BE-16、BE-17 | FE-12 |
| F-12 | BE-18 | FE-11、FE-12 |
| F-13 | BE-19 | FE-11 |
| F-14 | BE-20 | FE-13 |
| F-15 | BE-14、BE-21 | FE-15 |
| F-16 | BE-21 | FE-14 |
| F-17 | BE-25、BE-26 | FE-18、FE-20 |
| F-18 | BE-27、BE-22 | FE-21 |
| F-19 | BE-27、BE-28 | FE-19、FE-20 |
| F-20 | BE-23 | FE-15、FE-17 |

- [x] 每个 F-xx 至少一个 BE/FE 任务
- [x] 每个接口有权限码或 public/internal 说明与数据范围说明
- [x] 前端页面使用的接口都在分册契约中定义
- [x] 受控表均含 company_id / dept_id / created_by（kb.dataset 另有 owner_id 作为"本人"列）
- [x] 新增依赖与中间件已说明理由（3.4）
- [x] 全新建设无破坏性数据变更；docker-compose 镜像变更与回滚见第 10 节

## 10. 风险与兼容性

| 风险 | 影响 | 应对 |
|---|---|---|
| 大库检索延迟（BE-21 实测通用 10 万分段 P95 向量 674 / 全文 1043 / 混合 1418ms） | F-16/F-18 | 已决定按 M2 3.10 优化（BE-21b）：大库走按模型 HNSW 部分索引、小库精确；PG 参数调优；全文按常见词裁剪候选；混合并行。HNSW 召回率以门槛约束；仍不达标再评估 Qdrant（`VectorStore` 抽象已预留） |
| 满量级（500 万单元）时 HNSW 索引约 12GB 需常驻内存 | 检索延迟 | DB 主机内存建议 ≥ 64GB；本期规模 16GB 足够（M2 3.10.3） |
| jieba 分词与用户期望不一致（专有名词） | 全文检索召回 | 支持加载自定义词典（配置项 `JIEBA_USER_DICT`）；人工关键词加权 |
| token 计数用 `cl100k_base` 估算，与具体 Embedding 模型的分词器不同 | 分段长度与模型实际上限有偏差 | 按 PRD 以模型 `max_input_tokens` 为上限校验；模型服务因超长报错时，失败原因为"向量模型调用失败"并附模型返回信息，用户调小分段长度后重试 |
| Rerank 无 OpenAI 官方协议 | 兼容性 | 采用业界通用的 Jina/Cohere 兼容 `/rerank` 格式（Xinference、vLLM、TEI 适配层、硅基流动等均支持），见 M2 |
| Redis 不可用 | 所有登录态请求失败（fail-closed） | 生产 Redis 主从 + 哨兵（部署层面）；共享库返回 503001 而非放行 |
| iam 不可用 | 缓存未命中的请求失败；已缓存上下文的请求继续可用 | iam 多实例；上下文 TTL 10 分钟 |
| 事件丢失导致只读副本过期 | 展示/筛选不准（不影响安全判定） | 每 10 分钟增量对账 |
| 多服务带来的开发协作复杂度 | 开发智能体路径混乱 | 第 13 节规范变更；任务均写明服务和文件路径 |
| 本地 PG 镜像由 `postgres:16` 改为 `pgvector/pgvector:pg16` | 首个需求，无存量数据 | 回滚：compose 改回镜像即可（会失去 kb schema 的向量列能力） |

回滚方案：各服务 Alembic 均可 `downgrade base`；服务独立镜像版本可单独回退；M2/M3 的 schema 与 iam 互不依赖，回退 kb/open 不影响登录与系统管理。

## 11. 测试要点（总体）

- **越权（重点）**：无权限码调用每个写接口 → 403001；跨公司/跨部门/仅本人的直接 ID 访问 → 404000 且数据无变化；子公司管理员授予超出自身的权限/数据范围 → 403；公司级角色跨公司分配 → 拒绝。
- **7 种数据范围 + 多角色并集**：用 AC-17/AC-18 样本在用户、组织、知识库管理视图、API 密钥审计、调用日志、操作日志、登录日志上分别验证。
- **资源 ACL 与数据范围分离**：管理员在管理视图可见 ≠ 我的知识库可见 ≠ API 可检索（AC-26、AC-67、AC-73）。
- **会话即时失效**：登出、改密、重置、停用、删除后旧 access_token 立即 401002（跨 iam/kb/open 三个服务都要验）。
- **权限变更即时生效**：角色权限变更后，三个服务下一次请求即生效（epoch 机制）。
- **服务故障**：停掉 kb 时 iam 的登录/用户管理正常、删除组织返回 503001；停掉 kb-worker 时上传可提交、文档停留排队，恢复后继续处理；停掉 Redis 时请求返回 503001 而不是放行。
- **重复投递**：同一任务消息投递两次，文档分段不重复。
- 分册第 11 节有各里程碑的具体测试点。

## 12. 变更记录

| 日期 | 变更内容 | 原因 | 影响任务 |
|---|---|---|---|
| 2026-11-11 | 初稿：总体架构、服务拆分、跨服务约定、M1/M2/M3 分册 | 新需求 | 全部 |
| 2026-11-11 | 端口改为专属：iam 8301 / kb 8302 / open 8303 / chat 8304；宿主机 PostgreSQL 15432、Redis 16379、MinIO 19000/19001；前端 dev 5174（3.1、3.9、第 13 节同步） | 用户确认：本机多项目共用 | BE-01、BE-02（配置默认值）、BE-04、BE-11、BE-24、BE-29、FE-01、FE-22 |
| 2026-11-11 | 去掉 `minio/mc` 建桶容器，改由 `devctl.py init` 用 boto3 幂等建桶；`aioboto3` 提前到 M1 加入；MinIO healthcheck 用 curl；宿主端口可用环境变量覆盖（3.4、3.9） | 本机无法拉取 `minio/mc` 镜像（BE-01 反馈） | BE-01、BE-11 |
| 2026-11-11 | 第 7 节权限总表增加"图标"列（取自前端白名单），补充菜单排序与注册表字段 | FE-04/05 反馈 | BE-04（seed）、FE-04 |
| 2026-11-11 | `GET /system/roles/assignable` 支持 `org_id`（与 `user_id` 二选一） | FE-06 反馈：新建用户场景无 user_id | BE-08、BE-09、FE-06 |
| 2026-11-11 | 新增 TQ-06（管辖根组织保护）、TQ-07（集团下可建部门），均已按推荐写入 M1 契约；共享库 `data_scope_filter` 类型放宽、新增可注入 context loader（向后兼容） | M1 联调反馈 | BE-03、BE-07、FE-05；M2/M3 无需改动 |
| 2026-11-11 | 对照 PRD v0.3 校准：3.6 数据范围表补充集团本部口径；TQ-06/TQ-07 已确认；M1 新增 5.2.0 保护规则与 403103 | 用户确认、PRD v0.3 | BE-07、FE-05 |
| 2026-11-11 | 3.6 写明多角色数据范围取全部启用角色并集、与权限码来源无关；新增 SELF 在 iam 管理页的只读特例说明；`data_scope_filter` 签名与 M1 同步（允许可空列） | M1 第 1 轮测试后用户确认 | BE-07、BE-08（SELF 特例）、FE-05、FE-06 |
| 2026-11-12 | 检索性能：M2 新增 3.10 / BE-21b（HNSW 运行时索引、PG 参数、全文裁剪、混合并行）；风险表更新；13.10 登记"运行时建向量索引"规范例外；D3 结论更新为"pgvector：小库精确 + 大库 HNSW" | BE-21 压测不达标，用户决定 A+C+D | BE-21b、BE-29 |
| 2026-11-12 | 6.3 新增 `GET /api/v1/open-platform/audit/capabilities`（无法识别密钥开关的能力标记，不改 `/auth/me`）；M3 新增错误码 403605（admin_disabled 密钥不可编辑/重新生成）；详见 M3 第 12 节 | FE-18/20/21 契约澄清 | BE-25、BE-26、BE-27、FE-18、FE-20、FE-21 |

---

## 13. 规范变更建议（需主会话在用户确认后修改）

> 架构师不能修改 `CLAUDE.md`、`.claude/agents/*`、`.gitignore`。以下为建议的替换文本。
> 2026-11-11 状态：主会话已按本节修改上述文件，并另行把端口改为专属端口（见 3.9 与 CLAUDE.md 4.1）；本节中的端口数字已同步为新值，仅作留档。

### 13.1 `CLAUDE.md` 第 1 节"仓库结构"——整节替换为

````markdown
## 1. 仓库结构（monorepo，多服务）

```
.
├── CLAUDE.md                 # 本文件
├── .venv/                    # 全项目唯一的 Python 虚拟环境（所有后端服务共用，不进 git）
├── docker-compose.yml        # 本地中间件：PostgreSQL 16(+pgvector) + Redis 7 + MinIO
├── deploy/                   # 生产部署 docker-compose.prod.yml、.env.prod.example；local/ 本地 PG 初始化脚本
├── frontend/                 # React + Ant Design（单一 SPA）
├── backend/
│   ├── requirements.txt / requirements-dev.txt   # 所有服务共用，版本固定
│   ├── pyproject.toml        # 仅 ruff / mypy / pytest 配置
│   ├── Dockerfile            # 构建参数 SERVICE 选择服务
│   ├── scripts/devctl.py     # 本地一键 init / migrate / up / down / status
│   ├── libs/platform_common/ # 共享库：配置基类、DB、Redis、错误、响应、鉴权、数据权限、事件、操作日志
│   └── services/
│       ├── iam/              # 认证与权限服务 :8301
│       ├── kb/               # 知识库服务 :8302（main.py）+ 文档处理 worker（worker.py）
│       ├── open/             # 开放平台服务 :8303（API 密钥、开放检索、调用日志）
│       └── chat/             # 二期预留 :8304
├── docs/
│   ├── templates/
│   ├── features/<YYYYMMDD-简称>/  (input/、prd.md、tech-design*.md、test-report.md)
│   └── bugfixes/<YYYYMMDD-简称>/  (bugfix.md、tech-design.md、test-report.md)
└── .claude/
    ├── agents/
    └── commands/
```
````

### 13.2 `CLAUDE.md` 第 2 节表格——替换 `backend-dev`、`qa-tester` 两行

```markdown
| `backend-dev` | `backend/`、`docker-compose.yml`、`deploy/`、需求目录下的实现说明 | 改前端、私自改接口契约、跨服务 import 业务代码 |
| `qa-tester` | `backend/services/*/tests/integration/`、`frontend/e2e/`、`test-report.md` | 改业务代码（只报缺陷） |
```

并在"通用规则"末尾追加：

```markdown
- 后端任务（BE-xx）必须注明所属服务；一个任务只改一个服务目录（共享库任务除外）。
```

### 13.3 `CLAUDE.md` 第 3 节"中间件与部署"——替换为

```markdown
### 中间件与部署
- 本地：`docker compose` 只起中间件 —— **PostgreSQL 16（镜像 pgvector/pgvector:pg16）+ Redis 7 + MinIO**
- 向量检索用 pgvector，全文检索用 PostgreSQL tsvector + jieba 分词，异步任务与服务间事件用 Redis Streams；引入其他中间件须在 tech-design 中论证
- 前后端本地开发**不进容器**
- 生产：Docker 部署；每个后端服务一个镜像（`backend/Dockerfile` + `SERVICE` 构建参数），前端为 Nginx 镜像（静态资源 + 反向代理）
```

### 13.4 `CLAUDE.md` 第 4 节"后端规范"——4.1、4.2 整体替换，4.4 追加

````markdown
### 4.1 服务、启动与配置
- 后端由多个独立服务组成，位于 `backend/services/<服务>/`；通用能力只能放在 `backend/libs/platform_common/`（禁止放业务模型）。**服务之间禁止 import 对方代码**，只能通过内部 HTTP（`/internal/v1/*`，`X-Internal-Token`）和 Redis Streams 交互。
- 每个服务的 `main.py` 创建 app，并包含：
  ```python
  if __name__ == "__main__":
      uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
  ```
  kb 服务另有 `worker.py`（文档处理进程，同样 `python worker.py` 启动）。
- 启动单个服务：`cd backend/services/<服务> && ../../../.venv/bin/python main.py`；一键启动全部：`.venv/bin/python backend/scripts/devctl.py up`。**不开热加载**，修改后必须**重启进程**再验证（`devctl.py down` / `up`）。
- 端口（本机多项目共用，统一使用专属端口）：iam 8301、kb 8302、open 8303、chat 8304（预留）；宿主机中间件 PostgreSQL 15432、Redis 16379、MinIO 19000（API）/19001（控制台）；前端 dev 5174。容器内端口不变，生产部署不受影响。
- 配置：共享库提供 `BaseServiceSettings`，各服务在 `app/core/config.py` 继承扩展；**所有配置项带本地开发默认值**，可被 `backend/services/<服务>/.env` 或环境变量覆盖。`.env` 不进 git，`.env.example` 进 git，新增配置项必须同步。
- 共享库以可编辑方式安装：`.venv/bin/pip install -e backend/libs/platform_common`。

### 4.2 分层（每个服务内部，单向依赖：api → service → repository → model）
```
backend/services/<服务>/
  main.py  [worker.py]
  alembic.ini / alembic/          # 本服务独立迁移链，version_table 位于本服务 schema
  app/
    core/          # 本服务 config、常量
    deps/          # 本服务特有依赖（通用依赖来自 platform_common）
    models/        # ORM，__table_args__ = {"schema": "<服务名>"}
    schemas/       # Pydantic 请求/响应
    repositories/  # 所有查询；数据权限过滤统一调用 platform_common 的 data_scope_filter
    services/      # 业务逻辑、事务边界
    api/v1/        # 对外路由：只收参、声明权限、调 service
    api/internal/  # 内部路由（服务间调用）
  tests/           # 不进 git：unit/（开发写）、integration/（测试写）
```
- 路由层不写业务、不直接操作 session。
- 全异步：`async def` + asyncpg，请求链路中不做阻塞 IO；CPU 密集操作（文档解析、分词）放进程池或 worker。
````

4.3 "接口约定"追加：

```markdown
- 对外路由前缀与服务映射：`/api/v1/auth`、`/api/v1/system` → iam；`/api/v1/kb` → kb；`/api/v1/open-platform`、`/api/v1/open` → open；`/api/v1/chat` → chat。新增前缀须同步 Vite proxy 与 Nginx 配置。
- HTTP 状态码与错误类别一致（400/401/403/404/409/429/500/503），响应体始终为统一格式；`code = HTTP 状态 × 1000 + 序号`，序号段：通用 000~099、iam 100~299、kb 300~599、open 600~799、chat 800~899。
- 每个服务各自生成 OpenAPI（`/openapi.json`），前端分别生成类型。
```

4.4 "数据库约定"追加：

```markdown
- 一个 PostgreSQL 实例、一个库（`kbp`，测试库 `kbp_test`），**每个服务一个 schema**（iam / kb / open / chat）。禁止跨 schema 的外键、JOIN 和子查询；跨服务引用只存 ID，需要展示/筛选时使用本服务的只读副本表（由事件同步）或内部接口。
- 纯关联表允许物理删除（仍继承基类字段）；其他业务表逻辑删除。
- 受控表的 `dept_id` 表示"数据所属组织节点"（部门，或直属公司时为公司节点）。
```

### 13.5 `CLAUDE.md` 第 5 节追加 5.6

```markdown
### 5.6 多服务下的认证与权限
- iam 用 RS256 私钥签发 access token；其他服务只持有公钥本地验签。
- 每个请求由共享库 `get_auth_context` 校验：JWT → Redis 会话（`auth:sess:{sid}`，保证登出/改密/停用即时失效）→ 权限上下文（`authz:ctx:{user_id}`，未命中时调 iam 内部接口）。
- 权限码与数据范围只从权限上下文获取，任何服务不得自行查询 iam 的表。
- API 密钥只用于开放检索，由 open 服务校验。
```

### 13.6 `CLAUDE.md` 第 7 节表格——位置列替换

```markdown
| 后端单元/接口测试 | backend-dev | `backend/services/<服务>/tests/unit/`、`backend/libs/platform_common/tests/` | pytest |
| 后端集成测试（按 AC） | qa-tester | `backend/services/<服务>/tests/integration/`（跨服务场景放 `backend/tests_e2e_api/`） | pytest + httpx，真实 Postgres/Redis/MinIO，全部服务启动 |
```

### 13.7 `CLAUDE.md` 第 9 节"常用命令"——整节替换为

````markdown
## 9. 常用命令

```bash
# 中间件
docker compose up -d

# 后端环境（首次）
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
.venv/bin/pip install -e backend/libs/platform_common
.venv/bin/python backend/scripts/devctl.py init       # 生成本地 JWT 密钥对

# 迁移与启动（全部服务）
.venv/bin/python backend/scripts/devctl.py migrate    # 依次 iam → kb → open，并执行 iam seed
.venv/bin/python backend/scripts/devctl.py up         # 前台；加 -d 后台；可指定服务：up iam kb
.venv/bin/python backend/scripts/devctl.py down
.venv/bin/python backend/scripts/devctl.py --env test migrate   # 测试库 kbp_test

# 单个服务（以 iam 为例）
cd backend/services/iam && ../../../.venv/bin/alembic upgrade head
cd backend/services/iam && ../../../.venv/bin/python main.py
cd backend/services/iam && ../../../.venv/bin/mypy app && ../../../.venv/bin/pytest tests/unit
cd backend && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .

# 前端（首次需安装 pnpm：corepack enable && corepack prepare pnpm@9 --activate）
cd frontend && pnpm install && pnpm dev
cd frontend && pnpm gen:api                           # 从三个服务的 /openapi.json 生成类型（服务需已启动）
cd frontend && pnpm tsc --noEmit && pnpm lint && pnpm build
cd frontend && pnpm test
cd frontend && pnpm exec playwright test
```
````

### 13.8 `.gitignore` 建议调整

```gitignore
# 替换原"后端配置"段
backend/**/.env
backend/**/.env.*
!backend/**/.env.example
backend/.secrets/

# 替换原 backend/tests/ 一行
backend/**/tests/
backend/tests_e2e_api/

# 新增运行产物
.run/
```

### 13.10 规范例外登记（2026-11-12 新增，需主会话在用户确认后写入 CLAUDE.md 4.4）

```markdown
- 例外：kb 的向量 HNSW 索引（`kb.ix_seg_hnsw_m{模型ID}`、`kb.ix_child_hnsw_m{模型ID}`）依赖运行时的模型 ID 与维度，由 kb-worker 以 `CREATE INDEX CONCURRENTLY` 在运行时创建、对账与删除，不走 Alembic。除此之外的任何表结构/索引变更仍必须走 Alembic 迁移。
```

### 13.9 智能体提示词调整

**`.claude/agents/backend-dev.md`**

- description 中"只改 backend/ 和 docker-compose.yml" → "只改 `backend/`、`docker-compose.yml`、`deploy/`"。
- "职责边界"第一条替换为：`**只修改 backend/、docker-compose.yml、deploy/**，以及在需求目录的 tech-design*.md 中补充"实现说明"。每个 BE 任务注明所属服务，只在该服务目录（和任务明确列出的共享库文件）内修改；禁止跨服务 import。`
- "环境约定"整段替换为：

```markdown
## 环境约定（重要）
- **不使用 uv / poetry**。Python 环境是仓库根目录的 `.venv`（所有服务共用）。在服务目录 `backend/services/<服务>/` 下执行时使用 `../../../.venv/bin/python`；在 `backend/` 下执行时使用 `../.venv/bin/python`。
- 新增依赖：写入 `backend/requirements.txt` 或 `requirements-dev.txt`，**固定版本号**，然后 `pip install -r`。共享库修改后无需重装（可编辑安装）。
- 中间件：`docker compose up -d`（PostgreSQL+pgvector、Redis、MinIO），先确认容器在运行。
- 启动：单服务 `cd backend/services/<服务> && ../../../.venv/bin/python main.py`；联调用 `.venv/bin/python backend/scripts/devctl.py up -d <服务...>`，**没有热加载**。修改后先 `devctl.py down`（或按端口找 PID kill）再启动。验证完毕停止你启动的进程。
- 配置项定义在服务的 `app/core/config.py`（继承共享库 `BaseServiceSettings`，带本地默认值），新增配置同步更新该服务的 `.env.example`。
- 共享库 `platform_common` 是所有服务的基础，修改其公开接口（函数签名、AuthContext 字段、错误码）属于契约变更，必须先提"契约变更申请"。
```

- "完成标准"中的命令替换为在服务目录执行：`../../../.venv/bin/mypy app`、`../../../.venv/bin/alembic upgrade head`、`../../../.venv/bin/pytest tests/unit`；ruff 在 `backend/` 下执行；第 5 条改为"重启该服务后用 curl 调用（通过 iam 登录取 token），`/docs` 正常"。
- 编码规范追加："内部接口挂 `/internal/v1`，依赖 `require_internal`；跨服务调用使用共享库 `InternalClient`，设置超时并处理 503001。"

**`.claude/agents/qa-tester.md`**

- 职责边界"只写"改为 `backend/services/*/tests/integration/`、`backend/tests_e2e_api/`、`frontend/e2e/`、`test-report.md`。
- "测试环境"第 2 步改为：`.venv/bin/python backend/scripts/devctl.py --env test migrate`，`devctl.py --env test up -d`（启动全部服务与 worker），结束时 `devctl.py down`。
- 测试维度追加一条"**服务故障与一致性**：停止单个服务/worker 时其他服务的表现；权限变化跨服务即时生效。"

**`.claude/agents/frontend-dev.md`**

- 编码规范追加："接口按服务分文件：`src/services/iam.ts`、`kb.ts`、`open.ts`，类型由 `pnpm gen:api` 从三个服务生成到 `src/services/types/`。新增路由前缀需同步 `vite.config.ts` 的 proxy。"

**`.claude/agents/architect.md`**

- 职责边界"不修改 frontend/、backend/"保持；工作流程第 2 步追加："多服务下需写明每个接口/表/任务所属服务。"

**`.claude/commands/feature.md`**

- 步骤 3 派发开发时追加："BE 任务按服务分批派发；同一服务的任务不要同时派给两个后端智能体（避免迁移链冲突）；不同服务的任务可并行。"

---

## 14. 关键架构决策（请用户确认）

| 编号 | 决策 | 推荐 | 备选 | 推荐理由 / 代价 |
|---|---|---|---|---|
| D1 | 服务拆分粒度 | **iam / kb（API）/ kb-worker / open 四个进程，chat 二期**；kb 管理与检索同代码、可分组部署 | A. 检索拆成独立 retrieval 服务；B. 先做模块化单体，后拆 | A 会造成检索服务跨 schema 读 kb 数据或双写；B 不满足用户"分开部署"的明确诉求。推荐方案独立扩容能力已足够 |
| D2 | 数据库隔离 | **一实例一库、每服务一个 schema**，禁止跨 schema 访问 | 每服务一库 | 运维最简，将来拆库只改 DSN |
| D3 | 向量库 | **pgvector：小库精确检索 + 大库按模型 HNSW 部分索引**（2026-11-12 依 BE-21 压测调整），`VectorStore` 抽象 | Qdrant（多一个中间件，需双写同步） | 规模内满足且强一致；大库性能在 M2 压测验证 |
| D4 | 全文检索 | **PG tsvector + jieba** | Elasticsearch + IK | 少一套 JVM 中间件与数据同步 |
| D5 | 任务队列 / 事件 | **Redis Streams（自封装消费组）** | arq / Celery / RabbitMQ | 无新中间件、无新依赖，任务状态以 PG 为准 |
| D6 | 文件存储 | **MinIO（S3 协议）** | 本地磁盘 + NFS | 多节点共享，生产可换云 OSS |
| D7 | API 密钥归属 | **open 服务**（管理、校验、日志、限流内聚） | 放在 iam（凭证统一管理，但统计需跨服务聚合、热路径多一跳） | 用户原话把"API 密钥校验"列在权限认证中，此处与之不同，需确认 |
| D8 | 前端应用数 | **本期单一 SPA**，二期聊天作为独立应用，届时把 `frontend/` 改为 pnpm workspace（`apps/console`、`apps/chat`、`packages/shared`） | 本期即建 workspace / 微前端（qiankun、Module Federation） | 本期只有一个使用界面，提前拆分增加构建与协作成本；目录按模块组织，二期迁移成本低（主要是移动文件） |
| D9 | JWT 与吊销 | **RS256 + 每请求查 Redis 会话** | HS256 共享密钥 | 只有 iam 能签发，其他服务泄露也无法伪造令牌 |
| D10 | 共享代码方式 | **`platform_common` 可编辑安装进唯一 .venv** | 每服务复制一份 / git submodule | 符合"一个 .venv"约束，改一处全体生效 |
| D11 | Rerank 协议 | **Jina/Cohere 兼容 `POST {base_url}/rerank`** | 只支持某一家 | OpenAI 无 rerank 标准接口，PRD"OpenAI 兼容"对 Rerank 无法字面满足 |
| D12 | 分段 token 计数 | **tiktoken `cl100k_base` 估算** | 按模型加载 HF tokenizer（需下载、体积大） | 预览与处理一致即可；与模型真实分词的偏差在风险表中说明 |

### 14.1 需要产品/用户确认的 PRD 细节（不阻塞 M1 开工）

| 编号 | 问题 | 推荐 | 影响 |
|---|---|---|---|
| TQ-01 | F-12 规则"任一中间状态 30 分钟无进度即失败"：处理高峰时"排队中"可能合理地超过 30 分钟，会被误判失败 | "排队中"不计入超时；只对解析中/分段中/索引中计时；排队消息若丢失由巡检重新投递 | F-12、AC-41 |
| TQ-02 | 组织"类型"能否修改（PRD 只说子公司管理员不能改本公司节点类型） | 组织类型创建后不可修改（改类型会连锁改变下级的所属公司和数据归属） | F-02 |
| TQ-03 | 角色编码、类型、所属公司能否修改 | 创建后不可修改；名称、状态、备注、权限、数据范围可改 | F-04 |
| TQ-04 | 无法识别密钥的失败调用可能被恶意刷量，日志膨胀 | 按来源 IP 对"无效密钥"日志做采样：同一 IP 每分钟最多记 20 条，超出只计数到运行日志 | F-19、AC-58 |
| TQ-05 | 管理视图"每次进入查看内容都记操作日志"：进入详情页记 1 条；翻页、打开分段列表是否每次都记 | 进入知识库审计详情记 1 条，打开某文档的分段列表再记 1 条（含文档名），翻页不记；实现见 M2 5.8.1（`audit_entry` + 30 分钟去重兜底） | F-20、AC-67 |
| TQ-06（已确认，PRD v0.3 A-31） | 子公司管理员能否停用/删除自己管辖的根组织（本公司节点）？PRD 只限制了"不能改本公司节点的上级和类型" | 不能：非超管、非 ALL 范围的管理员不能停用/删除其管辖根节点；任何人不能停用本人所在组织（含上级），需由上级管理员操作 | F-02、AC-08 |
| TQ-07（已确认，PRD v0.3 A-30） | 集团节点下能否直接建部门？PRD F-02 规则 2 写"部门的上级可以是公司或部门"，但 F-10 规则 5 提到"集团下的部门"（集团本部） | 可以：集团节点视同"集团本部公司"，可直接下设部门 | F-02、F-10 |
