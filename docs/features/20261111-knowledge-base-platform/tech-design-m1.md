# M1 平台地基 技术方案（工程 + 共享库 + iam + 前端骨架）

- 关联：`./prd.md`（v0.3）F-01 ~ F-06，AC-01 ~ AC-21、AC-74；总体方案 `./tech-design.md`
- 状态：草稿
- 本分册覆盖：BE-01 ~ BE-10、FE-01 ~ FE-08

## 1. 范围

| 功能点 | 覆盖 | 说明 |
|---|---|---|
| F-01 | ✅ | 登录、刷新、登出、改密、强制改密、锁定、会话吊销、登录日志 |
| F-02 | ✅ | 组织树 CRUD、移动、停用、删除检查（"存在知识库"检查在 M2 接入，M1 先降级为 0） |
| F-03 | ✅ | 用户 CRUD、停用、重置密码、分配角色；停用/删除影响提示（M2/M3 接入计数） |
| F-04 | ✅ | 角色、权限树、授权上限、自锁确认 |
| F-05 | ✅ | 数据范围解析 + 共享过滤函数，在用户/组织/日志上生效 |
| F-06 | ✅ | 操作日志汇聚（Stream）+ 查询；登录日志；180 天清理 |

## 2. 现状

全新仓库，无代码。M1 产出的 `platform_common` 是 M2/M3 的前置。

---

## 3. 工程与共享库设计

### 3.1 后端目录（M1 结束时）

```
backend/
  requirements.txt  requirements-dev.txt  pyproject.toml
  scripts/devctl.py
  libs/platform_common/
    pyproject.toml
    platform_common/
      __init__.py
      config.py          # BaseServiceSettings
      db.py              # create_engine/session_factory、Base、AuditMixin、VersionMixin、get_db 依赖
      redis.py           # get_redis()、连接池
      errors.py          # BizError、CommonErrors、全局异常处理器注册
      response.py        # ok()/page() 统一响应、ApiResponse[T]、Page[T] 泛型 schema
      pagination.py      # PageParams 依赖（page/page_size 校验）
      logging.py         # 结构化日志、request_id 上下文
      app_factory.py     # create_app(settings, routers, lifespan_hooks) → 注册中间件/异常/healthz/readyz
      client_ip.py       # get_client_ip(request, trusted_proxies)
      http_client.py     # InternalClient（httpx.AsyncClient，带 X-Internal-Token/X-Request-Id，超时，错误映射为 503001）
      crypto.py          # sha256、hmac、随机串
      auth/
        jwt.py           # verify_access_token(token) -> AccessClaims（只验签，公钥）
        context.py       # AuthContext / DataScope 模型；load_auth_context(user_id) 读缓存→回源 iam
        deps.py          # get_auth_context、require_login、require_perm
        data_scope.py    # data_scope_filter(...)
        internal.py      # require_internal
        cache_keys.py    # 所有 Redis key 规范
      events/
        streams.py       # Stream 名常量
        publisher.py     # publish(stream, type, payload) / publish_after_commit
        consumer.py      # StreamConsumer（消费组、XAUTOCLAIM、重试、死信）
      oplog.py           # OpLogEvent、emit_oplog、oplog_scope、mask_sensitive
      jobs.py            # run_periodic(name, interval, coro, lock=True) —— 基于 Redis SET NX EX 的单实例定时任务
    tests/
  services/iam/
    main.py  .env.example  alembic.ini
    alembic/env.py  alembic/versions/
    app/
      core/config.py  core/security.py(签发 JWT、bcrypt)  core/constants.py
      models/ org.py user.py role.py permission.py session.py log.py
      schemas/ auth.py org.py user.py role.py permission.py log.py
      repositories/ org_repo.py user_repo.py role_repo.py permission_repo.py session_repo.py log_repo.py
      services/ auth_service.py session_service.py authz_service.py org_service.py user_service.py role_service.py log_service.py event_service.py downstream.py
      api/v1/ auth.py orgs.py users.py roles.py permissions.py logs.py  __init__.py(汇总 router)
      api/internal/ authz.py sync.py
      seed/ __main__.py permission_registry.py builtin.py
      jobs/ oplog_consumer.py log_cleanup.py
    tests/unit/
deploy/local/postgres-init.sql
docker-compose.yml
```

### 3.2 `platform_common` 公开接口（契约，M2/M3 直接依赖，修改需走契约变更）

```python
# config.py
class BaseServiceSettings(BaseSettings):
    APP_ENV: str = "dev"                       # dev / test / prod
    SERVICE_NAME: str                          # iam / kb / open（子类给默认值）
    HOST: str = "127.0.0.1"
    PORT: int                                  # 子类给默认值
    DATABASE_URL: str = "postgresql+asyncpg://kbp:kbp@localhost:15432/kbp"
    DB_POOL_SIZE: int = 10
    REDIS_URL: str = "redis://localhost:16379/0"
    JWT_PUBLIC_KEY_FILE: str = "<backend>/.secrets/jwt_public.pem"   # 相对路径按 backend/ 解析
    JWT_ISSUER: str = "kbp-iam"
    INTERNAL_API_TOKEN: str = "dev-internal-token-change-me"   # 生产必须覆盖，见下方启动校验
    IAM_INTERNAL_URL: str = "http://127.0.0.1:8301"
    KB_INTERNAL_URL: str = "http://127.0.0.1:8302"
    OPEN_INTERNAL_URL: str = "http://127.0.0.1:8303"
    INTERNAL_HTTP_TIMEOUT_SECONDS: float = 10.0
    TRUSTED_PROXIES: list[str] = ["127.0.0.1/32", "::1/128"]   # 仅本地开发默认；生产只填 Nginx 地址/网段
    AUTHZ_CTX_TTL_SECONDS: int = 600
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Asia/Shanghai"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_for_runtime(self) -> None:
        """create_app 启动时调用：APP_ENV 不在 {"dev", "test"} 时，若 INTERNAL_API_TOKEN 等于开发默认值
        或长度 < 32，抛出异常拒绝启动（日志明确提示需要覆盖哪个配置）。子类可扩展同类检查
        （kb: MODEL_SECRET_KEY；open: API_KEY_PEPPER；iam: SEED_ADMIN_PASSWORD 仍为默认值时只告警）"""

# errors.py
class BizError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None: ...
    # http_status = code // 1000
class CommonErrors:  # 常量，取值见总体方案 4.2
    INVALID_PARAMS = (400001, "参数不合法"); UNAUTHENTICATED = (401001, ...); SESSION_INVALID = (401002, ...)
    FORBIDDEN = (403001, ...); MUST_CHANGE_PASSWORD = (403002, ...); NOT_FOUND = (404000, "无权限或数据不存在")
    VERSION_CONFLICT = (409001, ...); TOO_MANY_REQUESTS = (429001, ...); INTERNAL = (500000, ...)
    DEPENDENCY_UNAVAILABLE = (503001, ...); INTERNAL_TOKEN_INVALID = (401901, ...)

# auth/context.py
class DataScope(BaseModel):
    all: bool = False
    company_ids: list[int] = []
    org_ids: list[int] = []
    include_self: bool = False

class AuthContext(BaseModel):
    user_id: int; username: str; name: str
    status: Literal["enabled", "disabled"]; is_deleted: bool; org_enabled: bool
    org_id: int; company_id: int; org_path: list[int]
    is_super_admin: bool; must_change_password: bool
    permissions: list[str]
    data_scope: DataScope
    epoch: int; computed_at: datetime
    @property
    def usable(self) -> bool: ...            # status=enabled and not is_deleted and org_enabled
    def has_perm(self, code: str) -> bool: ... # super_admin 恒为 True

async def load_auth_context(user_id: int) -> AuthContext | None:
    """MGET authz:ctx:{uid} + authz:epoch；命中且 epoch 一致直接返回；否则调 iam
    GET /internal/v1/authz/contexts/{uid}；iam 返回 404 → None。iam 不可用 → BizError(503001)
    回源方式由 auth/runtime.py 的已注册 loader 决定"""

# auth/runtime.py
ContextLoader = Callable[[int], Awaitable[AuthContext | None]]   # 计算并写缓存，用户不存在返回 None
def set_context_loader(loader: ContextLoader) -> None
    # 默认 loader = HTTP 调 iam 内部接口（kb/open 使用）；iam 在 lifespan 启动时注册本地 loader
    # （直接调用 authz_service 计算并写 authz:ctx），避免进程回调自身 HTTP。只允许在启动阶段调用一次

# auth/deps.py
async def get_auth_context(request: Request) -> AuthContext:
    """完整校验链（总体方案 3.5.1 第 1~6 步），结果放 request.state.ctx。
    白名单（允许 must_change_password）：由 require_login(allow_must_change=True) 声明"""
def require_login(allow_must_change: bool = False) -> Callable[..., Awaitable[AuthContext]]
def require_perm(*codes: str, mode: Literal["all", "any"] = "all") -> Callable[..., Awaitable[AuthContext]]
# 用法：dependencies=[Depends(require_perm("system:user:create"))]，或 ctx: AuthContext = Depends(require_perm(...))

# auth/data_scope.py
def data_scope_filter(ctx: AuthContext, *, company_col: ColumnElement[int] | ColumnElement[int | None],
                      dept_col: ColumnElement[int] | ColumnElement[int | None],
                      owner_col: ColumnElement[int] | ColumnElement[int | None]) -> ColumnElement[bool]
    # 列参数允许可空列（如日志表 company_id/dept_id）；值为 NULL 的行只有 all/超管可见（SQL 中 NULL = ANY(...) 不成立），语义不变
def in_data_scope(ctx: AuthContext, *, company_id: int | None, dept_id: int | None, owner_id: int | None) -> bool
    # 对单条已加载数据做同样判断（写操作前校验）

# auth/internal.py
async def require_internal(x_internal_token: str = Header(...)) -> None   # 不匹配 → 401901

# events/publisher.py
async def publish(stream: str, type_: str, payload: dict[str, Any]) -> str   # 返回 event_id
def publish_after_commit(session: AsyncSession, stream: str, type_: str, payload: dict) -> None
    # 注册到 session.info，提交成功后发布；发布失败只记日志

# events/consumer.py
class StreamConsumer:
    def __init__(self, stream: str, group: str, handler: Callable[[dict], Awaitable[None]],
                 *, batch: int = 50, block_ms: int = 5000, claim_idle_ms: int = 600_000, max_retries: int = 5): ...
    async def run_forever(self) -> None   # 自动建组(MKSTREAM)；成功 XACK；超过重试次数转 stream:dead
    async def stop(self) -> None

# oplog.py
class OpLogEvent(BaseModel):
    event_id: str; service: str; occurred_at: datetime
    operator_id: int; operator_username: str; operator_name: str
    company_id: int | None; dept_id: int | None
    module: str; action: str
    target_type: str; target_id: str | None; target_name: str | None
    summary: dict[str, Any] = {}       # {"before": {...}, "after": {...}} 或自定义，已脱敏
    result: Literal["success", "failure"]; error_message: str | None = None
    ip: str | None; user_agent: str | None; request_id: str | None
async def emit_oplog(event: OpLogEvent) -> None            # 永不抛异常
def oplog_scope(request: Request, ctx: AuthContext, *, module: str, action: str,
                target_type: str, target_id: Any = None, target_name: str | None = None) -> AsyncContextManager[OpLogHandle]
def mask_sensitive(data: dict[str, Any]) -> dict[str, Any]

# jobs.py
async def run_periodic(name: str, interval_seconds: int, func: Callable[[], Awaitable[None]], *, singleton: bool = True) -> None
```

Redis key 规范（`auth/cache_keys.py`）：

| key | 类型 | TTL | 写入方 | 说明 |
|---|---|---|---|---|
| `auth:sess:{sid}` | string(JSON `{"user_id":..,"created_at":..}`) | 7 天，刷新时续期 | iam | 会话存在即有效 |
| `auth:user_sess:{user_id}` | set(sid) | 7 天 | iam | 用于吊销某用户全部会话 |
| `auth:fail:{username}` | int | 900s | iam | 登录失败计数 |
| `auth:lock:{username}` | string | 900s | iam | 锁定标记 |
| `authz:ctx:{user_id}` | string(JSON AuthContext) | 600s | iam | 权限上下文 |
| `authz:epoch` | int | 永久 | iam | 全局失效版本号 |
| `job:lock:{name}` | string | 任务间隔 | 各服务 | 单实例定时任务锁 |

### 3.3 中间件与本地编排

`docker-compose.yml`：

| 服务 | 镜像 | 宿主机端口 → 容器端口 | 说明 |
|---|---|---|---|
| postgres | `pgvector/pgvector:pg16` | `${POSTGRES_PORT:-15432}` → 5432 | 用户/密码/库 `kbp/kbp/kbp`；挂载 `deploy/local/postgres-init.sql` 到 `/docker-entrypoint-initdb.d/`：创建库 `kbp_test`，并在 `kbp`、`kbp_test` 中 `CREATE EXTENSION IF NOT EXISTS vector`；数据卷 `.docker-data/postgres` |
| redis | `redis:7-alpine` | `${REDIS_PORT:-16379}` → 6379 | `appendonly yes`；数据卷 `.docker-data/redis` |
| minio | `minio/minio` | `${MINIO_API_PORT:-19000}` → 9000、`${MINIO_CONSOLE_PORT:-19001}` → 9001 | `minioadmin/minioadmin`；数据卷 `.docker-data/minio`；healthcheck：`curl -f http://localhost:9000/minio/health/live` |

- **不使用 `minio/mc` 一次性容器**（本机无法拉取该镜像）；桶 `kbp-files`、`kbp-test` 由 `devctl.py init` 幂等创建（见 3.4）。
- 宿主机端口均可用环境变量覆盖（compose 中写成 `${VAR:-默认}`）；覆盖后需同步各服务 `.env` 的 `DATABASE_URL`、`REDIS_URL`、`S3_ENDPOINT`。
- 容器内端口保持默认值；生产部署（M3 BE-29）在容器网络内使用服务名 + 容器端口，不受宿主机端口影响。
- （MinIO 在 M2 才使用，但 M1 一并编排，避免之后再改 compose。）

### 3.4 `devctl.py` 规格（标准库 + cryptography + boto3）

| 命令 | 行为 |
|---|---|
| `init` | ① 若 `backend/.secrets/jwt_private.pem` 不存在，用 `cryptography` 生成 RSA 2048 密钥对（`jwt_private.pem`、`jwt_public.pem`）；② 用 `boto3`（随 `aioboto3` 安装，requirements 中固定版本）连接 `S3_ENDPOINT`（默认 `http://127.0.0.1:19000`，可由环境变量 `S3_ENDPOINT`/`S3_ACCESS_KEY`/`S3_SECRET_KEY` 覆盖）幂等创建桶 `kbp-files`、`kbp-test`（已存在则跳过；MinIO 不可达时给出明确提示并以非 0 退出，密钥生成结果保留）。`migrate` 开始前同样执行一次建桶检查 |
| `migrate [svc...]` | 依次在 `services/iam`、`services/kb`、`services/open`（存在才执行）运行 `alembic upgrade head`；iam 之后运行 `python -m app.seed` |
| `up [-d] [svc...]` | svc 取值 `iam kb kb-worker open`（默认全部已存在的）；cwd=服务目录，命令 `<repo>/.venv/bin/python main.py`（kb-worker 为 `worker.py`）；前台模式合并输出并加 `[iam]` 前缀，Ctrl-C 向全部子进程发 SIGTERM；`-d` 时日志写 `logs/<svc>.log`、PID 写 `.run/<svc>.pid` |
| `down [svc...]` | 读 PID 文件发 SIGTERM，10 秒未退出则 SIGKILL；PID 文件缺失时按端口（`ss -ltnp` 解析）兜底，**但只终止 cwd 位于 `backend/services/` 下的本项目进程**，绝不终止其他项目的进程（CLAUDE.md 4.1） |
| `status` | 列出各服务 PID、端口（iam 8301、kb 8302、open 8303）、`/healthz` 结果 |
| `--env test` | 为子进程注入 `DATABASE_URL=postgresql+asyncpg://kbp:kbp@localhost:15432/kbp_test`、`REDIS_URL=redis://localhost:16379/1`、`S3_BUCKET=kbp-test`、`APP_ENV=test` |

---

## 4. 数据模型（schema `iam`）

> 基类字段（id、created_at、updated_at、created_by、updated_by、is_deleted）见总体方案 4.3，下表不再重复列出。

### 4.1 `iam.sys_org`（受数据权限控制：是；本人列 created_by）

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| parent_id | BIGINT | NOT NULL, INDEX | 0 | 集团根节点为 0 |
| ancestors | VARCHAR(1000) | NOT NULL | '0' | 祖级路径，不含自身，如 `0,1,5` |
| org_type | VARCHAR(16) | NOT NULL | | `group` / `company` / `dept` |
| name | VARCHAR(50) | NOT NULL | | |
| code | VARCHAR(32) | NOT NULL, UNIQUE（含已删除） | | 创建后不可改 |
| leader_user_id | BIGINT | NULL | | 负责人 |
| sort_order | INT | NOT NULL | 0 | 0~9999 |
| status | VARCHAR(16) | NOT NULL | 'enabled' | `enabled` / `disabled`（自身状态；生效状态需看祖先） |
| company_id | BIGINT | NOT NULL, INDEX | | 所属公司：公司/集团节点为自身 ID，部门为向上最近的公司/集团 |
| dept_id | BIGINT | NOT NULL, INDEX | | = 自身 id（数据所属组织节点；插入后同事务回填） |
| version | INT | NOT NULL | 1 | 乐观锁 |

- 索引：`uq_sys_org_parent_name (parent_id, name) WHERE is_deleted=false`；`ix_sys_org_parent_sort (parent_id, sort_order, created_at)`。
- 集团节点（`org_type=group`）全系统唯一：`uq_sys_org_group ON (org_type) WHERE org_type='group' AND is_deleted=false`。
- 集团节点同时代表"集团本部"（PRD v0.3 F-02 规则 1、A-30）：集团节点可直接下设部门；集团节点及其下（不经过任何公司节点）的部门，`company_id` = 集团节点 ID；直属集团节点或归属这些部门的用户，所属公司 = 集团节点（F-03 规则 1）。

### 4.2 `iam.sys_user`（受数据权限控制：是；本人列 created_by）

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| username | VARCHAR(32) | NOT NULL, UNIQUE（含已删除） | | `^[A-Za-z][A-Za-z0-9_]{3,31}$`；**区分大小写**：唯一约束按原值（`Zhangsan` 与 `zhangsan` 是两个账号），登录按原值精确匹配，锁定计数 key 也按输入原值 |
| password_hash | VARCHAR(100) | NOT NULL | | bcrypt（cost 12） |
| name | VARCHAR(30) | NOT NULL | | |
| org_id | BIGINT | NOT NULL, INDEX | | 主组织（集团/公司/部门节点） |
| company_id | BIGINT | NOT NULL, INDEX | | 冗余：所属公司，组织移动时重算 |
| dept_id | BIGINT | NOT NULL, INDEX | | = org_id |
| mobile | VARCHAR(11) | NULL | | `uq_sys_user_mobile (mobile) WHERE mobile IS NOT NULL AND is_deleted=false` |
| email | VARCHAR(100) | NULL | | |
| status | VARCHAR(16) | NOT NULL | 'enabled' | |
| is_builtin | BOOLEAN | NOT NULL | false | `admin` 为 true：不可删除、不可停用 |
| must_change_password | BOOLEAN | NOT NULL | true | 新建与重置后为 true |
| password_changed_at | TIMESTAMPTZ | NULL | | |
| last_login_at | TIMESTAMPTZ | NULL | | |
| last_login_ip | VARCHAR(64) | NULL | | |
| version | INT | NOT NULL | 1 | |

### 4.3 `iam.sys_role`（受数据权限控制：否，可见规则见 5.4）

| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| code | VARCHAR(50) | NOT NULL, UNIQUE（含已删除） | | `^[A-Za-z0-9_]{2,50}$`，创建后不可改 |
| name | VARCHAR(30) | NOT NULL | | |
| role_type | VARCHAR(16) | NOT NULL | | `group` / `company`，创建后不可改 |
| owner_company_id | BIGINT | NULL, INDEX | | 公司级必填，创建后不可改 |
| data_scope | VARCHAR(32) | NOT NULL | 'SELF' | 7 种之一 |
| status | VARCHAR(16) | NOT NULL | 'enabled' | |
| remark | VARCHAR(200) | NULL | | |
| is_builtin | BOOLEAN | NOT NULL | false | |
| builtin_key | VARCHAR(32) | NULL, UNIQUE | | `super_admin`/`group_admin`/`company_admin`/`employee` |
| version | INT | NOT NULL | 1 | |

- 唯一：`uq_sys_role_name (COALESCE(owner_company_id, 0), name) WHERE is_deleted=false`。

### 4.4 `iam.sys_role_org`（否；关联表，物理删除）
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| role_id | BIGINT | NOT NULL | |
| org_id | BIGINT | NOT NULL | |
- 唯一 `(role_id, org_id)`；索引 `org_id`。

### 4.5 `iam.sys_permission`（否）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| code | VARCHAR(100) | NOT NULL, UNIQUE | | `模块:资源:操作` |
| name | VARCHAR(50) | NOT NULL | | |
| perm_type | VARCHAR(16) | NOT NULL | | `menu` / `button` / `api` |
| parent_id | BIGINT | NOT NULL, INDEX | 0 | |
| path | VARCHAR(200) | NULL | | 菜单路由 |
| icon | VARCHAR(50) | NULL | | `@ant-design/icons` 组件名 |
| sort_order | INT | NOT NULL | 0 | |
| service | VARCHAR(16) | NOT NULL | | iam / kb / open（归属服务，便于排查） |
| super_only | BOOLEAN | NOT NULL | false | 预留：仅超管可拥有 |

### 4.6 `iam.sys_role_permission`（否；物理删除）
`role_id`、`permission_id`，唯一 `(role_id, permission_id)`。

### 4.7 `iam.sys_user_role`（否；物理删除）
| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | BIGINT NOT NULL INDEX | |
| role_id | BIGINT NOT NULL INDEX | |
| org_id | BIGINT NULL | 预留：在哪个组织下授予（本期写入用户主组织） |
- 唯一 `(user_id, role_id)`。

### 4.8 `iam.sys_user_session`（否）
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| sid | UUID | NOT NULL, UNIQUE | 会话 ID（JWT `sid`） |
| user_id | BIGINT | NOT NULL, INDEX | |
| refresh_token_hash | CHAR(64) | NOT NULL, UNIQUE | SHA-256(refresh_token) |
| expires_at | TIMESTAMPTZ | NOT NULL | 最近一次使用 + 7 天 |
| last_active_at | TIMESTAMPTZ | NOT NULL | |
| ip | VARCHAR(64) | NULL | |
| user_agent | VARCHAR(500) | NULL | |
| revoked_at | TIMESTAMPTZ | NULL | |
| revoke_reason | VARCHAR(32) | NULL | `logout`/`password_changed`/`password_reset`/`user_disabled`/`user_deleted`/`org_disabled`（组织停用时吊销子树用户会话） |

### 4.9 `iam.sys_login_log`（受数据权限控制：是；本人列 created_by = user_id）
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| username | VARCHAR(64) | NOT NULL, INDEX | 输入的账号（截断 64） |
| user_id | BIGINT | NULL | 账号不存在时为空 |
| company_id | BIGINT | NULL, INDEX | 账号不存在时为空（仅 ALL 可见） |
| dept_id | BIGINT | NULL, INDEX | |
| result | VARCHAR(16) | NOT NULL | `success` / `failure` |
| fail_reason | VARCHAR(32) | NULL | 成功时为空；失败取值见下表（**完整枚举，不会出现其他值**） |
| fail_message | VARCHAR(200) | NULL | 中文说明 |
| ip | VARCHAR(64) | NULL | |
| user_agent | VARCHAR(500) | NULL | |
| login_at | TIMESTAMPTZ | NOT NULL, INDEX | |

`fail_reason` 完整枚举（登录日志列表的"失败原因"按此映射中文；`fail_message` 为写入时的中文说明，可作回退）：

| fail_reason | 中文含义 | 触发条件 | 对应错误码 |
|---|---|---|---|
| `bad_credentials` | 账号或密码错误 | 账号不存在（含已删除）或密码错误 | 401101 |
| `locked` | 账号已锁定 | 处于 15 分钟锁定期内（含锁定期内输入正确密码） | 401102 |
| `user_disabled` | 账号已停用 | 用户状态为停用 | 401103 |
| `org_disabled` | 所属组织已停用 | 主组织或任一上级组织停用 | 401103 |

### 4.10 `iam.sys_operation_log`（受数据权限控制：是；本人列 created_by = operator_id）
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| event_id | UUID | NOT NULL, UNIQUE | 幂等 |
| service | VARCHAR(16) | NOT NULL | |
| operator_id | BIGINT | NOT NULL, INDEX | |
| operator_username | VARCHAR(32) | NOT NULL | |
| operator_name | VARCHAR(30) | NOT NULL | |
| company_id | BIGINT | NULL, INDEX | 操作人所属公司（写入时） |
| dept_id | BIGINT | NULL, INDEX | 操作人所属组织 |
| company_name | VARCHAR(50) | NULL | 入库时由 iam 查名称冗余 |
| module | VARCHAR(32) | NOT NULL | 枚举见 5.8 |
| action | VARCHAR(32) | NOT NULL | 枚举见 5.8 |
| target_type | VARCHAR(32) | NOT NULL | |
| target_id | VARCHAR(64) | NULL | |
| target_name | VARCHAR(200) | NULL | |
| summary | JSONB | NOT NULL | '{}' |
| result | VARCHAR(16) | NOT NULL | |
| error_message | VARCHAR(500) | NULL | |
| ip | VARCHAR(64) | NULL | |
| user_agent | VARCHAR(500) | NULL | |
| request_id | VARCHAR(64) | NULL | |
| occurred_at | TIMESTAMPTZ | NOT NULL, INDEX | |

- 日志表只增不改；180 天以前的数据由定时任务**物理删除**（保留期策略，非业务删除）。

### 4.11 Alembic 与初始化
- `services/iam/alembic/env.py`：`version_table_schema="iam"`，`include_schemas=True`，只包含 `iam` schema 的对象。
- `0001_init_iam`：`CREATE SCHEMA IF NOT EXISTS iam` + 上述 10 张表 + 索引；downgrade：**逐表 `DROP TABLE`（含索引），保留空的 `iam` schema**——因为 `alembic_version` 表位于 `iam` schema 内，删除 schema 会导致 Alembic 无法回写版本；需要彻底清理时由运维手工 `DROP SCHEMA iam CASCADE`。
- Seed（`python -m app.seed`，幂等，devctl migrate 自动执行）：
  1. 集团节点：不存在时创建，`name=SEED_GROUP_NAME(默认"集团")`、`code=SEED_GROUP_CODE(默认"GROUP")`。
  2. 权限点：按 `permission_registry.py` upsert（code 为键，更新名称/路由/图标/排序/父级）；**本期全部权限点（含 kb/open 的）在 M1 一次写入**，便于前端菜单与角色授权提前联调。
  3. 内置角色：不存在时创建 4 个（见总体方案第 7 节），并按注册表 `default_roles` 授权；已存在则只为**新插入的权限点**补授权。
  4. `admin` 用户：不存在时创建于集团节点，密码 `SEED_ADMIN_PASSWORD`（默认 `Admin12345`），`must_change_password=true`，`is_builtin=true`，授予 `super_admin`。
  5. 执行后 `INCR authz:epoch`。

---

## 5. 接口契约（iam）

> 通用：统一响应、分页、错误码见总体方案第 4 节。除注明外均需登录（`get_auth_context` 全链校验）。

### 5.1 认证

#### 5.1.1 `POST /api/v1/auth/login` — 登录
- 权限码：**public**（登录入口，无凭据）
- 数据范围：不适用
- 请求 body：
  | 字段 | 类型 | 必填 | 规则 |
  |---|---|---|---|
  | username | string | 是 | 1~64 字符（不在此处做格式校验，避免暴露规则） |
  | password | string | 是 | 1~64 字符 |
- 处理顺序：①`auth:lock:{username}` 存在 → 401102；②查用户（未删除）；不存在或密码错 → `INCR auth:fail:{username}`（首次设 EX 900），达到 5 次时写 `auth:lock`（EX 900）并删除计数，返回 401101（第 5 次仍返回 401101，第 6 次起返回 401102）；③用户停用 → 401103（fail_reason=user_disabled）；④组织或任一祖先停用 → 401103（org_disabled）；⑤成功：删除失败计数，建会话，签发令牌，更新 last_login。每个分支写登录日志。
- 响应 data：
  ```json
  {"access_token": "eyJ...", "refresh_token": "rt_3kV...", "token_type": "Bearer",
   "expires_in": 1800, "must_change_password": true}
  ```
- 错误码：
  | code | 触发条件 | message |
  |---|---|---|
  | 401101 | 账号不存在或密码错误 | 账号或密码错误 |
  | 401102 | 处于锁定期 | 账号已锁定，请 {n} 分钟后再试（`data={"remaining_seconds": 812}`，**401102 一定返回 `remaining_seconds`**：整数，取锁定 key 的剩余 TTL，最小为 1；n = ceil(remaining_seconds/60)） |
  | 401103 | 账号停用 / 组织停用 | 账号不可用，请联系管理员 |
- 幂等/并发：前端按钮 loading 防重复提交。
- JWT claims：`iss=kbp-iam`、`sub=str(user_id)`、`sid`、`iat`、`exp`、`typ=access`，RS256。
- refresh_token：`rt_` + 48 字节 urlsafe 随机串，只存 SHA-256。

#### 5.1.2 `POST /api/v1/auth/refresh` — 刷新令牌
- 权限码：**public**（凭刷新令牌，不需要 access_token）
- body：`refresh_token: string`（必填）
- 处理：按哈希查会话，`revoked_at IS NULL` 且 `expires_at > now` 且 Redis 会话存在且用户可用；轮换新的 refresh_token（替换哈希），`expires_at = now + 7d`，续期 Redis TTL；签发新 access_token（同一 sid）。
- 响应 data：同 login（`must_change_password` 为当前值）。
- 错误码：401104 刷新令牌无效或已过期（前端收到后跳登录页）。
- 并发：前端保证同一时刻只发起一次刷新（single-flight）；后端在同一会话行上 `SELECT ... FOR UPDATE`，旧令牌轮换后再用返回 401104。

#### 5.1.3 `POST /api/v1/auth/logout` — 登出
- 权限码：login（允许改密前调用）
- body：无
- 处理：吊销当前 sid（PG `revoked_at`、`revoke_reason=logout`，删 Redis 会话）。
- 响应 data：`null`

#### 5.1.4 `GET /api/v1/auth/me` — 当前用户、权限码、菜单
- 权限码：login（允许改密前调用）
- 响应 data：
  ```json
  {
    "user": {"id": 12, "username": "zhangsan", "name": "张三", "org_id": 5, "org_name": "研发部",
             "company_id": 3, "company_name": "A公司", "mobile": "13800000000", "email": null,
             "must_change_password": false, "is_super_admin": false, "last_login_at": "2026-11-11T09:00:00+08:00"},
    "permissions": ["kb:dataset:list", "kb:dataset:create"],
    "menus": [
      {"code": "kb:dataset:list", "name": "知识库", "path": "/kb/datasets", "icon": "DatabaseOutlined", "sort_order": 1, "children": []},
      {"code": "system:menu:root", "name": "系统管理", "path": "/system", "icon": "SettingOutlined", "sort_order": 9,
       "children": [{"code": "system:user:list", "name": "用户管理", "path": "/system/users", "icon": null, "sort_order": 2, "children": []}]}
    ]
  }
  ```
- 规则：`menus` 只含 `perm_type=menu` 的节点；**叶子菜单**须用户拥有该权限码才出现；**目录节点**（有子菜单的 menu，如 `system:menu:root`、`openapi:menu:root`、`system:log:root`）只要任一子菜单出现就出现，**不要求**拥有目录码；只拥有目录码而无任何子菜单出现时目录不出现；同级按 sort_order 升序。
- 超级管理员：`permissions` 返回**系统全部权限码**（`sys_permission` 中全部 code，与 AuthContext 一致，非空数组），`menus` 返回全部菜单。前端按 `is_super_admin` 放行与按权限码判断结果一致，两种方式都正确。
- `menus[].icon`：取自权限注册表，值为总体方案第 7 节"图标"列（前端白名单内的 `@ant-design/icons` 组件名）；子菜单也有图标（示例中的 null 仅示意，以注册表为准）。

#### 5.1.5 `PUT /api/v1/auth/password` — 修改本人密码
- 权限码：login（允许改密前调用）
- body：
  | 字段 | 类型 | 必填 | 规则 |
  |---|---|---|---|
  | old_password | string | 是 | |
  | new_password | string | 是 | 8~32 位，同时含字母和数字（`^(?=.*[A-Za-z])(?=.*\d).{8,32}$`），不等于旧密码 |
- 处理：校验旧密码 → 更新哈希、`must_change_password=false`、`password_changed_at` → **吊销除当前 sid 外的全部会话**（reason=password_changed）→ 删 `authz:ctx:{uid}`。
- 响应 data：`null`
- 错误码：400101 原密码错误；400102 新密码不符合规则（`data.errors`）；400103 新密码不能与当前密码相同。

### 5.2 组织

组织节点对象 `OrgNode`：
```json
{"id": 5, "parent_id": 3, "name": "研发部", "code": "A-RD", "org_type": "dept",
 "leader_user_id": 21, "leader_name": "李四", "sort_order": 1, "status": "enabled",
 "effective_status": "enabled", "company_id": 3, "version": 2,
 "disable_blocked_reason": null, "delete_blocked_reason": null,
 "created_at": "2026-11-11T10:00:00+08:00", "children": []}
```
`effective_status`：自身或任一祖先停用则为 `disabled`。

`disable_blocked_reason` / `delete_blocked_reason`（仅 5.2.1 组织管理树返回；其他接口可省略）：服务端按 5.2.0 的**保护规则**为当前操作人逐节点计算，`null` 表示不受保护（是否最终成功仍以请求时校验为准，例如删除时的下级/用户/知识库/角色引用检查不在此预判）；非 `null` 时为提示文案（即对应错误码的 message），前端据此把"停用""删除"按钮**置灰并悬停显示该文案**，不得隐藏。节点已停用时 `disable_blocked_reason` 恒为 `null`（启用不受保护）。

#### 5.2.0 组织保护规则（停用 / 删除）

定义（基于操作人当前启用且未删除的角色计算，iam 内部函数 `org_protection.compute(op)`）：

- **无管辖根限制**：操作人为超级管理员，或任一启用角色数据范围为 `ALL`（即 `ctx.data_scope.all`）。此时不计算管辖根。
- **管辖根组织集合 R(op)**：对每个启用角色分别计算后取并集（多角色时每个角色的管辖根都受保护）：

  | 角色数据范围 | 该角色的管辖根 |
  |---|---|
  | `COMPANY_AND_CHILD`、`COMPANY` | 操作人所属公司节点（`op.company_id`；集团本部用户为集团节点） |
  | `DEPT_AND_CHILD`、`DEPT` | 操作人主组织节点（`op.org_id`；直属公司/集团节点的用户即该公司/集团节点） |
  | `CUSTOM` | 该角色勾选的组织中，**祖先链上不含该角色其他勾选组织**的节点（按 `ancestors` 判断，忽略已删除组织） |
  | `SELF`、`ALL` | 无 |

- **本人组织链 P(op)** = `op.org_path`（本人主组织及其全部上级，含集团节点）。

判定顺序与错误码（停用 = `PUT .../status` 且 `status=disabled`；删除 = `DELETE`）：

| 顺序 | 条件 | 适用 | 错误码 / 提示 |
|---|---|---|---|
| 1 | 目标为集团节点 | 停用、删除（及移动） | 400114 集团节点不能移动、停用或删除 |
| 2 | 无管辖根限制不成立，且目标 ∈ R(op) | 停用、删除 | **403102** 不能停用/删除自己管辖范围的根组织，请联系上级管理员 |
| 3 | 目标 ∈ P(op)（**含超级管理员与 ALL 范围管理员**） | 仅停用 | **403103** 不能停用本人所在的组织及其上级组织 |

- 顺序 2 先于 3：例如 A 公司管理员停用 A 公司节点（既是管辖根又是本人上级）返回 403102（与 AC-74 文案一致）。
- 删除本人所在组织链上的节点不在此拦截，由 409103/409104（存在下级/用户）兜底。
- 启用（`status=enabled`）不受保护规则限制。
- 与 AC-74 对照：M（COMPANY_AND_CHILD，A 公司研发部）停用/删除 A 公司 → 403102；停用研发部 → 403103；停用测试部 → 成功；G（ALL，集团财务部）停用 A 公司 → 成功、停用集团财务部 → 403103；S0（集团节点）停用集团节点 → 400114。

#### 5.2.0a SELF 数据范围的只读特例（仅 iam 用户与组织）

用户确认的规则：持有 SELF 范围（`ctx.data_scope.include_self = true`）的用户，在 iam 管理页中额外**只读**可见：
- 用户列表/详情：本人账号（`sys_user.id = ctx.user_id`）；
- 组织树/组织选择器/组织详情：本人组织链（`sys_org.id = ANY(ctx.org_path)`）。

实现位置（不改共享库 `data_scope_filter` 语义）：
- iam `repositories` 层定义两种条件：
  - **管理范围** `manage_filter = data_scope_filter(ctx, ...)`（原规则）；
  - **可见范围** `visible_filter = manage_filter OR (SELF 特例条件)`，仅当 `include_self` 时追加 OR。
- 查询接口（5.2.1、5.2.2、5.2.3、5.3.1、5.3.2、5.4.8）用 `visible_filter`；**所有写接口及其前置校验**（组织新增的上级、编辑、移动（节点、当前上级、新上级）、停用、删除；用户新增的目标组织、编辑（含新组织）、启停、重置密码、分配角色、删除；`roles/assignable` 的 `user_id`/`org_id`；角色 CUSTOM 组织校验）一律用 `manage_filter` / `in_data_scope`。
- 写接口命中"可见但不可管理"的数据 → **403001**（无权限执行该操作），不再返回 404000（数据对其可见，不需要隐藏存在性）；完全不可见的仍 404000。
- 响应标记：`OrgNode`（5.2.1/5.2.3）、组织选择器节点（5.2.2）、`UserItem` 增加 `manageable: bool`（是否在管理范围内）。`manageable=false` 时：`disable_blocked_reason`、`delete_blocked_reason` 为 `null`（不适用）；前端**不显示**该行的全部管理操作（新增下级、编辑、移动、停用/启用、删除、重置密码、分配角色），选择器中该节点不可选（作为用户所属组织、角色 CUSTOM 组织等写入目标时）。
- 5.2.0 保护规则不受影响：保护规则只对 `manageable=true` 的节点计算；只读节点的写请求在保护规则之前即被 403001 拒绝。
- 不影响日志查询、kb/open 的任何数据范围。

#### 5.2.1 `GET /api/v1/system/orgs/tree` — 组织管理树
- 权限码：`system:org:list`；数据范围：按 `sys_org.company_id / dept_id / created_by` 过滤（可见范围含 5.2.0a 特例，节点带 `manageable`）
- query：`name`（可选，模糊）、`status`（可选 enabled/disabled）
- 响应 data：`OrgNode[]`（森林）。父节点不可见的可见节点作为根返回；有 name/status 过滤时返回命中节点及其**可见**祖先。同级按 sort_order、created_at 升序。不分页（≤5000）。

#### 5.2.2 `GET /api/v1/system/orgs/options` — 组织选择器
- 权限码：任一 `system:org:list`、`system:user:list`、`system:role:list`、`system:oplog:list`、`system:loginlog:list`、`kb:admin:list`、`openapi:apikey:audit`
- 数据范围：同 5.2.1（超管 / ALL 返回全部；含 5.2.0a 特例）
- query：`types`（可选，逗号分隔：`group,company,dept`）、`include_disabled`（bool，默认 true）
- 响应 data：`[{"id":1,"parent_id":0,"name":"集团","org_type":"group","status":"enabled","manageable":false,"children":[...]}]`

#### 5.2.3 `GET /api/v1/system/orgs/{id}`
- 权限码 `system:org:list`；范围外 → 404000。响应 `OrgNode`（children 为空数组）。

#### 5.2.4 `POST /api/v1/system/orgs` — 新增
- 权限码：`system:org:create`；数据范围：`parent_id` 对应节点须在范围内，否则 404000
- body：
  | 字段 | 类型 | 必填 | 规则 / 默认 |
  |---|---|---|---|
  | parent_id | int | 是 | 存在且未删除 |
  | org_type | string | 是 | `company` / `dept`（不能新建 group） |
  | name | string | 是 | 1~50 字，去首尾空格 |
  | code | string | 是 | `^[A-Za-z0-9_-]{1,32}$` |
  | leader_user_id | int | 否 | 须为范围内未删除用户 |
  | sort_order | int | 否 | 0~9999，默认 0 |
  | status | string | 否 | 默认 enabled |
- 层级规则：company 的上级只能是 group/company（400111）；dept 的上级可以是 **group**/company/dept（集团节点视为"集团本部"，可直接下设部门，与 PRD F-10 规则 5"集团下的部门"一致，见 TQ-07）；dept 下不能建 company（400110）。不再返回 400001。
- 响应 data：`OrgNode`
- 错误码：400110 部门下不能创建公司；400111 公司的上级只能是集团或公司；409101 同一上级下已存在同名组织；409102 组织编码已存在。
- 副作用：发布 `org.upserted`；写操作日志（org/create）。

#### 5.2.5 `PUT /api/v1/system/orgs/{id}` — 编辑
- 权限码 `system:org:update`；范围内
- body：`name`(必填)、`leader_user_id`(可空)、`sort_order`(必填)、`version`(必填)。code、org_type、parent 不在此接口修改（TQ-02 推荐类型不可改）。
- 错误码：409101、409001。响应 `OrgNode`。

#### 5.2.6 `PUT /api/v1/system/orgs/{id}/move` — 调整上级
- 权限码 `system:org:update`
- body：`parent_id`(必填)、`version`(必填)
- 校验：节点、**节点当前上级**、新上级都须在范围内（子公司管理员的本公司节点其上级不在范围内 → 403101）；不能是集团节点（400114）；新上级不能是自身或后代（400112）；层级规则同新增（400110/400111）；新上级下同名 → 409101。
- 新上级等于当前上级：视为 no-op，校验 version 后直接返回当前 `OrgNode`，不写日志、不发事件、不 bump epoch。
- 处理（单事务）：更新自身 parent_id/ancestors；批量更新所有后代 ancestors；重算自身与后代的 `company_id`；重算这些组织下用户的 `company_id`；提交后 `INCR authz:epoch`，对每个受影响的组织和用户发布 `org.upserted`/`user.upserted`。
- 错误码：403101 不能调整本公司节点的上级；400112；400114 集团节点不能移动、停用或删除。

#### 5.2.7 `PUT /api/v1/system/orgs/{id}/status`
- 权限码 `system:org:update`；body：`status`、`version`。集团节点 → 400114。
- 停用时按 5.2.0 保护规则校验（400114 / 403102 / 403103）；启用不受限制。
- 状态与当前相同：no-op，直接返回，不写日志。
- 停用：提交后 `INCR authz:epoch`（ctx.org_enabled 重算）；**并吊销该组织子树下所有用户的会话**（F-02 规则 4 + F-01 规则 3，使其立即无法使用）。启用不恢复会话。

#### 5.2.8 `DELETE /api/v1/system/orgs/{id}`
- 权限码 `system:org:delete`；按 5.2.0 保护规则校验（400114 / 403102；403103 不适用于删除）。
- 检查顺序：存在未删除下级组织 → 409103；存在未删除用户（org_id=该节点）→ 409104；存在归属该公司的未删除公司级角色（`sys_role.owner_company_id = 该节点`）→ 409106（`data={"roles":["角色名",...最多10个],"total":n}`）；调 kb `GET /internal/v1/stats/datasets?dept_id={id}` 计数>0 → 409105（kb 未部署时（M1）配置项 `KB_STATS_ENABLED=false` 跳过；已启用但调用失败 → 503001）。
- 通过检查后（单事务）：逻辑删除；**物理删除 `sys_role_org` 中引用该组织的行**（CUSTOM 范围自动收窄，方向安全；若某 CUSTOM 角色因此无任何组织，其数据范围解析为空集，即什么都看不到）；有引用被移除时 `INCR authz:epoch`，操作日志 summary 记录 `{"before": {...}, "custom_role_refs_removed": ["角色名", ...]}`；发布 `org.upserted(is_deleted=true)`。

### 5.3 用户

用户对象 `UserItem`：
```json
{"id": 21, "username": "lisi", "name": "李四", "org_id": 5, "org_name": "研发部",
 "company_id": 3, "company_name": "A公司", "roles": [{"id": 4, "name": "普通员工"}],
 "mobile": "13800000001", "email": "lisi@example.com", "status": "enabled",
 "is_builtin": false, "must_change_password": true, "last_login_at": null,
 "created_at": "2026-11-11T10:00:00+08:00", "version": 1, "manageable": true}
```
`manageable`：是否在操作人管理范围内（5.2.0a）；SELF 用户看到的本人账号可能为 `false`。

#### 5.3.1 `GET /api/v1/system/users`
- 权限码 `system:user:list`；数据范围：`sys_user.company_id / dept_id / created_by`（可见范围含 5.2.0a 本人账号特例）
- query：`page`、`page_size`、`org_id`（含下级）、`username`（模糊）、`name`（模糊）、`mobile`（模糊）、`status`
- 排序：created_at desc
- 响应：分页 `UserItem`

#### 5.3.2 `GET /api/v1/system/users/{id}` — `UserItem`；可见范围外 404000（含 5.2.0a 特例）

#### 5.3.3 `POST /api/v1/system/users`
- 权限码 `system:user:create`；`org_id` 对应组织须在范围内（404000）
- body：
  | 字段 | 类型 | 必填 | 规则 |
  |---|---|---|---|
  | username | string | 是 | `^[A-Za-z][A-Za-z0-9_]{3,31}$` |
  | name | string | 是 | 1~30 字 |
  | org_id | int | 是 | 集团/公司/部门节点 |
  | mobile | string | 否 | `^1\d{10}$` |
  | email | string | 否 | Email 格式，≤100 |
  | password | string | 否 | 不传则系统生成 12 位字母+数字；传则按密码规则校验 |
  | role_ids | int[] | 否 | **允许创建时直接分配角色**（单独需要 `system:user:create`，不要求 `system:user:assign`）；每个须对目标组织"可分配"（5.4.2 `org_id` 场景规则），否则 403121；操作日志 user/create 的摘要中记录角色名 |
  | status | string | 否 | 默认 enabled |
- 响应 data：`{"user": UserItem, "initial_password": "Ab3kd9Lm2pQx"}`（仅系统生成时返回明文，否则 `null`）
- 错误码：409111 账号已存在；409112 手机号已被使用；403121。
- 日志摘要中不出现密码。

#### 5.3.4 `PUT /api/v1/system/users/{id}`
- 权限码 `system:user:update`；body：`name`、`org_id`、`mobile`、`email`、`version`（全部必填，mobile/email 可为 null）
- 改组织：新组织须在范围内；重算 company_id/dept_id；删 `authz:ctx`；发布 `user.upserted`。用户此前创建的数据归属不变。

#### 5.3.5 `PUT /api/v1/system/users/{id}/status`
- 权限码 `system:user:status`；body：`status`、`version`
- 不能停用自己（403111）；`is_builtin` 用户不能停用（403112）。
- 停用：吊销全部会话（user_disabled）、删 ctx、发布事件。
- 状态与当前相同：no-op（仍校验 version），直接返回，不写日志、不吊销会话。

#### 5.3.6 `POST /api/v1/system/users/{id}/reset-password`
- 权限码 `system:user:reset_pwd`；body：`password`（可选，同规则）
- 处理：`must_change_password=true`，吊销全部会话（password_reset），删 ctx。
- 不需要也不递增 `version`（`version` 只用于资料编辑与状态变更的并发控制；重置密码以最后一次为准）。不发布 `user.upserted`（只读副本不含密码相关字段）。
- 响应 data：`{"password": "Xy7..."}`（系统生成时返回，否则 null）

#### 5.3.7 `PUT /api/v1/system/users/{id}/roles`
- 权限码 `system:user:assign`；body：`role_ids: int[]`（可为空数组）、`confirm_self_lockout: bool = false`
- 不递增用户 `version`，不发布 `user.upserted`（`UserRef` 不含角色；权限变化通过删除 `authz:ctx` 即时生效）。
- 规则：提交集合中每个角色须对该用户"可分配"（403121）；最终集合 = 用户现有角色中**操作人不可管理的** ∪ 提交集合；操作人修改自己导致失去 `system:role:list` 或 `system:user:list` 且未确认 → 409124（`data={"lost_permissions":["system:user:list"]}`）。
- 删 ctx；操作日志 summary `{"before":[角色名], "after":[角色名]}`。

#### 5.3.8 `DELETE /api/v1/system/users/{id}`
- 权限码 `system:user:delete`；不能删除自己（403111）、`is_builtin`（403112）
- 逻辑删除；吊销会话；删 ctx；发布事件。

#### 5.3.9 `GET /api/v1/system/users/{id}/impact` — 停用/删除前的影响提示
- 权限码 `system:user:list`；范围内
- 处理：并发调用 kb `GET /internal/v1/stats/datasets?owner_id=` 与 open `GET /internal/v1/stats/api-keys?user_id=`；下游未启用或失败时对应字段为 null，`degraded=true`
- 响应 data：`{"owned_dataset_count": 2, "api_key_count": 1, "degraded": false}`
- 前端文案：`该用户拥有 {owned_dataset_count} 个知识库，请及时转移；其 API 密钥将失效`（degraded 时显示"知识库数量暂无法获取"）。

### 5.4 角色与权限

#### 5.4.0 规则定义（后端实现必须一致）
- **可管理公司集合 M(op)**：超管或 data_scope.all → 全部；否则 = `op.data_scope.company_ids`。
- **角色可见**：集团级角色对所有拥有 `system:role:list` 的人可见；公司级角色当 `owner_company_id ∈ M(op)` 时可见。不可见 → 404000。
- **角色可编辑**（`editable`）：非 super_admin；集团级角色要求 op 为超管或 data_scope.all；公司级要求 `owner_company_id ∈ M(op)`。
- **数据范围等级**：SELF=1 < DEPT=2 < DEPT_AND_CHILD=3 < COMPANY=4 < COMPANY_AND_CHILD=5 < ALL=6；`max_rank(op)` = op 所有启用角色中非 CUSTOM 范围的最大等级。设置非 CUSTOM 范围 s 需 `rank(s) ≤ max_rank(op)`；设置 CUSTOM 需每个组织都在 op 的数据范围内（`in_data_scope`，按组织的 company_id/dept_id）。超管不受限。
- **授权上限**：提交的 permission_ids ⊆ op.permissions（超管不受限）。保存时最终集合 = 角色现有权限中 op **不拥有的** ∪ 提交集合（这些节点前端置灰保留）。
- **角色对用户可分配**：角色可见且启用；角色权限 ⊆ op.permissions；角色数据范围满足上一条；公司级角色要求目标用户 `company_id`（新建场景为目标组织的 `company_id`）在 `owner_company_id` 及其下属公司内；`super_admin` 只有超管可分配。

角色对象 `RoleItem`：
```json
{"id": 9, "code": "a_cs", "name": "A-客服", "role_type": "company", "owner_company_id": 3,
 "owner_company_name": "A公司", "data_scope": "DEPT", "status": "enabled", "remark": null,
 "is_builtin": false, "builtin_key": null, "user_count": 12, "editable": true,
 "created_at": "2026-11-11T10:00:00+08:00", "version": 3}
```

#### 5.4.1 `GET /api/v1/system/roles`
- 权限码 `system:role:list`；按可见规则
- query：`page`、`page_size`、`name`、`code`、`role_type`、`status`、`owner_company_id`
- 响应：分页 `RoleItem`（`user_count` 只统计未删除用户）

#### 5.4.2 `GET /api/v1/system/roles/assignable` — 可分配角色
- 权限码：任一 `system:user:assign`、`system:user:create`
- query（`user_id` 与 `org_id` **二选一**，都不传或都传 → 400001）：
  | 字段 | 类型 | 说明 |
  |---|---|---|
  | user_id | int | 已有用户（分配角色场景）；须在 op 用户数据范围内，否则 404000；调用者须有 `system:user:assign` |
  | org_id | int | 新建用户场景的目标组织；须在 op 数据范围内，否则 404000；调用者须有 `system:user:create` |
- 判定：按 5.4.0"角色对用户可分配"，其中"目标用户所属公司"在 `org_id` 场景下取该组织的 `company_id`。
- 响应 data：`[{"id":4,"name":"普通员工","code":"employee","role_type":"group","data_scope":"SELF","assigned":true}]`（只返回可分配角色；`assigned` 表示用户已持有，`org_id` 场景恒为 false）
- 前端：新增用户表单在选定所属组织后用 `org_id` 拉取；组织变更时清空已选角色并重新拉取。

#### 5.4.3 `GET /api/v1/system/roles/{id}`
- 响应：`RoleItem` + `"permission_ids": [..], "custom_org_ids": [..]`

#### 5.4.4 `POST /api/v1/system/roles`
- 权限码 `system:role:create`
- body：
  | 字段 | 类型 | 必填 | 规则 |
  |---|---|---|---|
  | code | string | 是 | `^[A-Za-z0-9_]{2,50}$` |
  | name | string | 是 | 1~30 字 |
  | role_type | string | 是 | `group`（要求 op 超管或 ALL，否则 403125）/ `company` |
  | owner_company_id | int | company 时必填 | 须 ∈ M(op)，且为 company/group 节点 |
  | data_scope | string | 否 | 默认 SELF，受等级约束 |
  | custom_org_ids | int[] | CUSTOM 时必填 ≥1 | |
  | status | string | 否 | 默认 enabled |
  | remark | string | 否 | ≤200 |
- 新建角色无功能权限，通过 5.4.6 授权。
- 数据范围：`data_scope`、`custom_org_ids` 在创建接口中为**可选**字段（不传即 SELF、空集合）。前端可以在新增表单中展示数据范围，也可以不展示、创建后在"分配权限"抽屉（5.4.6）中设置，两种方式都符合契约；本期前端采用后者（新增表单不含数据范围，与 PRD"角色属性含数据范围"不冲突——数据范围仍是角色属性，只是在授权抽屉维护）。后端保留这两个可选字段，校验规则不变。
- 错误码：409121 角色编码已存在；409122 角色名称已存在；400121 CUSTOM 须选择组织；400122 公司级角色须指定所属公司；403124 数据范围超出您的数据范围；403125 无权维护集团级角色。

#### 5.4.5 `PUT /api/v1/system/roles/{id}`
- 权限码 `system:role:update`；要求 editable（否则 403125 或 404000）
- body：`name`、`status`、`remark`、`version`、`confirm_self_lockout`(默认 false)
- `super_admin` → 403122。停用角色：`INCR authz:epoch`；若操作人自身因此失去 `system:role:list` 且未确认 → 409124。

#### 5.4.6 `PUT /api/v1/system/roles/{id}/grants` — 分配权限与数据范围
- 权限码 `system:role:grant`；要求 editable
- body：`permission_ids: int[]`、`data_scope`、`custom_org_ids: int[]`、`version`、`confirm_self_lockout: bool=false`
- 校验：授权上限（403123，`data={"forbidden_codes":[...]}`）；数据范围（403124）；CUSTOM（400121）；自锁（409124）。
- 处理：替换关联；`INCR authz:epoch`；操作日志 summary：`{"permissions":{"added":[codes],"removed":[codes]},"data_scope":{"before":"DEPT","after":"COMPANY"}}`。

#### 5.4.7 `DELETE /api/v1/system/roles/{id}`
- 权限码 `system:role:delete`；内置 → 403122；有关联未删除用户 → 409123（`data={"user_count": 3}`）

#### 5.4.8 `GET /api/v1/system/roles/{id}/users`
- 权限码 `system:role:list`；角色可见；用户列表再按 op 用户数据范围过滤；分页 `UserItem`（roles 字段可省略为空数组）

#### 5.4.9 `GET /api/v1/system/permissions/tree`
- 权限码 `system:role:list`
- 响应 data：
  ```json
  {"tree": [{"id": 1, "code": "kb:dataset:list", "name": "知识库", "perm_type": "menu", "grantable": true, "children": []}],
   "max_data_scope": "COMPANY_AND_CHILD", "can_custom": true}
  ```
  `grantable` = op 拥有该权限（超管全 true）；`max_data_scope` = 5.4.0 的 `max_rank(op)` 对应值（超管为 `ALL`；仅有 CUSTOM 角色时为 `SELF`）；`can_custom` = op 可设置 CUSTOM（超管/ALL/拥有任何非空数据范围时为 true，具体组织仍由后端逐个校验）。前端据此置灰权限节点与数据范围选项。

### 5.5 日志

#### 5.5.1 `GET /api/v1/system/operation-logs`
- 权限码 `system:oplog:list`；数据范围：`company_id / dept_id / created_by(operator_id)`
- query：`page`、`page_size`、`start_time`（必填）、`end_time`（必填，跨度 ≤180 天，否则 400001）、`operator`（模糊匹配姓名或账号）、`module`、`action`、`result`
- 排序 occurred_at desc
- 响应 items：
  ```json
  {"id": 101, "occurred_at": "2026-11-11T10:00:00+08:00", "operator_id": 2, "operator_username": "admin_a",
   "operator_name": "王管理", "company_name": "A公司", "module": "user", "action": "reset_password",
   "target_type": "user", "target_id": "21", "target_name": "lisi(李四)", "result": "success",
   "error_message": null, "ip": "10.0.0.8", "service": "iam"}
  ```

#### 5.5.2 `GET /api/v1/system/operation-logs/{id}`
- 同上权限与范围；响应：列表字段 + `summary`、`user_agent`、`request_id`

#### 5.5.3 `GET /api/v1/system/login-logs`
- 权限码 `system:loginlog:list`；数据范围同上（company_id 为空的记录仅 `all`/超管可见）
- query：`page`、`page_size`、`start_time`、`end_time`（同上约束）、`username`（模糊）、`result`、`ip`
- 响应 items：`{"id","login_at","username","user_id","user_name","company_name","result","fail_reason","fail_message","ip","user_agent"}`

### 5.6 内部接口（`require_internal`）

#### 5.6.1 `GET /internal/v1/authz/contexts/{user_id}`
- 计算 AuthContext（结构见总体方案 3.5.1），写入 `authz:ctx:{user_id}`（TTL 600s，epoch = 当前值），返回 data = AuthContext。
- 用户不存在（含物理不存在）→ 404000；已删除用户返回 `is_deleted=true`、`permissions=[]`。
- 计算规则：
  - 角色：仅 `status=enabled` 且未删除；`is_super_admin` = 持有启用的 super_admin 角色。
  - permissions：角色权限并集（超管 = 全部权限码）。
  - org_enabled：主组织及全部祖先 status=enabled 且未删除。
  - data_scope：见总体方案 3.6。

#### 5.6.2 `POST /internal/v1/authz/contexts/batch`
- body：`{"user_ids": [1, 2]}`（≤200）；data：`{"items": {"1": AuthContext, "2": null}}`

#### 5.6.3 `GET /internal/v1/sync/users`
- query：`updated_after`（ISO，可选）、`after_id`（int ≥0，默认 0）、`limit`（1~1000，默认 500）；含已删除
- 游标条件：`updated_at > :updated_after OR (updated_at = :updated_after AND id > :after_id)`；**未传 `updated_after` 时从头开始、忽略 `after_id`**（首次全量拉取）；后续一律使用上一页返回的 `next` 原样传回
- 排序 `(updated_at, id)`；data：`{"items":[UserRef], "next": {"updated_after": "...", "after_id": 123} | null}`
- `UserRef`：`{"id","username","name","status","is_deleted","org_id","company_id","updated_at"}`

#### 5.6.4 `GET /internal/v1/sync/orgs`
- 同上；`OrgRef`：`{"id","parent_id","ancestors","org_type","name","code","status","is_deleted","company_id","sort_order","updated_at"}`

### 5.7 事件（iam 发布到 `stream:iam.events`）

| type | 触发 | payload |
|---|---|---|
| `user.upserted` | 用户新增/编辑/停用/启用/删除、组织移动导致 company_id 变化 | `UserRef` |
| `org.upserted` | 组织新增/编辑/移动/停用/删除（移动时子树每个节点各一条） | `OrgRef` |

消费方按 `updated_at` 比较，只应用更新的数据（幂等）。

### 5.8 操作日志枚举（全平台）

| module | action | 说明 | 产生服务 |
|---|---|---|---|
| `user` | `create` `update` `status` `reset_password` `assign_role` `delete` | | iam |
| `role` | `create` `update` `grant` `delete` | grant 的 summary 含权限与数据范围前后值 | iam |
| `org` | `create` `update` `move` `status` `delete` | | iam |
| `model` | `create` `update` `status` `set_default` `delete` | | kb |
| `dataset` | `create` `update` `delete` `assign_create` `assign_update` `assign_delete` `transfer` `retrieval_config` `admin_view` | | kb |
| `document` | `upload` `delete` `reprocess` | | kb |
| `api_key` | `create` `update` `status` `regenerate` `delete` `admin_disable` `admin_delete` | | open |

`result`：`success` / `failure`。

`summary` 结构约定：
| 操作类型 | 结构 |
|---|---|
| 新建（create、upload 等） | `{"after": {...}}`（无 before） |
| 删除（delete、admin_delete） | `{"before": {...}}`（无 after）；组织删除另含 `custom_role_refs_removed` |
| 编辑/状态/移动等 | `{"before": {...}, "after": {...}}`，只含变化的关键字段 |
| 授权（role/grant） | `{"permissions": {"added": [...], "removed": [...]}, "data_scope": {"before": ..., "after": ...}, "custom_orgs": {"added": [...], "removed": [...]}}` |
| 分配角色（user/assign_role） | `{"before": [角色名], "after": [角色名]}` |
| 审计查看（dataset/admin_view） | `{"document_name": "..."}`（进入知识库详情时为 `{}`） |
前端遇到未知结构时以 JSON 展示。

### 5.9 iam 专属错误码汇总

| code | message |
|---|---|
| 401101 | 账号或密码错误 |
| 401102 | 账号已锁定，请 {n} 分钟后再试 |
| 401103 | 账号不可用，请联系管理员 |
| 401104 | 登录已过期，请重新登录（刷新令牌无效） |
| 400101 | 原密码错误 |
| 400102 | 新密码不符合规则 |
| 400103 | 新密码不能与当前密码相同 |
| 400110 | 部门下不能创建公司 |
| 400111 | 公司的上级只能是集团或公司 |
| 400112 | 不能移动到自身或下级组织之下 |
| 400114 | 集团节点不能移动、停用或删除 |
| 400120 | 用户只能归属集团、公司或部门节点 |
| 400121 | 自定义数据范围必须至少选择一个组织 |
| 400122 | 公司级角色必须指定所属公司 |
| 403101 | 不能调整本公司节点的上级 |
| 403102 | 不能停用/删除自己管辖范围的根组织，请联系上级管理员 |
| 403103 | 不能停用本人所在的组织及其上级组织 |
| 403111 | 不能停用或删除自己 |
| 403112 | 不能停用或删除内置管理员账号 |
| 403121 | 所选角色超出您的授权范围 |
| 403122 | 内置角色不能删除（超级管理员角色不能修改） |
| 403123 | 授予的权限超出您拥有的权限 |
| 403124 | 数据范围超出您的数据范围 |
| 403125 | 无权维护该角色 |
| 409101 | 同一上级下已存在同名组织 |
| 409102 | 组织编码已存在 |
| 409103 | 存在下级组织，不能删除 |
| 409104 | 组织下存在用户，不能删除 |
| 409105 | 组织下存在知识库，不能删除 |
| 409106 | 存在归属该公司的角色，不能删除 |
| 409111 | 账号已存在 |
| 409112 | 手机号已被使用 |
| 409121 | 角色编码已存在 |
| 409122 | 角色名称已存在 |
| 409123 | 角色仍有关联用户，不能删除 |
| 409124 | 保存后您将失去该页面权限（需确认） |

---

## 6. 权限设计

见总体方案第 7 节（全部权限码在 M1 seed 一次写入）。M1 实际生效的接口权限：`system:org:*`、`system:user:*`、`system:role:*`、`system:oplog:list`、`system:loginlog:list`。

前端路由与权限码映射（FE-04 路由表的唯一依据）：

| 路由 | 页面 | 进入所需权限码 | 里程碑 |
|---|---|---|---|
| `/login` | 登录 | 无 | M1 |
| `/change-password` | 强制/主动改密 | 登录 | M1 |
| `/profile` | 个人中心 | 登录 | M1 |
| `/403`、`/404` | | 无 | M1 |
| `/` | 重定向到第一个有权限的菜单 | 登录 | M1 |
| `/system/orgs` | 组织管理 | system:org:list | M1 |
| `/system/users` | 用户管理 | system:user:list | M1 |
| `/system/roles` | 角色管理 | system:role:list | M1 |
| `/system/logs/operation` | 操作日志 | system:oplog:list | M1 |
| `/system/logs/login` | 登录日志 | system:loginlog:list | M1 |
| `/system/models` | 模型配置 | system:model:list | M2 |
| `/kb/datasets` 及 `/kb/datasets/:id/*` | 知识库 | kb:dataset:list | M2 |
| `/system/datasets`、`/system/datasets/:id` | 知识库管理 | kb:admin:list（详情需 kb:admin:view） | M2 |
| `/openapi/keys` `/openapi/logs` `/openapi/docs` | 开放平台 | 对应菜单码 | M3 |
| `/system/api-keys` | API 密钥审计 | openapi:apikey:audit | M3 |

## 7. 后端任务清单

### BE-01（基础设施）工程脚手架与本地编排 — 共享
- 文件：`docker-compose.yml`、`deploy/local/postgres-init.sql`、`backend/requirements.txt`、`backend/requirements-dev.txt`、`backend/pyproject.toml`、`backend/scripts/devctl.py`、`backend/libs/platform_common/pyproject.toml`、`backend/libs/platform_common/platform_common/__init__.py`
- 内容：
  1. compose 按 3.3（4 个服务，数据卷在 `.docker-data/`）。
  2. requirements：fastapi、uvicorn[standard]、pydantic、pydantic-settings、sqlalchemy[asyncio]、asyncpg、alembic、redis、httpx、pyjwt[crypto]、cryptography、bcrypt、python-multipart、**aioboto3（带入 boto3，devctl 建桶使用；提前在 M1 加入）**（M2 再追加其余 kb 依赖）；dev：pytest、pytest-asyncio、ruff、mypy、types-* 必要存根。**全部固定版本**。
  3. `pyproject.toml`：ruff（line-length 120、target py312、规则集 E/F/I/B/UP/ASYNC）、mypy（strict，plugins pydantic.mypy）、pytest（asyncio_mode=auto）。
  4. devctl 按 3.4 实现（标准库 + cryptography + boto3）。
- 完成标准：`docker compose up -d` 后 3 个中间件 healthy（宿主机端口 15432/16379/19000/19001），`kbp`/`kbp_test` 库存在且 `vector` 扩展已装；`devctl.py init` 后两个桶存在且重复执行无报错；`pip install -r ... && pip install -e backend/libs/platform_common` 成功；`devctl.py init` 生成密钥；`devctl.py status` 可运行（无服务时显示未启动）；`ruff check backend` 通过。

### BE-02（共享库）基础能力 — platform_common
- 文件：`platform_common/{config,db,redis,errors,response,pagination,logging,app_factory,client_ip,http_client,crypto,jobs}.py`、`libs/platform_common/tests/test_*.py`
- 内容：按 3.2 实现。`create_app` 负责：请求 ID 中间件、访问日志、`BizError`/`RequestValidationError`(→400001)/`HTTPException`/未知异常(→500000，记录堆栈不返回)处理器、`/healthz`、`/readyz`（DB `SELECT 1` + Redis `PING`）、lifespan 钩子注册（用于启动后台消费者）。`db.py` 的 `get_db` 依赖：每请求一个 `AsyncSession`，由 service 层控制 `commit`。`response.ok(data)` / `response.page(items,total,page,page_size)`。`InternalClient.get/post` 将连接错误/超时/5xx 映射为 `BizError(503001)`，4xx 透传为对应 BizError。
- 完成标准：单测覆盖异常处理器的 4 类映射、分页参数边界（page=0、page_size=101 → 400001）、`get_client_ip` 可信代理逻辑；mypy/ruff 通过。

### BE-03（共享库）鉴权、数据权限、事件、操作日志 — platform_common
- 文件：`platform_common/auth/{jwt,context,deps,data_scope,internal,cache_keys}.py`、`platform_common/events/{streams,publisher,consumer}.py`、`platform_common/oplog.py`、对应 tests
- 内容：按 3.2 契约实现；`get_auth_context` 严格按总体方案 3.5.1 的 6 步，Redis 单次 `MGET`；`data_scope_filter` 与 `in_data_scope` 逻辑一致；`StreamConsumer` 支持优雅停止。
- 完成标准：单测：伪造签名/过期 → 401001；会话不存在 → 401002；ctx epoch 不一致触发回源（mock iam）；must_change 白名单；`require_perm` any/all；`data_scope_filter` 对 7 种范围组合生成的 SQL（编译后断言）与 AC-17 样本一致；consumer 重试与死信；`emit_oplog` 在 Redis 不可用时不抛异常。

### BE-04（iam）模型、迁移、Seed、服务骨架
- 文件：`services/iam/main.py`、`app/core/{config,constants,security}.py`、`app/models/*.py`、`alembic.ini`、`alembic/env.py`、`alembic/versions/0001_init_iam.py`、`app/seed/{__main__,permission_registry,builtin}.py`、`.env.example`、`app/api/v1/__init__.py`
- 内容：第 4 节全部表；`config.py` 增加 `PORT=8301`、`JWT_PRIVATE_KEY_FILE`、`ACCESS_TOKEN_EXPIRE_MINUTES=30`、`REFRESH_TOKEN_EXPIRE_DAYS=7`、`LOGIN_MAX_FAILURES=5`、`LOGIN_FAIL_WINDOW_SECONDS=900`、`LOGIN_LOCK_SECONDS=900`、`SEED_ADMIN_PASSWORD`、`SEED_GROUP_NAME`、`SEED_GROUP_CODE`、`LOG_RETENTION_DAYS=180`、`KB_STATS_ENABLED=false`、`OPEN_STATS_ENABLED=false`；`security.py` 提供 `sign_access_token`、`hash_password`、`verify_password`、`generate_password`、`validate_password_rule`；权限注册表包含总体方案第 7 节**全部**权限码（含父子关系、路由、图标、排序、default_roles）；seed 按 4.11。
- 完成标准：`alembic upgrade head` / `downgrade base` / 再 upgrade 均成功；seed 连续执行两次结果一致；`python main.py` 启动，`/healthz`、`/docs` 正常。

### BE-05（iam）认证与会话 — F-01
- 文件：`app/api/v1/auth.py`、`app/schemas/auth.py`、`app/services/{auth_service,session_service}.py`、`app/repositories/{session_repo,log_repo}.py`（登录日志写入部分）、tests
- 内容：5.1 全部接口；会话写 PG + Redis（`auth:sess`、`auth:user_sess`）；`session_service.revoke_all(user_id, reason, except_sid=None)` 供其它 service 调用；登录日志写入（同步写，失败只记运行日志）。
- 完成标准：AC-01~AC-06 对应单测：锁定第 6 次、不存在账号同提示、停用账号/停用上级组织、刷新轮换与旧令牌失效、改密后其他会话 401002 而当前会话可用、重置后全部会话失效、must_change 时访问其他接口 403002。

### BE-06（iam）权限上下文、内部接口、事件发布 — F-04/F-05
- 文件：`app/services/{authz_service,event_service}.py`、`app/api/internal/{authz,sync}.py`、`app/repositories/{permission_repo}.py`（菜单/权限查询）、tests
- 内容：AuthContext 计算（5.6.1 规则 + 总体 3.6）、缓存写入；`invalidate_user(user_id)`、`bump_epoch()` 工具（**事务提交后执行**）；5.6 四个内部接口；`event_service` 封装 `user.upserted` / `org.upserted` 发布（`publish_after_commit`）；`/auth/me` 的菜单树组装函数。
- 完成标准：单测覆盖 7 种数据范围解析（含"直属公司节点"的 DEPT/DEPT_AND_CHILD、集团本部用户的 COMPANY_AND_CHILD）、多角色并集、停用角色不计入、组织停用 → usable=false；sync 接口游标分页正确。

### BE-07（iam）组织管理 — F-02
- 文件：`app/api/v1/orgs.py`、`app/schemas/org.py`、`app/services/org_service.py`、`app/repositories/org_repo.py`、`app/services/downstream.py`（kb/open 统计调用，含开关与降级）、tests
- 内容：5.2 全部接口；移动时子树 ancestors/company_id、用户 company_id 批量重算（单事务）；停用时吊销子树用户会话；操作日志；事件发布。
- **约束**：所有对 `sys_org`、`sys_user` 的批量 `UPDATE`（`update()` 语句、bulk 更新，不经 ORM 实例的 onupdate）**必须显式设置 `updated_at = now()`（及 `updated_by`）**，否则 sync 游标与对账会漏行、只读副本不更新；单测需断言移动后子树组织与受影响用户的 `updated_at` 均已变化。
- SELF 只读特例：按 5.2.0a 区分 `visible_filter`/`manage_filter`，输出 `manageable`；只读节点写请求 → 403001。
- 保护规则：实现 5.2.0（`org_protection.compute(op)` 同时供 5.2.1 计算 `disable_blocked_reason`/`delete_blocked_reason` 与 5.2.7/5.2.8 校验，保证一致）。
- 完成标准：AC-07~AC-09、**AC-74** 单测（含 CUSTOM 多勾选节点的管辖根、多角色并集、超管/ALL 不受管辖根限制但受本人组织链限制）；子公司管理员越权（B 公司节点 → 404000、移动本公司 → 403101）；并发编辑 version 冲突 409001。

### BE-08（iam）用户管理 — F-03
- 文件：`app/api/v1/users.py`、`app/schemas/user.py`、`app/services/user_service.py`、`app/repositories/user_repo.py`、tests
- 内容：5.3 全部接口；组织树筛选（含下级）；与 BE-09 共用"角色可分配"判定（放 `role_service.assignable_roles_for(op, user)`，若 BE-09 未完成，本任务先实现该函数并由 BE-09 复用）。
- SELF 只读特例：用户列表/详情按 5.2.0a 可见本人账号，`manageable` 按管理范围计算；写接口与 `roles/assignable` 只用管理范围。
- **约束**：同 BE-07——对 `sys_user` 的批量 `UPDATE` 必须显式设置 `updated_at`、`updated_by`；任何修改 `sys_user` 的路径都要发布 `user.upserted`。
- 完成标准：AC-10~AC-12 单测；跨公司 ID 直访 404000 且数据无变化；停用/删除/重置后会话失效；初始密码只返回一次且操作日志无明文。

### BE-09（iam）角色与权限 — F-04/F-05
- 文件：`app/api/v1/{roles,permissions}.py`、`app/schemas/{role,permission}.py`、`app/services/role_service.py`、`app/repositories/role_repo.py`、tests
- 内容：5.4 全部接口与 5.4.0 规则；变更后 `bump_epoch`；自锁确认。
- 完成标准：AC-13~AC-16 单测；授权上限（权限、数据范围、CUSTOM 组织越界）；公司级角色跨公司不可见、不可分配；内置角色不可删。

### BE-10（iam）日志汇聚与查询、保留期清理 — F-06
- 文件：`app/api/v1/logs.py`、`app/schemas/log.py`、`app/services/log_service.py`、`app/repositories/log_repo.py`、`app/jobs/{oplog_consumer,log_cleanup}.py`、`main.py`（lifespan 中启动消费者与清理任务）、tests
- 内容：`StreamConsumer(stream:oplog, group=iam-oplog)` 入库（`event_id` 唯一，冲突忽略；入库时补 `company_name`）；iam 自身操作同样通过 `emit_oplog` 走 Stream（保持一条路径）；5.5 三个接口；每日 03:00（每小时检查一次，`run_periodic` 单实例）分批删除 180 天前的登录/操作日志（每批 5000）。
- 完成标准：AC-20、AC-21 单测；重复事件只入库一次；Redis 断开时业务操作仍成功；日志接口无修改/删除路由。

## 8. 前端任务清单

### FE-01 前端工程骨架
- 文件：`frontend/package.json`、`vite.config.ts`、`tsconfig*.json`、`.eslintrc`/`eslint.config.js`、`.prettierrc`、`index.html`、`src/main.tsx`、`src/App.tsx`、`src/theme.ts`、`scripts/gen-api.mjs`
- 前置：pnpm 已安装（主会话处理）。
- 内容：React 18 + TS + Vite；依赖按基线（antd 5、@ant-design/icons、@ant-design/pro-components、react-router-dom 6、@tanstack/react-query、axios、zustand、dayjs、lodash-es；dev：vitest、@testing-library/react、openapi-typescript、eslint、prettier）；dev server 端口 **5174**（`strictPort: true`）；`vite.config.ts` 的 proxy：`/api/v1/auth`、`/api/v1/system` → `http://127.0.0.1:8301`；`/api/v1/kb` → `http://127.0.0.1:8302`；`/api/v1/open-platform`、`/api/v1/open` → `http://127.0.0.1:8303`；`pnpm gen:api` 拉取 `http://127.0.0.1:{8301,8302,8303}/openapi.json`；`pnpm gen:api` 依次拉取三个服务的 `/openapi.json` 生成 `src/services/types/{iam,kb,open}.d.ts`（服务未启动则跳过并提示）；ConfigProvider 中文 locale + 主题 token；dayjs 中文。
- 完成标准：`pnpm tsc --noEmit`、`pnpm lint`、`pnpm build` 通过，`pnpm dev` 打开空白首页。

### FE-02 请求层、认证状态、权限基础 — F-01、F-04
- 文件：`src/api/request.ts`、`src/api/tokenStore.ts`、`src/stores/auth.ts`、`src/access/{usePermission.ts,Access.tsx}`、`src/router/{guards.tsx,routes.tsx(骨架)}`、`src/services/iam.ts`（auth 部分）、`src/utils/{error.ts,format.ts}`
- 使用接口：5.1.2 refresh、5.1.4 me、5.1.3 logout
- 内容：axios 实例：注入 `Authorization: Bearer`；响应 `code !== 0` 转为统一错误对象（含 code、message、data）；**401001 → single-flight 刷新**（刷新期间其他请求排队，成功重放，失败清空并跳 `/login?redirect=当前地址`）；401002/401104 → 直接跳登录；403002 → 跳 `/change-password`；其他错误默认 `message.error`，调用方可关闭。token 存 localStorage（access + refresh）。Zustand `auth` store：user、permissions(Set)、menus、`loadMe()`、`logout()`。`usePermission(code | codes, mode)`、`<Access code>`。路由守卫：未登录跳登录；`must_change_password` 只允许 `/change-password`；路由 meta.perm 不满足 → 403 页。
- 完成标准：Vitest 覆盖刷新排队（并发 3 个 401 只刷新一次）、错误码分流、usePermission。

### FE-03 登录、强制改密、个人中心 — F-01
- 文件 / 路由：`src/pages/auth/login/index.tsx`（`/login`）、`src/pages/auth/change-password/index.tsx`（`/change-password`）、`src/pages/auth/profile/index.tsx`（`/profile`）
- 使用接口：5.1.1、5.1.4、5.1.5、5.1.3
- 内容：登录表单必填校验、提交 loading 防重复；401102 显示"账号已锁定，请 x 分钟后再试"；登录后若 must_change 进入改密页，否则回 redirect 或 `/`。改密页：新密码规则前端同步校验（8~32、含字母和数字、不同于旧密码），成功后 `loadMe()` 并进入首页；改密页提供"退出登录"。个人中心展示 me.user 字段 + 修改密码入口。
- 完成标准：AC-01~AC-06 中前端可见行为可手测；四种状态处理。

### FE-04 主布局、菜单、路由表、403/404 — F-04
- 文件：`src/layouts/BasicLayout.tsx`、`src/router/routes.tsx`（完整路由表，按第 6 节映射，M2/M3 页面先用占位组件）、`src/pages/exception/{403,404}.tsx`、`src/components/PageContainerWrapper.tsx`
- 使用接口：5.1.4 me（menus）
- 内容：ProLayout 侧边菜单由 `menus` 渲染（图标名映射 `@ant-design/icons`），路由按本地路由表匹配；右上角头像菜单（个人中心、退出）；`/` 重定向到第一个有权限的菜单（无任何菜单时显示空状态页）；直接访问无权限路由显示 403。
- 完成标准：AC-13（菜单随权限变化，刷新生效）、AC-15（403）前端部分。

### FE-05 组织管理页 — F-02
- 文件 / 路由：`src/pages/system/org/index.tsx`、`components/OrgFormModal.tsx`、`components/MoveOrgModal.tsx`；`src/components/OrgTreeSelect.tsx`（通用，调用 5.2.2，支持 `types` 过滤与多选）、`src/components/UserSelect.tsx`（通用，远程搜索 5.3.1）
- 使用接口：5.2 全部、5.3.1（负责人选择）
- 权限码：`system:org:list`、`system:org:create|update|delete`
- 内容：树形 ProTable（名称、类型、编码、负责人、显示顺序、状态（生效状态为停用时标注"上级已停用"）、操作：新增下级/编辑/移动/停用启用/删除）；新增时根据上级类型限制可选类型（集团下可选公司、部门；公司下可选公司、部门；部门下只可选部门）；编码编辑时只读；删除二次确认；409 错误展示后端 message。
- `manageable=false` 的节点（SELF 特例中的本人组织链）不显示任何管理操作；`OrgTreeSelect` 作为写入目标选择时禁用 `manageable=false` 节点。
- 保护规则展示：**直接使用 5.2.1 返回的 `disable_blocked_reason`、`delete_blocked_reason`**，非 null 时"停用"/"删除"按钮置灰（不隐藏）并用 Tooltip 显示该文案；前端**不自行推算**管辖根（AuthContext 未下发角色明细）。组织变更后刷新树以更新标记；请求仍返回 403102/403103 时展示后端 message。
- 完成标准：AC-07~AC-09、AC-74 前端行为。

### FE-06 用户管理页 — F-03
- 文件 / 路由：`src/pages/system/user/index.tsx`、`components/{UserFormModal,AssignRolesModal,ResetPasswordModal,InitialPasswordModal}.tsx`
- 使用接口：5.3 全部、5.2.2、5.4.2
- 权限码：`system:user:list|create|update|status|reset_pwd|assign|delete`
- 内容：左侧组织树（5.2.2）筛选、右侧 ProTable（账号、姓名、所属组织、所属公司、角色、手机、状态、创建时间、操作）；新增用户可选"系统生成密码"，成功后弹窗展示初始密码（复制，关闭后不可再看）；停用/删除前调 5.3.9 展示影响提示；不显示对自己的停用/删除按钮、对 `is_builtin` 不显示删除/停用；分配角色弹窗用 5.4.2，409124 时二次确认后带 `confirm_self_lockout=true` 重提。
- `manageable=false` 的用户行（SELF 特例中的本人账号）不显示编辑、重置密码、分配角色、停用、删除；新增/编辑用户的所属组织选择器禁用 `manageable=false` 节点。
- 完成标准：AC-10~AC-12 前端行为。

### FE-07 角色管理页 — F-04、F-05
- 文件 / 路由：`src/pages/system/role/index.tsx`、`components/{RoleFormModal,GrantDrawer,RoleUsersDrawer}.tsx`
- 使用接口：5.4 全部、5.2.2
- 权限码：`system:role:list|create|update|grant|delete`
- 内容：列表列见 PRD；`editable=false` 的行隐藏编辑/授权/删除；授权抽屉：左侧权限树（`grantable=false` 置灰；已有但不可授予的保持勾选并置灰），右侧数据范围单选（等级高于 `max_data_scope` 的选项置灰，`can_custom=false` 时 CUSTOM 置灰；后端 403124 仍需友好提示），CUSTOM 时显示组织树多选（5.2.2）+ "包含下级"快捷勾选（前端展开为具体组织 ID 提交）；409124 二次确认"保存后您将失去该页面权限"后带 `confirm_self_lockout=true` 重提。
- 完成标准：AC-13~AC-16 前端行为。

### FE-08 操作日志与登录日志页 — F-06
- 文件 / 路由：`src/pages/system/log/operation/index.tsx`、`components/OpLogDetailDrawer.tsx`、`src/pages/system/log/login/index.tsx`
- 使用接口：5.5 全部
- 权限码：`system:oplog:list`、`system:loginlog:list`
- 内容：时间范围默认近 7 天、最长 180 天（前端限制）；模块/操作类型下拉使用 5.8 枚举的中文映射（`src/pages/system/log/dict.ts`）；详情抽屉展示 summary（before/after 表格对比，未知结构以 JSON 展示）；无修改/删除操作。
- 完成标准：AC-20、AC-21 前端行为。

## 9. 任务依赖与并行

| 阶段 | 后端 | 前端 |
|---|---|---|
| 1 | BE-01 | FE-01 |
| 2 | BE-02 | FE-02（对契约开发，mock 数据单测） |
| 3 | BE-03 | FE-03、FE-04 |
| 4 | BE-04 | FE-05、FE-06、FE-07、FE-08（对契约并行） |
| 5 | BE-05、BE-06（可并行，同服务不同文件；建议同一后端智能体顺序执行以免迁移冲突——二者均无迁移，可并行派发） | 联调 FE-03/FE-04 |
| 6 | BE-07、BE-08、BE-09、BE-10（依赖 BE-05/06；四者可并行派发给不同智能体，各自只改自己的 api/schemas/services/repositories 文件；共享的 `role_service.assignable_roles_for` 由 BE-09 拥有，BE-08 依赖它时先以接口桩对接） | 联调 FE-05~FE-08 |

- 先后依赖：BE-01 → BE-02 → BE-03 → BE-04 → 其余；迁移只在 BE-04 产生（M1 中其他任务不得新增迁移；如需改表提契约变更）。
- 前端联调前提：BE-04、BE-05、BE-06 完成（可登录、可拿 me）。

## 10. 风险与兼容性
- 无存量数据；回滚：`alembic downgrade base`（iam schema 整体删除）。
- `INCR authz:epoch` 会让全部在线用户在下一次请求时回源 iam 计算上下文（2 万用户分散在时间上），单次计算 <20ms，可接受；如出现抖动，可在 AuthContext 计算中缓存组织树（进程内，随 epoch 失效）。

## 11. 测试要点（M1）
- 越权：普通员工调用所有 `system:*` 写接口 → 403001；A 公司管理员以 B 公司的 org/user/role ID 调详情、编辑、停用、重置、删除、分配角色 → 404000；A 公司管理员把 A 的公司级角色分配给 B 的用户 → 拒绝（AC-16）。
- 数据范围：用 AC-17 组织样本，在用户列表、组织树、操作日志、登录日志上验证 7 种范围与并集（AC-18）；DEPT/DEPT_AND_CHILD 对"直属公司节点用户"的特殊口径（A-05）。
- 会话：登出后旧 access_token 立即 401002；改密时当前会话保留、其他会话失效（AC-05）；停用组织后其下用户会话失效；刷新令牌重复使用 → 401104；7 天未刷新 → 401104。
- 锁定：15 分钟窗口边界、锁定剩余时间提示、成功登录清零。
- 授权上限：直接构造请求授予超出权限、ALL 范围、范围外 CUSTOM 组织（AC-14）；自锁 409124。
- 并发：两人同时编辑同一组织/角色 → 后者 409001。
- 日志：AC-20 五类操作中 M1 可验的两类（重置密码、修改数据范围）；无明文密码；Redis 停止时业务成功、日志缺失但运行日志报错。
- 回归：无（首个需求）。

## 12. 变更记录
| 日期 | 变更内容 | 原因 | 影响任务 |
|---|---|---|---|
| 2026-11-11 | 初稿 | 新需求 | 全部 |
| 2026-11-11 | 端口改为专属（3.2 `BaseServiceSettings` 默认值：DB 15432、Redis 16379、内部地址 8301/8302/8303；BE-04 `PORT=8301`；FE-01 dev 5174 与 proxy 目标） | 用户确认：本机多项目共用 | BE-01、BE-02、BE-04、FE-01 |
| 2026-11-11 | 3.3 去掉 minio-init，宿主端口 `${VAR:-默认}` 可覆盖，MinIO healthcheck 用 curl；3.4 devctl `init`/`migrate` 用 boto3 幂等建桶；`down` 端口兜底只终止本项目进程；BE-01 依赖增加 aioboto3 | BE-01 反馈：本机无法拉取 `minio/mc` | BE-01 |
| 2026-11-11 | 5.4.2 增加 `org_id` 参数（与 `user_id` 二选一，权限码 any-of `system:user:assign`/`system:user:create`）；5.3.3 明确创建用户可直接带 `role_ids`（按目标组织判定可分配）；5.4.0 规则同步 | FE-06 反馈 | BE-08、BE-09、FE-06 |
| 2026-11-11 | 4.9 补全登录日志 `fail_reason` 枚举（bad_credentials/locked/user_disabled/org_disabled）及中文含义 | FE-08 反馈 | BE-05、FE-08 |
| 2026-11-11 | 5.1.4 明确超管 `permissions` 返回全部权限码；5.1.1 明确 401102 一定返回 `remaining_seconds`（整数 ≥1）；`menus[].icon` 来源 | FE-02 反馈 | BE-05、BE-06、FE-02、FE-03 |
| 2026-11-11 | 5.4.4 澄清：`data_scope`/`custom_org_ids` 在创建接口为可选（默认 SELF），前端本期在授权抽屉设置数据范围，契约不变 | FE-07 反馈 | 无（澄清） |
| 2026-11-11 | 4.11 downgrade 改为逐表 DROP、保留空 `iam` schema | `alembic_version` 位于 iam schema 内（BE-04 反馈，主会话已同意） | BE-04（已按此实现） |
| 2026-11-11 | 5.1.4 菜单规则明确：叶子需拥有、目录随子菜单出现且不要求目录码 | BE-06 反馈 | BE-06、FE-04 |
| 2026-11-11 | 5.6.3/5.6.4 明确游标条件，未传 `updated_after` 时忽略 `after_id` | BE-06 反馈 | BE-06、BE-12、BE-24 |
| 2026-11-11 | BE-07/BE-08 增加约束：批量 UPDATE 必须显式写 `updated_at`/`updated_by` | 保证 sync 游标与事件不漏行 | BE-07、BE-08 |
| 2026-11-11 | 确认 DEPT_AND_CHILD 对直属公司节点用户的口径（含该公司全部部门，不进入下属公司）与 PRD F-05 规则 4 / A-05 一致，无需改动 | BE-06 反馈 | 无 |
| 2026-11-11 | 5.2.7/5.2.8 增加管辖根节点保护与"不能停用本人所在组织"（403102）；状态相同为 no-op | M1 联调发现子公司管理员可停用本公司导致全员下线（TQ-06） | BE-07、FE-05 |
| 2026-11-11 | 5.2.8 删除组织：被公司级角色归属 → 409106；CUSTOM 引用自动移除并 bump epoch、记日志 | M1 联调发现角色指向已删除组织 | BE-07 |
| 2026-11-11 | 5.2.4/5.2.6 部门可直接挂在集团下（不再返回 400001）；移动到当前上级为 no-op；4.8 `revoke_reason` 增加 `org_disabled` | PRD F-10 规则 5 存在"集团下的部门"（TQ-07）；BE-07 反馈 | BE-07、FE-05 |
| 2026-11-11 | 5.3.5/5.3.6/5.3.7 确认：状态相同为 no-op；重置密码与分配角色不递增 version、不发 `user.upserted` | BE-08 反馈 | 无（确认现有实现） |
| 2026-11-11 | 3.2 `data_scope_filter` 列参数允许可空列（仅类型放宽，语义不变）；新增 `auth/runtime.py` 可注入 context loader，iam 注册本地 loader | BE-10、BE-05 反馈；向后兼容，M2/M3 无需改调用方式 | BE-03（共享库）、BE-05/BE-06、BE-10 |
| 2026-11-11 | 5.8 补充 summary 结构约定（删除只有 before） | BE-09 反馈 | BE-09、FE-08 |
| 2026-11-11 | 对照 PRD v0.3：新增 5.2.0 组织保护规则（按数据范围定义管辖根，含 CUSTOM 与多角色；本人组织链对超管也生效）；403102 拆分为 403102（管辖根，停用/删除）与 403103（本人组织链，仅停用）；OrgNode 增加 `disable_blocked_reason`/`delete_blocked_reason`（5.2.1 返回，前端置灰提示）；4.1 补充集团本部口径 | 用户确认 TQ-06/TQ-07，PRD v0.3 F-02 规则 1/2/9、AC-74 | BE-07、FE-05 |
| 2026-11-11 | 核对 BE-06 数据范围：集团本部用户 `company_id`=集团节点，`COMPANY` 只覆盖集团本部（集团节点及其不经公司的下级部门），`COMPANY_AND_CHILD` 覆盖全部公司，`DEPT_AND_CHILD` 不进入任何公司——与 PRD v0.3 F-03 规则 1、F-05 规则 4 一致，无需改动 | PRD v0.3 | 无 |
| 2026-11-11 | 4.2 写明账号区分大小写、唯一约束按原值 | 用户确认保持现状 | 无（澄清） |
| 2026-11-11 | 新增 5.2.0a SELF 只读特例：iam 查询用 `visible_filter`（OR 本人账号/本人组织链），写接口用 `manage_filter`；可见不可管理的写请求返回 403001；OrgNode、组织选择器节点、UserItem 增加 `manageable` | M1 第 1 轮测试后用户确认 | BE-07、BE-08、BE-09（assignable/CUSTOM 校验用管理范围）、FE-05、FE-06、FE-07（选择器不可选） |
| 2026-11-11 | 3.2 `BaseServiceSettings.validate_for_runtime()`：非 dev/test 环境 `INTERNAL_API_TOKEN` 为默认值或过短拒绝启动；`TRUSTED_PROXIES` 生产只填 Nginx 地址 | 测试提出的部署安全建议，用户确认 | BE-02（共享库）、BE-29 |

## 13. 实现说明（开发补充）
- 后端：
  - **BE-01 已完成**（共享）。文件：`docker-compose.yml`、`deploy/local/postgres-init.sql`、`backend/{requirements.txt,requirements-dev.txt,pyproject.toml}`、`backend/scripts/devctl.py`、`backend/libs/platform_common/{pyproject.toml,platform_common/__init__.py}`。
  - 实际固定版本（pip 实测可装）：fastapi 0.162.4、uvicorn[standard] 0.54.0、pydantic 2.14.3、pydantic-settings 2.16.2、sqlalchemy[asyncio] **2.0.57**（刻意不用 2.1.x，保持技术栈基线 2.0）、asyncpg 0.32.0、alembic 1.20.1、redis 8.1.0、httpx 0.28.1、pyjwt[crypto] 2.15.1、cryptography 50.0.2、bcrypt 5.0.0、python-multipart 0.0.33；dev：pytest 9.2.0、pytest-asyncio 1.4.1.post1、ruff 0.17.4、mypy 2.4.1（尚无需要的 types-* 存根）。
  - 编排（已按"专属端口"修正）：postgres(`pgvector/pgvector:pg16`，宿主 **15432**，kbp/kbp/kbp，初始化脚本建 `kbp_test` 并在两库装 `vector`)、redis(`redis:7-alpine`，宿主 **16379**，AOF)、minio(宿主 **19000/19001**，minioadmin/minioadmin，healthcheck 用 curl `/minio/health/live`)。**无 minio-init 容器**，桶 `kbp-files`、`kbp-test` 由 `devctl.py init` 用 boto3 幂等创建（`S3_ENDPOINT` 默认 `http://127.0.0.1:19000`，可由 `S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY/S3_REGION` 覆盖）。数据卷 `.docker-data/`。宿主端口可用 `POSTGRES_PORT/REDIS_PORT/MINIO_API_PORT/MINIO_CONSOLE_PORT` 覆盖。服务端口：iam 8301、kb 8302、open 8303。
  - `pyproject.toml` 位于 `backend/`，mypy 排除 `tests/` 与 alembic versions，pytest testpaths 为 `libs/platform_common/tests` 与 `services`。
  - devctl 用法（仓库根）：`.venv/bin/python backend/scripts/devctl.py init | migrate [svc] | up [-d] [svc...] | down [svc...] | status`，`--env test` 置于子命令前（注入 kbp_test、Redis db 1、桶 kbp-test）。`init` 幂等：密钥已存在则跳过，并确保两个桶存在。**`down` 只按 `.run/<svc>.pid` 停止本脚本启动的进程，不再按端口查找/终止任何进程**；`status` 同样只看 PID 文件。服务入口不存在时 `up`/`status` 优雅降级。新增依赖 aioboto3 15.5.0 + boto3 1.40.61（提前加入，kb 在 M2 使用）。
  - **BE-02 已完成**（`backend/libs/platform_common/platform_common/`）：`config.py`（BaseServiceSettings，默认值使用新端口；`jwt_public_key_path` 属性解析相对路径）、`errors.py`（BizError、CommonErrors、`error_from_http_status`）、`response.py`（`ok()`/`page()`、`ApiResponse[T]`、`Page[T]`、**`LocalDatetime`**：响应 schema 中的时间字段使用该类型即输出 `+08:00` ISO 8601）、`pagination.py`（`PageParamsDep` 依赖，含 `offset/limit`）、`db.py`（`init_db/get_engine/get_session_factory/dispose_db`、`Base/AuditMixin/VersionMixin`、`get_db`）、`redis.py`（`init_redis/get_redis/close_redis`）、`logging.py`（JSON 日志、`get_request_id/set_request_id`）、`app_factory.py`、`client_ip.py`、`http_client.py`（`InternalClient.get/post/aclose`，返回响应 `data`）、`crypto.py`、`jobs.py`。
  - `create_app(settings, routers, lifespan_hooks, *, title, version)`：`routers` 自带前缀；`lifespan_hooks` 为 `(app) -> async context manager` 列表，在 DB/Redis 初始化后按序进入、逆序退出。中间件：纯 ASGI 的请求 ID + 访问日志（`/healthz`、`/readyz` 不记）；500 响应同样带 `X-Request-Id`。异常处理：BizError、RequestValidationError(→400 / 400001，`data.errors=[{field,message}]`)、HTTPException(按状态码映射通用错误码，不透出 detail)、未知异常(→500000，堆栈仅入日志)。`/readyz` 失败返回 HTTP 503 / 503001，`data={"database":"ok|fail","redis":"ok|fail"}`。
  - 引擎/Redis 为进程内单例（`init_db`/`init_redis` 幂等），`get_db` 不自动提交。`AuditMixin.id` 为 `BIGINT IDENTITY (BY DEFAULT)`，`updated_at` 带 `onupdate=now()`。DB 连接强制 `timezone=Asia/Shanghai`（`server_settings`）。
  - `run_periodic`：先抢 `job:lock:{name}`（TTL=间隔）再执行，首轮立即执行；任务异常只记日志。cache_keys.py 属 BE-03，目前锁键在 jobs.py 内联。
  - **BE-03 已完成**（`platform_common/auth/{cache_keys,runtime,jwt,context,deps,data_scope,internal}.py`、`events/{streams,publisher,consumer}.py`、`oplog.py`）。jobs 锁键已收入 `cache_keys.job_lock`。
  - **契约细节（与 3.2 签名的差异均为向后兼容的补充）**：
    - `auth/runtime.py`：`create_app` 在 lifespan 中 `configure(settings)`，鉴权模块据此取公钥、`INTERNAL_API_TOKEN`、iam 地址；iam 内部客户端（`InternalClient`）惰性创建、关闭时释放。`verify_access_token(token, settings=None)`，`settings` 缺省取已注册的。JWT 约定：RS256，`sub`=字符串形式 user_id，必含 `sid`、`exp`，`iss` 必须等于 `JWT_ISSUER`；公钥读取失败 → 500000。
    - `AuthContext.usable` 为 `computed_field`，序列化后与总体方案 3.5.1 的 JSON 一致；加载时多余字段被忽略。iam 内部接口 `GET /internal/v1/authz/contexts/{uid}` 的 `data` 即 AuthContext，由 iam 自己回写缓存。
    - `get_auth_context` 6 步实现；Redis 单次 `MGET [auth:sess, authz:ctx, authz:epoch]`；epoch 缺省视为 0；Redis 不可用 → 503001；ctx.user_id 与 token 不符 → 401002。`request.state.ctx` 缓存，同一请求多个依赖不重复校验。`require_login(allow_must_change)` / `require_perm(*codes, mode)` 均基于它；`require_perm` 不放行 must_change（403002）。
    - `require_internal` 的 header 声明为可选，缺失同样返回 401901（而非框架 400001）。
    - `data_scope_filter` 用 `IN (绑定参数)` 而非 `= ANY`（语义相同）；ALL/超管 → `true()`，皆空 → `false()`；列为 NULL 不命中。AC-17 七种范围 + AC-18 并集已由单测覆盖：编译 SQL 断言、`in_data_scope` 内存判断、真实 PostgreSQL 临时表执行三者一致。
    - 事件信封统一为 Stream 单字段 `data` 存 JSON：`{"event_id","type","occurred_at","payload"}`；`stream:oplog` 的 `data` 为 OpLogEvent JSON。`publish_after_commit` 通过 SQLAlchemy `after_commit`/`after_rollback` 事件实现，`drain_pending_publishes()` 供停机/测试等待。
    - `StreamConsumer`：自动建组（从头消费）；handler 收到信封 dict 并附 `_stream_id`；失败消息在本消费者按指数退避重试（`retry_backoff_seconds`），累计 `max_retries` 次后写 `stream:dead`（含 stream/group/message_id/error/原始 data）并 XACK；JSON 非法直接进死信；他人遗留且空闲 ≥ `claim_idle_ms` 的消息经 XAUTOCLAIM 接管；`stop()` 立即打断阻塞读并优雅退出。失败计数在进程内存中（重启后重新计数）。
    - `oplog`：`mask_sensitive` 递归脱敏键名含 password/passwd/secret/api_key/credential/private_key，或以 `token` 结尾（`access_token`、`token`；`max_tokens` 不脱敏）；`emit_oplog` 写入前再次脱敏并吞掉全部异常；`oplog_scope` 的 handle 提供 `summary`、`set_target(id, name)`，BizError → failure(message)，其他异常 → failure(系统繁忙)，均继续抛出。注意：日志 `extra` 的键不得与 LogRecord 保留字段重名（曾因 `module` 触发 KeyError，已改为 `op_*`）。
  - 单测累计 76 个（`libs/platform_common/tests/`，需本地 Postgres/Redis）。
  - mypy：`backend/pyproject.toml` 设置 `mypy_path = "libs/platform_common"`（editable 安装对 mypy 不可见），在 `backend/` 下执行 `../.venv/bin/mypy libs/platform_common/platform_common scripts`；boto3 系列忽略缺失存根。单测 28 个位于 `libs/platform_common/tests/`（依赖本地 kbp_test / Redis db 1）。
  - **BE-04 已完成**（`backend/services/iam/`）。迁移 `0001_init_iam`（10 张表，`alembic check` 无漂移）；`alembic upgrade head` / `downgrade base` / 再 `upgrade` 已验证。
    - 目录：`main.py`、`alembic.ini`、`alembic/{env.py,script.py.mako,versions/0001_init_iam.py}`、`app/core/{config,constants,security}.py`、`app/models/{org,user,role,permission,session,log}.py`（`role.py` 含 sys_role/sys_role_org/sys_role_permission/sys_user_role）、`app/seed/{__main__,permission_registry,builtin}.py`、`app/api/v1/__init__.py`（仅导出空 `router`，前缀 `/api/v1`，BE-05 起往里 include）、`.env.example`。
    - `alembic/env.py`：异步引擎；`version_table_schema="iam"`，`include_name` 只放行 iam schema；连接后先 `CREATE SCHEMA IF NOT EXISTS iam`（版本表在该 schema 内，必须先建）。**与 4.11 的差异**：`downgrade` 逐表 `DROP TABLE`（索引随表删除）而**不** `DROP SCHEMA iam CASCADE`，因为 `alembic_version` 位于 iam schema，删 schema 后 Alembic 无法回写版本记录导致 `downgrade base` 失败；downgrade 后 iam schema 保留为空（仅含版本表）。
    - 模型：全部继承 `AuditMixin`（含关联表，物理删除但保留审计列），`sys_org/sys_user/sys_role` 另含 `VersionMixin`；`sys_role_name` 唯一索引为表达式索引 `(COALESCE(owner_company_id,0), name) WHERE is_deleted=false`（在 `role.py` 类外用 `func.coalesce` 声明）。`sys_org.dept_id` NOT NULL 且无默认值：插入时先写 0，`flush` 取得 id 后回填 `company_id/dept_id`（seed 已按此实现，BE-07 创建组织沿用，同事务完成）。`sys_login_log.created_by` 约定为 user_id（账号不存在时 0），`sys_operation_log.created_by` 约定为 operator_id，由 BE-05/BE-10 写入时填充。
    - `core/config.py` 的 `Settings(BaseServiceSettings)` 按 BE-04 要求增加全部配置项；`get_settings()` 带 `lru_cache`；`jwt_private_key_path` 相对路径按 `backend/` 解析（同公钥）。
    - `core/security.py`：`sign_access_token(user_id, sid, settings=None) -> (token, expires_in秒)`（RS256，claims `iss/sub=str(user_id)/sid/iat/exp/typ=access`，已与共享库 `verify_access_token` 联测）；`hash_password`（bcrypt cost 12）、`verify_password`（异常/超长返回 False）、`generate_password(length=12)`、`validate_password_rule`、另提供 `generate_refresh_token()`（`rt_` + 48 字节 urlsafe，供 BE-05 使用，库中存 `platform_common.crypto.sha256_hex`）。
    - `core/constants.py`：`OrgType/Status/RoleType/DataScopeType/PermType/BuiltinRole/RevokeReason/LoginFailReason` 等 StrEnum 与密码、账号正则常量。
    - 权限注册表：`PermissionDef` 字段 `code/name/perm_type/parent_code/path/icon/sort_order/service/default_roles`，共 **44 个权限码**（15 menu + 29 button），icon/sort_order 取自总体方案第 7 节；`validate_registry()` 在 seed 启动前自检（code 唯一、父级先于子级、菜单图标在前端白名单、按钮无图标）。按钮 `sort_order` 按表中顺序在各父级下从 1 起编号；`service` 归属：kb（kb:* 与 system:model:*）、open（openapi:*）、iam（其余 system:*）。
    - Seed（`python -m app.seed`，同一事务，已验证连续两次执行结果一致）：集团节点（按 `org_type=group` 判存在）→ 权限点 upsert（按 code，更新名称/路由/图标/排序/父级/类型/服务）→ 4 个内置角色（集团级；super_admin/group_admin=ALL，company_admin=COMPANY_AND_CHILD，employee=SELF）→ 新建角色授予全部默认权限，已有角色只补**本次新插入**权限点（不覆盖管理员调整，也不覆盖内置角色名称/数据范围）→ `admin` 用户（已存在不重置密码，`must_change_password=true`、`is_builtin=true`、授予 super_admin，`sys_user_role.org_id`=集团节点）→ 事务提交后 `INCR authz:epoch`（Redis 不可用时 seed 失败）。授权数：super_admin 44、group_admin 44、company_admin 40（无模型配置）、employee 16。
    - mypy：`backend/pyproject.toml` 的 `mypy_path` 改为 `$MYPY_CONFIG_FILE_DIR/libs/platform_common`，使在服务目录执行 `../../../.venv/bin/mypy app` 与在 `backend/` 执行均可解析共享库（此前相对 cwd 解析，仅 backend/ 下可用）。
    - 单测（`services/iam/tests/unit/`，17 个，不进 git）：安全工具、注册表（44 个/图标白名单/排序/默认角色）、seed 幂等与"不覆盖管理员调整"、OpenAPI 与 `/healthz`、`/readyz`。使用 `kbp_test` 库与 Redis db 1；`migrated_db` 夹具每次先 `downgrade base` 再 `upgrade head`；`tests/` 下不放 `__init__.py`（避免与共享库 `tests` 包同名冲突），`conftest.py` 自行把服务目录加入 `sys.path`，在服务目录执行 `../../../.venv/bin/pytest tests/unit`。seed 测试结束会清除 Redis db 1 的 `authz:epoch`（共享库测试假设 epoch 缺省为 0）。
    - 已验证：`devctl.py up -d iam` 后 `/healthz`、`/readyz`（database/redis 均 ok）、`/docs`（200）、`/openapi.json` 正常；`devctl.py migrate iam` 执行 `alembic upgrade head` + seed 正常。开发库 `kbp` 已 seed：集团节点 id=1、admin(id=1，初始密码 `Admin12345`，首次登录需改密)。
  - **BE-06 已完成**（iam）。新增：`app/services/{authz_service,event_service,sync_service}.py`、`app/repositories/{permission_repo,role_repo,org_repo,user_repo}.py`（仅 BE-06 所需查询，BE-07/08/09 在同文件追加）、`app/schemas/{authz,sync,permission}.py`、`app/api/internal/{__init__,authz,sync}.py`（`main.py` 已挂载 `internal_router`，前缀 `/internal/v1`，整体依赖 `require_internal`）。无迁移。
    - **authz_service 对外函数（BE-05 及后续任务直接调用，均为 async，`session` 为 `AsyncSession`）**：
      - `get_context(session, user_id) -> AuthContext | None`：计算并回写 `authz:ctx:{uid}`（TTL=`AUTHZ_CTX_TTL_SECONDS`，epoch 为计算前读取的当前值）；用户物理不存在返回 None；已删除用户返回 `is_deleted=true`、`permissions=[]`、空数据范围。写缓存失败只记日志。
      - `get_contexts(session, user_ids) -> dict[int, AuthContext | None]`：批量版（固定条数查询，无 N+1），同样回写缓存；`compute_contexts(session, ids, epoch=...)` 为不写缓存的纯计算版。
      - `invalidate_user(user_id)` / `invalidate_users(ids)`：`DEL authz:ctx:{uid}`；`bump_epoch() -> int`：`INCR authz:epoch`；`current_epoch() -> int`。
      - 事务提交后执行版本：`invalidate_user_after_commit(session, uid)`、`invalidate_users_after_commit(session, ids)`、`bump_epoch_after_commit(session)`（注册在 `session.info`，`commit` 成功后以后台任务执行，回滚丢弃；`drain_after_commit()` 供测试/停机等待）。后台任务不保证在 HTTP 响应前完成；要求"立即生效"的写接口（改密、停用、吊销等）推荐 `await session.commit()` 之后直接 `await invalidate_user(...)`。
      - `/auth/me` 组装：`get_me_payload(session, ctx) -> tuple[list[str], list[MenuNode]]`，返回 `(permissions, menus)`，permissions 即 `ctx.permissions`（超管为全部 44 个码），menus 为菜单树；纯函数 `build_menu_tree(permissions: Sequence[SysPermission], owned_codes | None)`（None=全部菜单）。`MenuNode`（`app/schemas/permission.py`）字段：`code,name,path,icon,sort_order,children`，直接作为响应 schema 使用。菜单规则：只含 `perm_type=menu`；叶子菜单（无菜单子节点）须拥有才出现；目录节点在其下出现任一子菜单时出现（不要求直接拥有目录码；只拥有目录码而无子菜单则不出现）；同级按 `(sort_order, id)`。
    - 数据范围解析（`compute_contexts`）：仅启用且未删除的角色生效；超管 = 持有启用的 `builtin_key=super_admin` 角色（`all=true`，permissions=全部码）；`ALL`→`all`；`COMPANY`→`[user.company_id]`；`COMPANY_AND_CHILD`→本公司 + 全部下属公司（`org_type in group/company`，按 `ancestors` 整段匹配，不含已删除，含已停用；集团本部用户得到集团节点 + 全部公司）；`DEPT`→`[user.org_id]`；`DEPT_AND_CHILD`→`org_id` + 其下 `org_type=dept` 且 `company_id == user.company_id` 的全部部门（不跨入下属公司；直属公司节点时 = 公司节点 + 公司下所有部门）；`SELF`→`include_self`；`CUSTOM`→`sys_role_org` 勾选组织（不含下级）；多角色取并集；`company_ids/org_ids` 去重升序。`org_path` = ancestors 去掉 0 + 自身；`org_enabled` = 路径上全部节点存在、未删除且启用。
    - 内部接口：`GET /internal/v1/authz/contexts/{user_id}`（不存在 404000；`data` 为 AuthContext，含 `usable`）；`POST /internal/v1/authz/contexts/batch`（`user_ids` 1~200，否则 400001；`data.items` 键为字符串 user_id，不存在为 null）；`GET /internal/v1/sync/users|orgs`（`updated_after` 可选 ISO、`after_id>=0` 默认 0、`limit` 1~1000 默认 500，含已删除，按 `(updated_at,id)` 升序，`next` 在无更多数据时为 null；`updated_after` 缺省时忽略 `after_id`；游标用 `or_(updated_at > x, and_(updated_at = x, id > y))`；时间输出 `+08:00`）。缺失/错误 `X-Internal-Token` → 401901。
    - 事件（`event_service`，事务提交后发布到 `stream:iam.events`，回滚丢弃）：`publish_user_upserted(session, user)`、`publish_users_upserted(session, users)`、`publish_org_upserted(session, org)`、`publish_orgs_upserted(session, orgs)`（移动组织时对子树每个节点调用）。函数内部会 `flush` 并 `refresh(updated_at)`，调用方在变更后直接调用即可；payload 即 `UserRef`/`OrgRef`（`schemas/sync.py`），信封为共享库统一格式。注意：对 `sys_user/sys_org` 做**批量 `UPDATE`**（如组织移动重算 company_id）时必须显式 `updated_at=func.now()`，否则同步游标与事件会漏掉这些行。
    - 单测（新增 27 个，累计 44 个，`tests/unit/`）：7 种范围（含直属公司节点、集团本部）、并集、停用/删除角色不计入、祖先组织停用与自身删除、停用/删除/不存在用户、缓存与 epoch 与提交后失效/回滚丢弃、菜单树各规则、事件提交后才发布与回滚丢弃、内部接口 401901/404000/400001、sync 多页游标无遗漏无重复/恰整页 next=null/`updated_after` 续传。新增 `clean_db` 夹具（TRUNCATE iam 表 + 清 Redis db1 的 `authz:*` 与 `stream:iam.events`）；conftest 在导入 app 前把 `DATABASE_URL/REDIS_URL` 指向测试库，使经 `main.app` 的 API 测试不碰开发库；因每个用例都 seed（bcrypt cost 12），整套约 30 秒。
    - 已验证（`devctl up -d iam` + curl，开发库）：`/internal/v1/authz/contexts/1` 返回超管上下文且写入 Redis `authz:ctx:1`；无 token 401901；用户 999 → 404000；batch、sync/orgs 正常；OpenAPI 含 4 个内部路径。
  - **BE-05 已完成**（iam，F-01）。无迁移。新增：`app/api/v1/auth.py`（`api/v1/__init__.py` 已 include）、`app/schemas/auth.py`、`app/services/{auth_service,session_service}.py`、`app/repositories/{session_repo,log_repo}.py`；`user_repo` 追加 `get_by_username/get_by_id/touch_last_login/update_password`；`authz_service` 末尾追加公开的 `run_after_commit(session, func, *args)`。
    - 接口按 5.1 实现：`login`/`refresh` 为 public，`logout`/`me`/`password` 为 `require_login(allow_must_change=True)`；响应均带 `response_model`，OpenAPI 已生成。
    - 登录：先 `TTL auth:lock:{username}`（锁定中直接 401102，`data.remaining_seconds=max(ttl,1)`，message 的分钟数向上取整）；账号不存在也会做等价的 bcrypt 比较（防耗时枚举）并同样计数、锁定；失败第 5 次返回 401101 并写锁，第 6 次起 401102（含密码正确）；密码正确后才判断停用（401103，user_disabled / org_disabled 由 `authz_service.get_context().org_enabled` 判定），故错误密码不会泄露账号状态。成功后清失败计数、建会话、更新 last_login（`touch_last_login` 显式保持 `updated_at` 不变，避免干扰同步游标）。登录日志用**独立事务同步写**，失败只记运行日志；账号不存在时 `user_id=NULL`、`created_by=0`；`fail_reason` 仅 4 个枚举值。bcrypt 校验/哈希走 `asyncio.to_thread`。
    - 会话：`session_service.create_session` 在调用方事务内写 PG，并同步写 Redis（`auth:sess:{sid}` JSON、`auth:user_sess:{uid}` set，TTL=`REFRESH_TOKEN_EXPIRE_DAYS`）；Redis 写失败 → 503001 并回滚。刷新：`SELECT ... FOR UPDATE` 取 `revoked_at IS NULL AND expires_at > now` 的会话，要求 Redis 会话存在且用户 `usable`，否则 401104；轮换哈希、续期 PG/Redis（同一 sid，Redis 续期在提交前）。登出：PG 吊销（reason=logout）+ 提交后立即删 Redis。当前 sid 取自 access token（`verify_access_token`）。
    - **供其他 service 调用**：`session_service.revoke_all(session, user_id, reason, except_sid=None) -> list[str]`（**注意第一个参数是 `AsyncSession`**，与任务清单签名相比多一个 session，以便与调用方的改密/停用在同一事务内更新 PG；不提交；返回被吊销的 sid；同时注册"提交成功后清理 Redis"，回滚丢弃）。要求**即时生效**时（重置密码、停用、删除用户），调用方应：`sids = await revoke_all(...)` → `await session.commit()` → `await session_service.purge_cache(user_id, sids, except_sid=None)` → `await authz_service.invalidate_user(user_id)`。`purge_cache` 幂等，会同时清理 `auth:user_sess:{uid}` 集合中的全部 sid。`reason` 取 `RevokeReason`（password_changed/password_reset/user_disabled/user_deleted/logout）。
    - 改密：校验顺序 400101（原密码）→ 400102（规则，`data.errors=[{field:"new_password",message}]`，给出具体原因：长度/缺字母/缺数字）→ 400103（与当前密码相同）；请求体 schema 只限制非空与 ≤128，规则交由 service，以保证返回 400102 而非通用 400001。成功后 `must_change_password=false`、`password_changed_at`、吊销**除当前 sid 外**全部会话（reason=password_changed）→ commit → 清缓存 → `invalidate_user`。
    - `/auth/me`：`user` 含 `org_name/company_name`（`org_repo.get_by_ids`），`permissions/menus` 复用 `authz_service.get_me_payload`；超管 44 个权限码、3 个顶级菜单（kb:dataset:list、openapi:menu:root、system:menu:root）。
    - 无操作日志：5.8 枚举未包含认证类操作，登录/登出只写登录日志。
    - 单测（`tests/unit/test_auth_api.py`，20 个，累计 64 个，整套约 47 秒）：登录成功+me+会话落库、未登录 401001、参数校验 400001、第 6 次锁定（含 `remaining_seconds`、日志原因序列、到期后可登录、TTL<1s 取 1）、成功清零失败计数、不存在账号同提示且同样锁定、停用用户/停用上级组织（日志 user_disabled/org_disabled，错误密码仍 401101）、刷新轮换/旧令牌 401104/过期/Redis 会话缺失/用户停用、登出、改密后其他会话 401002 且其刷新令牌失效而当前会话可用、改密各校验、重置（revoke_all）后全部会话失效、提交后钩子、回滚不吊销、`must_change` 访问 `require_perm` 接口 403002（me/password 白名单可用）、无权限 403001、超管 44 权限码。测试中 bcrypt cost 降为 4，并 monkeypatch `platform_common.auth.deps.fetch_context_from_iam` 为进程内直接计算（测试进程没有监听 8301 的真实 iam）。`tests/unit/helpers.py` 的 `add_user` 允许覆盖 `password_hash`。
    - 已验证（`devctl up -d iam` + curl，开发库）：admin/Admin12345 登录 → `must_change_password=true` → `/auth/me` 返回 must_change 标记（44 权限码）→ 弱密码 400102 → 改密 → `/auth/me` 44 权限码 + 菜单 → refresh（旧令牌 401104）→ logout → 旧 access token 401002；不存在账号第 6 次 401102 `remaining_seconds=900`。
    - **开发库 admin 状态**：验证后已恢复为初始状态——初始密码仍为 `Admin12345`，`must_change_password=true`。（恢复过程中误对开发库执行了 `alembic downgrade -1`，iam schema 被清空后重新 `upgrade head` + `python -m app.seed`，开发库 iam 数据此前仅有 seed 数据，现状等价；组织 id=1 为集团、admin id=1。）
    - 风险提示：iam 自身的鉴权缓存未命中时，`get_auth_context` 经共享库 `fetch_context_from_iam` 以 HTTP 回源 `IAM_INTERNAL_URL`（即调用自身）。单进程 uvicorn 下可用（异步不死锁），但依赖该地址配置正确；建议后续（契约变更）在共享库 `auth/runtime` 增加可注入的本地 context loader，iam 启动时注册为直接计算。
  - **BE-09 已完成**（iam，F-04/F-05）。无迁移。新增：`app/api/v1/{roles,permissions}.py`（已 include）、`app/schemas/{role,user}.py`（`user.py` 目前仅含 `UserItem`/`RoleRef`，BE-08 在此追加请求/响应模型，勿覆盖）、`app/services/role_service.py`；`role_repo`、`permission_repo.get_by_ids`、`user_repo.page_users_of_role` 追加查询。5.4.1~5.4.9 全部按契约实现，均有 `response_model`；写接口用 `oplog_scope` 记 `role/create|update|grant|delete`（失败也记 failure），summary：create `{"after":{...,"custom_org_ids"}}`、update `{"before","after"}`、grant 按 5.4.6、delete `{"before"}`。
    - **供 BE-08 复用（`app.services.role_service`，均 async，`ctx` 为操作人 `AuthContext`）**：
      - `assignable_roles_for(session, ctx, *, user_id: int | None = None, org_id: int | None = None) -> list[AssignableRole]`：二选一（都传/都不传 → 400001）；`user_id` 须为未删除且在 `in_data_scope` 内的用户，`org_id` 须为未删除且在范围内的组织，否则 404000；返回对目标可分配的启用角色，`assigned` 表示用户已持有（org 场景恒 false）。**不校验功能权限码**（路由层 `require_perm` 负责；`GET /roles/assignable` 在 service `list_assignable` 内按场景要求 `system:user:assign` / `system:user:create`，否则 403001）。
      - `ensure_roles_assignable(session, ctx, role_ids, *, user_id=None, org_id=None) -> list[SysRole]`：role_ids 须全部在可分配集合内，否则 403121（5.3.3 创建用户带 `role_ids` 用 `org_id=`，5.3.7 分配角色用 `user_id=`）；返回角色按 id 升序。
      - `assignable_roles(session, ctx, target_company_id) -> list[SysRole]`：已知目标所属公司时的底层判定；`can_manage_role(ctx, role) -> bool`（角色对操作人可见）。5.3.7 的"现有角色中操作人不可管理的"= 用户现有角色中不在 `assignable_roles(...)` 返回集合内的部分（该函数只返回**启用**角色；停用角色也应视为"不可管理"而保留，BE-08 注意）。`is_global(ctx)`、`manageable_company_ids(ctx)` 同模块可用。
      - 目标公司判定：`sys_user.company_id`（或 org 的 `company_id`）须在公司级角色 `owner_company_id` 自身或其下属公司内（按目标公司节点 `ancestors` + 自身判定，不能反向：下属公司角色不能给上级公司用户）；`super_admin` 角色仅超管可分配；非超管还要求角色权限 ⊆ 操作人权限、数据范围不超过 `max_rank`、CUSTOM 角色的每个（未删除）组织都在操作人范围内。
    - 规则实现细节：`max_rank` 取操作人启用角色中非 CUSTOM 的最大等级，超管 ALL，仅 CUSTOM 时 SELF；`can_custom` = 超管/ALL 或 `company_ids/org_ids/include_self` 任一非空。CUSTOM 组织范围判定用组织自身的 `company_id/dept_id/created_by` 走 `in_data_scope`；不存在/已删除的组织创建或授权时 400001，越界 403124。授权接口里"与角色现有值相同"的数据范围（非 CUSTOM 同值；CUSTOM 已有的组织）视为未改动不再校验上限（避免历史值卡住编辑，也不构成提权）；权限按"现有中操作人不拥有的 ∪ 提交集合"合并保留。创建公司级角色：`owner_company_id` 缺失 400122；组织不存在或非 company/group 节点 400001；不在 M(op) 403125。集团级角色创建/编辑需超管或 ALL（403125）；`super_admin` 编辑/授权 403122；内置角色（`is_builtin`）删除 403122；可见性不满足一律 404000（先于 403 判定）。校验顺序：可见 → 内置/可编辑 → `version`（409001）→ 业务校验 → 自锁。
    - 乐观锁：`PUT /roles/{id}`、`/grants` 的 `version` 必填，不一致 409001，成功 `version+1`。编辑接口 `name/status/remark` 可选（缺省不改，`remark` 显式传 null 清空）。
    - 自锁（409124）：仅当操作人自己持有该角色（启用）且保存后其所有启用角色并集不再含 `system:role:list` 时触发，`data={"lost_permissions":["system:role:list"]}`；停用角色同理；`confirm_self_lockout=true` 放行。
    - 缓存失效：授权、状态变更、删除均在 `commit` 之后直接 `await authz_service.bump_epoch()`（Redis 异常只记日志，缓存 TTL 兜底），集成验证授权/取消勾选后被授权用户下一次请求即生效（AC-13）。删除角色为逻辑删除并物理清理其 `sys_role_permission/sys_role_org`，编码仍占用，名称可复用。
    - 列表：`name/code` 模糊（转义 `%`/`_`），按 id 升序，`user_count` 只统计未删除用户（一次分组查询，无 N+1）。`/roles/{id}/users` 复用 `data_scope_filter`（`sys_user.company_id/dept_id/created_by`），`roles` 为空数组。
    - 单测（`tests/unit/test_roles_api.py`，22 个，累计 86 个，整套约 76 秒）：AC-13（授权/取消即时生效，菜单随之变化）、AC-14（权限/范围/CUSTOM 越界、保留不拥有的权限、范围降低后不能再升回）、AC-15（普通员工 403001、未登录 401）、AC-16（B 公司看不到/不能分配 A 公司角色，404000/403121）、公司角色下属公司方向、assignable 的二选一/404000/功能权限、列表过滤分页、角色下用户数据范围、权限树 grantable 与 `max_data_scope`、版本冲突、自锁确认、停用 bump epoch、内置/有用户/已删除用户不计数的删除规则、操作日志（Redis `stream:oplog`）。
    - 已验证（`devctl up -d iam` + curl，开发库）：列表、创建、重复编码 409121、权限树、assignable（二选一 400001 / `org_id=1`）、授权、版本冲突 409001、编辑、删除、内置角色删除/修改 403122、未登录 401001，`/docs` 200，OpenAPI 含 6 个新路径。验证后已恢复：admin 密码 `Admin12345` + `must_change_password=true`，临时角色已物理删除（开发库 iam 数据无残留），**未执行 alembic downgrade**；为此清理了开发 Redis db0 的 `auth:*`、`authz:ctx:*` 并 `INCR authz:epoch`（开发环境所有已登录会话需重新登录），并吊销了开发库所有未吊销会话。`stream:oplog` 中留有验证产生的 role 操作事件（BE-10 消费者上线后会入库，属测试数据）。
  - **BE-07 已完成**（iam，F-02）。无迁移。新增：`app/api/v1/orgs.py`（已 include）、`app/schemas/org.py`、`app/services/{org_service,downstream}.py`；`org_repo` 追加 `get_active/list_visible/name_exists/code_exists/has_children/subtree/reparent_descendants`，`user_repo` 追加 `visible_user_exists/count_in_org/ids_in_orgs/reassign_company/get_many_fresh`，`session_repo.revoke_users_sessions` 与 `session_service.revoke_many(session, user_ids, reason) -> dict[uid, list[sid]]`（批量版，同样注册提交后清缓存），`event_service.publish_(users|orgs)_upserted` 批量版改为一次 flush、仅对 `updated_at` 未加载的实例 refresh（避免子树 N 次查询）；`RevokeReason` 增加 `org_disabled`（4.8 的 `revoke_reason` 枚举注释需补充该值，列为 VARCHAR(32) 无需迁移）；`main.py` 注册 `downstream.lifespan_hook`（退出时关闭下游 HTTP 客户端）。
    - 5.2.1~5.2.8 全部按契约实现（均带 `response_model`）。树/选择器在内存中组装（范围内全部未删除节点，≤5000）：父节点不在结果集的节点作为根；`name`（不区分大小写子串）/`status` 过滤返回命中节点 + 其**可见**祖先；`effective_status` 一次批量取祖先状态计算（祖先缺失/已删除视为 disabled）；`options` 的 `include_disabled=false` 按**生效状态**排除（停用节点的后代一并排除），`types` 过滤后父节点不在集合的节点提升为根，`types` 含非法值 → 400001；选择器权限为 7 个码 any-of。
    - 范围与越权：单节点读写统一 `_get_visible`（未删除且 `in_data_scope`，否则 404000）；写操作 `SELECT ... FOR UPDATE` 后校验 `version`（409001），并发两次同版本编辑只有一个成功（有测试）。移动校验顺序：节点可见(404000) → 集团(400114) → version(409001) → **当前上级**在范围内(否则 403101) → 新上级可见(404000) → 自身/后代(400112) → 层级(400110/400111) → 同名(409101)。层级规则补充：dept 的上级为 group 时契约未给错误码，返回通用 400001「部门的上级只能是公司或部门」；company 挂到 dept 下返回 400110。上级未变化的移动为 no-op（返回当前节点，version 不变）。
    - 新增：`company_id` 先写 0 占位 → flush 取 id 后回填 `company_id/dept_id`（公司/集团=自身，部门=上级 `company_id`）；负责人须为数据范围内未删除用户（否则 400001）；唯一约束冲突并发兜底转换为 409101/409102；提交后递增 `authz:epoch`（新增公司/部门会改变 COMPANY_AND_CHILD 等数据范围）。
    - 移动（单事务）：自身用 ORM 更新；后代 `ancestors` 用前缀替换的单条 `UPDATE ... SET ancestors = new_prefix || substr(ancestors, len(old_prefix)+1)`，按目标 `company_id` 分组（公司节点=自身，部门取父节点）；用户 `company_id` 按组织分组 `UPDATE ... WHERE org_id IN (...) AND company_id <> :cid RETURNING id`（只动 company_id 真正变化的用户）。**所有 bulk UPDATE 显式 `updated_at=now()`、`updated_by=操作人`**；之后以 `populate_existing` 重新加载并发布 `org.upserted`（自身+后代各一条）与 `user.upserted`（受影响用户）；提交后 `INCR authz:epoch`。操作日志 summary 含 before/after 与 `affected_orgs/affected_users`。
    - 停用：子树（自身+后代）下全部未删除用户 `session_service.revoke_many(..., org_disabled)` → `commit` → 逐用户 `purge_cache` → `bump_epoch`；仅发布该组织自身的 `org.upserted`；启用不恢复会话。不再单独 `invalidate_user`（epoch 递增已使全部 ctx 缓存失效）。
    - 删除：检查顺序 409103 → 409104 → kb 统计 409105；逻辑删除并 `version+1`，发布 `org.upserted(is_deleted=true)`，提交后递增 epoch；已删除节点 `name` 可复用，`code` 不可（409102）。
    - `app/services/downstream.py`（供 BE-07/BE-08）：`kb_dataset_count_by_dept(dept_id)`、`kb_dataset_count_by_owner(owner_id)`、`open_api_key_count_by_user(user_id)`，开关（`KB_STATS_ENABLED/OPEN_STATS_ENABLED`，默认 false）关闭返回 `None`；开启后失败抛 `BizError(503001)`；`kb_dataset_count_by_owner_safe` / `open_api_key_count_by_user_safe` 失败也返回 `None`（BE-08 影响提示用，`degraded = 任一为 None`）。基于共享库 `InternalClient`（超时取 `INTERNAL_HTTP_TIMEOUT_SECONDS`）。
    - 单测（`tests/unit/test_orgs_api.py`，17 个，累计 103 个，整套约 100 秒）：403001/401、树范围与过滤、选择器与详情 404000、新增（回填/事件/日志/层级与重复/范围/参数）、编辑与 409001、并发编辑、移动子树与用户重算（断言子树组织与受影响用户 `updated_at` 变化且无关行不变、`updated_by`、事件、epoch）、公司含子公司移动、移动校验、子公司管理员（B 节点 404000、移动本公司 403101、本公司内部可移）、停用吊销（会话 org_disabled、他人不受影响、启用不恢复）、状态规则、删除规则与 kb 统计（409105/503001）、downstream 开关与降级。测试复用 `test_roles_api` 的 `env` 夹具。
    - 已验证（`devctl up -d iam` + curl，开发库）：树、新增公司/部门、层级 400001、重名 409101/编码 409102、选择器、编辑、旧 version 409001、移动集团 400114/移到自身下 400112、停用、删除（含 409103）、无 token 401001，OpenAPI 含 orgs 6 条路径。**开发库已恢复**：临时组织（TMP_C/TMP_D）物理删除，admin 恢复为 `Admin12345` + `must_change_password=true`；未执行 downgrade。
  - **BE-08 已完成**（iam，F-03）。无迁移。新增：`app/api/v1/users.py`（已 include）、`app/services/user_service.py`；`app/schemas/user.py` 在 `UserItem/RoleRef` 之后追加 `UserCreate/UserUpdate/UserStatusBody/ResetPasswordBody/AssignRolesBody/UserCreated/PasswordReset/UserImpact`；`user_repo` 追加 `get_active(for_update)/username_exists/mobile_exists/page_users/roles_of_users/apply_user_roles`。5.3.1~5.3.9 全部按契约实现（均带 `response_model`）。
    - 范围与越权：单用户读写统一 `_get_visible`（未删除且 `in_data_scope`，否则 404000），写操作 `FOR UPDATE` 后再校验 `version`（409001）；列表用 `data_scope_filter`（`company_id/dept_id/created_by`）由 service 生成条件传入 repo。`org_id` 筛选 = 该节点 + 全部未删除后代（任意类型）的直属用户；节点不存在或在范围外返回空页（不泄露）。`username` 不区分大小写模糊，`name/mobile` 模糊，均转义 `%`/`_`；按 `created_at desc, id desc`；用户行的角色与组织名各一次批量查询。`UserItem.roles` 含停用角色（不含已删除）。
    - 新增：顺序为组织可见(404000) → `role_ids` 可分配(403121，`ensure_roles_assignable(org_id=)`) → 账号(409111，含已删除) → 手机号(409112) → 密码规则；`password` 缺省/空串则生成 12 位字母数字并仅在响应 `initial_password` 返回；传入密码不合规 400102（`data.errors=[{field:"password",message}]`）。`company_id` = 组织的 `company_id`，`dept_id` = `org_id`，`created_by/updated_by` = 操作人，`must_change_password=true`。`status` 默认 enabled。400120 在三类节点均合法的前提下无触发场景，未使用。唯一约束并发冲突兜底转换为 409111/409112。
    - 编辑：校验顺序 可见 → version → 新组织可见(404000) → 手机号(409112)；改组织重算 `company_id/dept_id`，提交后 `invalidate_user`；总是发布 `user.upserted`。
    - 启停：自己停用 403111 → 内置用户停用 403112 → version；状态不变为 no-op（不升 version、不发事件）。停用走 `revoke_all(user_disabled)` → `commit` → `purge_cache` → `invalidate_user`；启用只 `invalidate_user`（不恢复会话）。重置密码（不升 `version`）：`must_change_password=true`、`password_changed_at=NULL`、`revoke_all(password_reset)`、同样的提交后清理；删除：自己 403111 → 内置 403112，逻辑删除并 `version+1`，`revoke_all(user_deleted)`；均发布 `user.upserted`（删除的 `is_deleted=true`）。账号不可复用，手机号（部分唯一索引排除已删除）可复用。
    - 分配角色：提交集合须全部可分配(403121)；最终集合 = 用户现有角色（含停用）中**不在 `assignable_roles(session, ctx, user.company_id)` 返回集合内**的 ∪ 提交集合，因此超管角色、停用角色、操作人不可见的公司角色都会保留，只对 diff 做增删（`sys_user_role` 物理增删，`org_id`=用户主组织）。自锁检查仅在操作人改自己且非超管时进行，关注 `system:role:list`/`system:user:list`，按最终集合中**启用**角色的权限并集判断，409124 `data.lost_permissions`；`confirm_self_lockout=true` 放行。不改动 `sys_user` 行，故不发布 `user.upserted`；提交后 `invalidate_user`。
    - 操作日志（`oplog_scope`，失败也记 failure）：create `{"after":{username,name,org_id,org_name,mobile,email,status,roles:[名],system_generated}}`、update `{"before","after"}`、status `{"before":{"status"},"after":{"status"}}`、reset_password `{"system_generated","revoked_sessions"}`、assign_role `{"before":[角色名],"after":[角色名]}`、delete `{"before"}`。**摘要中不出现任何密码**（注意共享库脱敏会把键名含 `password` 的值替换为 `******`，所以标记键用 `system_generated`）。
    - 影响提示：`asyncio.gather(downstream.kb_dataset_count_by_owner_safe, downstream.open_api_key_count_by_user_safe)`，任一 None → `degraded=true`（下游开关默认关闭，故开发环境恒为 null/degraded）。
    - 单测（`tests/unit/test_users_api.py`，15 个，累计 118 个，整套约 2 分钟）：无权限 403001/401、AC-10（创建/重复 409111/手机 409112/首次登录须改密/事件/日志无明文）、指定密码与参数校验、带 `role_ids`（403121 无残留）、列表过滤（组织树含下级、模糊、转义、分页、集团管理员/范围外）、AC-11（B 公司用户 7 种直接请求均 404000 且行数据/会话无变化）、编辑与版本冲突、AC-12（自己/admin 403111/403112、停用后 access 401002、refresh 401104、登录 401103、再启用）、删除、影响提示三种降级态、重置密码（会话失效/新旧密码/日志无明文）、分配角色（即时生效、保留超管与停用角色、自锁确认）。测试复用 `test_roles_api` 的 `env` 夹具。
    - 已验证（`devctl up -d iam` + curl，开发库）：列表、创建（返回一次性 `initial_password`）、重复账号 409111、详情、impact（degraded）、编辑、停用、重置密码、分配角色、停用/删除自己 403111、删除后详情 404000、未登录 401001，`/docs` 200，OpenAPI 含 7 个 users 路径。**开发库已恢复**：临时用户 `tmp_user1` 物理删除，admin 恢复为 `Admin12345` + `must_change_password=true`，已吊销全部未吊销会话并清理 Redis `auth:*`、`authz:ctx:*`、`INCR authz:epoch`；未执行 downgrade。
  - **BE-10 已完成**（iam，F-06）。无迁移（表已在 0001 建好）。新增：`app/api/v1/logs.py`（已 include，仅 3 个 GET，无修改/删除路由）、`app/schemas/log.py`、`app/services/log_service.py`、`app/jobs/{__init__,oplog_consumer,log_cleanup}.py`；`log_repo` 追加 `insert_operation_log/get_org_name/page_operation_logs/get_operation_log/page_login_logs/delete_older_than`；`main.py` 的 `lifespan_hooks` 增加 `jobs.lifespan_hook`。新增配置 `LOG_JOBS_ENABLED`（默认 true，已同步 `.env.example`；`false` 时不启动消费者与清理任务，单测 conftest 置为 false 以免干扰读取 `stream:oplog` 的用例）。
    - 入库：`StreamConsumer("stream:oplog", group="iam-oplog")`，handler 收到的是 `OpLogEvent` JSON 本体（共享库注入 `_stream_id`，被 pydantic 忽略）；`INSERT ... ON CONFLICT (event_id) DO NOTHING`（重复事件只入库一次）；入库时按 `company_id` 查 `sys_org.name` 写 `company_name`；各字符串列按表定义截断；`created_by/updated_by = operator_id`。事件非法则抛异常，由消费者重试后进 `stream:dead`。iam 自身操作同样经 `emit_oplog` → Stream，无旁路。
    - 查询：数据权限统一走 `log_repo._scope`（封装 `data_scope_filter`，`company_id/dept_id` 可空列做类型 cast，NULL 不命中，仅 ALL/超管可见；本人列 `created_by`）；详情越权返回 404000。`start_time/end_time` 必填（缺失由全局校验处理器返回 400/400001），无时区的时间按东八区解释，`end < start` 或跨度 > 180 天返回 400001；`operator` 同时模糊匹配姓名/账号（转义 `% _ \`），`result` 限 `success|failure`；排序 `occurred_at desc, id desc`；登录日志用一次联表（`sys_user.name`、`sys_org.name`）取 `user_name/company_name`，无 N+1。
    - 清理：`run_periodic("iam-log-cleanup", 3600, scheduled_cleanup)`，仅东八区 03 点执行；`cleanup_expired_logs()` 按 `LOG_RETENTION_DAYS`（180）分批（5000/批，`OPLOG_BATCH_DELETE`）物理删除登录日志与操作日志。
    - Redis 断开：`emit_oplog` 吞异常，业务照常成功（单测覆盖）；消费者循环遇异常 1 秒后重试，恢复后继续消费。
    - 单测（`tests/unit/test_logs.py`，12 个，累计 130 个）：入库幂等与 company_name、字段截断与非法事件、消费者端到端（真实业务操作 → 日志，含重复投递只入库一次、AC-20，摘要无密码）、Redis 故障业务成功、公司管理员只见本公司及下属（AC-21）与 SELF 范围、过滤/分页/排序、登录日志范围与字段（含账号不存在的记录仅超管可见）、时间范围校验、403/401、路由只读、分批清理。
    - 已验证（`devctl up -d iam` + curl，开发库）：新增并删除临时组织后，`GET /system/operation-logs`（含 `module=org` 过滤）能查到 `org/create`、`org/delete` 两条，详情含 `summary/user_agent/request_id`；`GET /system/login-logs` 可见成功/失败登录；跨度 >180 天 400001；`DELETE` 日志路径 405；OpenAPI 日志路径仅 GET。消费组 `iam-oplog` lag=0、pending=0、`stream:dead` 不存在。
    - 开发环境处理：首次启动消费者前已执行 `DEL stream:oplog`（开发 Redis db0，当时 56 条前序任务自测遗留的测试事件，指向已删除的临时数据），避免测试数据入库。验证中 admin 密码临时改为临时值以登录，结束后已恢复为 `Admin12345` + `must_change_password=true`（因进入时 admin 密码并非 Admin12345，开发库 `sys_user.admin` 的 password_hash 已被覆盖为 Admin12345 的新哈希）；临时组织已逻辑删除（组织删除即逻辑删除，其操作日志按审计要求保留）；日志表未手工删除，**未执行 alembic downgrade**。验证后 iam 已用 devctl 停止。

- 前端（FE-01、FE-02）：
  - 实际依赖版本：react/react-dom 18.3、antd 5.29、@ant-design/icons 5.6、@ant-design/pro-components 2.8、react-router-dom 6.30、@tanstack/react-query 5、axios 1.x、zustand 5、dayjs、lodash-es；dev：vite 8、vitest 5、typescript 5.9（有意不用 7）、eslint 9（flat config）、openapi-typescript 7。注意 pnpm 默认会装到 react 19/antd 6/router 7，已显式固定到基线大版本。
  - 目录：`frontend/src/{api,services,services/types,stores,access,router,utils,pages,components,layouts}`；`@` 别名指向 `src`。路由：`router/routes.tsx`（路由表，meta.perm）、`router/AppRoutes.tsx`（渲染）、`router/guards.tsx`（RequireAuth、RequirePerm、Forbidden）。
  - 类型：`pnpm gen:api` 生成 `src/services/types/{iam,kb,open}.d.ts`（服务未启动则跳过）；生成前先使用手写的 `src/services/types/iam-contract.ts`（按 5.1 契约），后续可替换。
  - token：access/refresh 存 localStorage（`kbp_access_token`、`kbp_refresh_token`），封装在 `api/tokenStore.ts`。baseURL 为 `/api/v1`，业务调用走 `http.get/post/put/patch/delete`（自动解包 `data`），异常统一为 `ApiError(code, message, data, status)`；`skipErrorToast: true` 可关闭自动错误提示（登录、改密已关闭）。
  - 刷新机制：401001 → `refreshAccessToken()` single-flight（共享同一 Promise），用不带拦截器的 `rawClient` 调 `/auth/refresh`，成功后轮换保存两个 token 并重放原请求（仅重放一次，`_retried`）；失败或 401002/401104 → 清 token、硬跳转 `/login?redirect=当前地址`；403002 → 硬跳转 `/change-password`。硬跳转会同时清空内存状态。
  - 权限：`usePermission()` 返回 `can(code | codes, 'any'|'all')`，`<Access code mode fallback>`；`is_super_admin` 直接放行；不判断角色名。
  - 路由守卫：无 token → 登录；首次进入拉取 `/auth/me`（失败显示重试）；`must_change_password` 时只允许 `/change-password`；`meta.perm` 不满足显示 403。登录页、改密页路由尚未实现（`/login` 仅占位，`/change-password` 待 FE-03，FE-04 补完整路由表）。
  - 单测：`api/request.test.ts`（并发 3 个 401001 只刷新一次、刷新失败跳登录、错误码分流）、`access/usePermission.test.tsx`、`utils/error.test.ts`。
- 前端（FE-03、FE-04）：
  - 路由：`router/AppRoutes.tsx` 分三层：`/login`（公开）、`/change-password`（需登录，独立于主布局）、主布局（`RequireAuth` + `BasicLayout`）下的 `/`、`/profile`、`/403`、`/404`、业务路由（`router/routes.tsx` 的 `businessRoutes`，含 meta.perm，M1/M2/M3 页面暂为占位）、`*` → 404。无权限由 `RequirePerm` 在布局内渲染 403 页。
  - 登录：`pages/auth/login`，ProForm `LoginForm`，`onFinish` 返回 Promise 期间按钮自动 loading 防重复提交；登录前 `reset()` 并清 query 缓存；成功后写 token、`loadMe()`；`must_change_password` → `/change-password`，否则回 `redirect`（`utils/redirect.ts` 的 `safeRedirect` 只放行站内路径）。401102 优先用 `data.remaining_seconds` 向上取整分钟，缺失回退后端 message（`pages/auth/login/messages.ts`）。其余失败显示后端 message，登录页使用 `skipErrorToast`，错误以表单内 Alert 展示。
  - 改密：`pages/auth/change-password`，前端规则同 5.1.5（`rules.ts`，给出具体原因）；400101 显示在“当前密码”、400102/400103 显示在“新密码”；成功后 `loadMe()` 并进入首页；页面带“退出登录”。
  - 个人中心：`pages/auth/profile` 展示 me.user 字段与“修改密码”入口。
  - 主布局：`layouts/BasicLayout.tsx`（ProLayout mix 布局），菜单由 me.menus 渲染（`utils/menu.ts`），图标名通过 `components/menuIcons.tsx` 的白名单映射（后端新增图标名需同步追加，未收录则不显示图标）。右上角头像菜单：个人中心、退出登录。`/` 重定向到第一个叶子菜单，没有菜单显示空状态。`components/PageContainerWrapper.tsx` 统一处理加载/错误（重试）/空数据，供 FE-05~08 使用。
  - 单测：`router/guards.test.tsx`（未登录、强制改密、403）、`utils/{menu,redirect}.test.ts`、`pages/auth/login/messages.test.ts`、`pages/auth/change-password/rules.test.ts`。
  - antd peer 警告说明：pro-components 2.8.10 声明 `antd: ^4.24.15 || ^5.11.2`，不含 antd 6。早先警告出现在 pnpm 默认装到 antd 6.7 的时候；固定到 antd 5.29.3 后重新安装已无 unmet peer 警告。结论：只是版本范围声明，不要升级到 antd 6。
  - 端口（用户已确认的变更）：dev server `5174`（`strictPort`，被占用时直接报错不顺延）；proxy：`/api/v1/auth`、`/api/v1/system` → iam `127.0.0.1:8301`，`/api/v1/kb` → kb `8302`，`/api/v1/open-platform`、`/api/v1/open` → open `8303`（chat 8304 预留未配）；可用环境变量 `IAM_URL`、`KB_URL`、`OPEN_URL` 覆盖，`scripts/gen-api.mjs` 使用同一组默认地址。
- 前端（FE-05~FE-08）：
  - 通用：`components/OrgTreeSelect.tsx`（5.2.2，`types` 过滤、单/多选、`isDisabled` 置灰）、`components/UserSelect.tsx`（5.3.1 远程搜索）、`hooks/useOrgOptions.ts`（queryKey `org-options`，组织变更后失效）、`utils/orgTree.ts`（树工具、新增类型限制、移动类型限制、CUSTOM「包含下级」展开）、`utils/lockout.ts`（409124 二次确认后带 `confirm_self_lockout=true` 重提，用户取消抛 `LockoutCancelled` 静默）、`utils/notify.ts`。写操作接口（表单类）用 `skipErrorToast`，由页面 `notifyError` 提示后端 message；停用/删除等确认弹窗内的操作走默认拦截器提示。
  - 组织：`pages/system/org`，树形 ProTable（展开全部，空 children 已剔除）；新增时类型按上级限制：集团→公司；公司→公司/部门；部门→部门；编码编辑时只读；移动时自身、后代及类型不允许的节点置灰；停用/删除均二次确认，生效状态为停用而自身启用时标注“上级已停用”。
  - 用户：`pages/system/user`，左侧组织树（5.2.2）+ ProTable；停用/删除前调 5.3.9 展示影响提示（失败按降级文案）；对自己与 `is_builtin` 不显示停用/删除；新增/重置密码支持系统生成并在弹窗一次性展示（复制）；分配角色用 5.4.2（`user_id`），409124 二次确认重提，操作自己成功后 `loadMe()`。
  - 新增用户表单（契约变更后）：选定所属组织后用 `GET /roles/assignable?org_id=` 拉取可选角色，组织变更时清空已选角色，创建请求带 `role_ids`；`roleApi.assignable` 入参为 `{user_id}` 或 `{org_id}` 二选一。
  - 角色：`pages/system/role`，`editable=false` 隐藏编辑/授权/删除；授权抽屉的权限树用 `checkStrictly`（菜单与按钮独立勾选，符合 AC-13“有菜单无按钮”），`grantable=false` 节点置灰且已有的保持勾选，**提交时只含可授予项**（不可授予的由后端合并保留）；数据范围按 `max_data_scope` 等级与 `can_custom` 置灰；CUSTOM 选组织 + “包含下级”勾选，提交时展开为具体 id，非 CUSTOM 提交空数组；403123/403124 友好提示；409124 二次确认。`grantLogic.ts` 为纯函数便于单测。
  - 日志：`pages/system/log/{operation,login}`，时间范围默认近 7 天、最长 180 天、不可选未来（`timeRange.ts`，RangePicker `disabledDate` + 请求前校验）；`dict.ts` 为 5.8 枚举中文映射（未知值回退原值；登录失败原因映射契约完整枚举 `bad_credentials`、`locked`、`user_disabled`、`org_disabled`，未知值回退 `fail_message`）；详情抽屉 `summary.ts` 解析 before/after、added/removed 为对比表，未知结构以 JSON 展示。
  - 菜单图标白名单（`components/menuIcons.tsx` 的 `MENU_ICON_NAMES`，后端 seed 的 `icon` 必须取自此清单）：ApartmentOutlined、ApiOutlined、AppstoreOutlined、AuditOutlined、CloudServerOutlined、DatabaseOutlined、FileSearchOutlined、FileTextOutlined、HistoryOutlined、KeyOutlined、LoginOutlined、ProfileOutlined、ReadOutlined、SafetyOutlined、SettingOutlined、TeamOutlined、UserOutlined。注意：tech-design.md 第 7 节权限总表没有图标列，现仅 5.1.4 示例出现 DatabaseOutlined、SettingOutlined；其余是前端按菜单语义给出的建议映射：知识库 DatabaseOutlined；开放平台 ApiOutlined；我的 API 密钥 KeyOutlined；调用日志 FileTextOutlined；API 文档 ReadOutlined；系统管理 SettingOutlined；组织管理 ApartmentOutlined；用户管理 UserOutlined；角色管理 TeamOutlined；知识库管理 AppstoreOutlined；API 密钥审计 AuditOutlined；模型配置 CloudServerOutlined；日志（目录）FileSearchOutlined；操作日志 HistoryOutlined；登录日志 LoginOutlined。按钮类权限无需图标。
  - 图标核对：tech-design.md 第 7 节“图标”列的 15 个取值均在 `MENU_ICON_NAMES`（17 项）白名单内，无需调整；超管放行仍按 `is_super_admin`，401102 仍优先 `remaining_seconds` 并保留 message 回退。
  - 联调记录（iam 8301 + `pnpm dev` 5174，Playwright 走通）：未登录访问受保护页 → `/login?redirect=` → 错误密码提示“账号或密码错误” → admin 登录进入强制改密页 → 访问 `/profile` 被重定向回改密页 → 弱密码给出具体原因 → 改密成功进入主布局（`/` 跳到第一个菜单 `/kb/datasets`，侧边菜单“知识库/开放平台/系统管理”及一级图标正常）→ 个人中心 → 刷新仍保持登录 → 退出登录回 `/login`（token 已清空）。`pnpm gen:api` 已生成 `src/services/types/iam.d.ts`（目前后端只有 auth 接口）。截图在 `frontend/test-results/`（不进 git）。
  - 与后端 OpenAPI 对比后手写类型的修正：`MeUser.org_name` 可空；`MenuNode.path` 可空（取不到 path 时布局用 code 兜底）、`children` 可缺省。`company_id` 后端为非空，前端类型仍按可空兼容。
  - 联调中修复的前端问题：① 退出登录后跳转登录页带上了 `redirect=/profile`（状态清空先触发了路由守卫），改为先跳转再清状态；② ProTable 在接口报错时抛未捕获异常，已为各 ProTable 加 `onRequestError`（提示由拦截器统一处理）；③ 全局 `renderEmpty` 统一为“暂无数据”（ProTable 空态原先显示英文 No data）；④ 日志页时间范围搜索项加宽。
  - 联调记录（FE-05~FE-08，iam 8301 + Playwright，截图 `frontend/test-results/20-*` 到 `87-*`）：
    - 组织：新增子公司 A/B、部门、子部门（集团下只出现“公司”、部门下只出现“部门”）；编辑（编码只读）；同名 409101 提示；移动（自身及后代、类型不允许的节点置灰）；停用/启用（子树出现“上级已停用”标签）；删除空节点成功，有下级时 409103 提示。
    - 用户：新增用户（选组织后按 `org_id` 拉可选角色并带 `role_ids`，换组织清空角色）、系统生成密码一次性弹窗、手动密码、账号/组织校验、409111 重复账号、编辑（账号只读）、停用前影响提示（kb 未部署时走降级文案）、重置密码、分配角色、按左侧组织筛选、删除；admin 行不显示停用/删除。
    - 角色：新增公司级角色、授权抽屉（权限树 + 数据范围 + CUSTOM 多选 + “包含下级”展开）、保存后重开回显一致、编辑（编码只读）、查看角色用户、删除；内置角色按 `editable` 隐藏编辑/授权/删除。
    - 日志：操作日志/登录日志列表、详情抽屉（角色授权为前后对比表，删除类仅 `before` 对象按字段展示，`data_scope` 显示中文）。
    - A 公司管理员（company_admin）登录：只看到 A 公司及其部门的组织/用户，下拉与左侧树无集团和 B 公司；菜单无“模型配置”，直接访问 `/system/models` 显示 403；日志按范围为空。
  - 联调中修复的前端问题：① `modal.confirm` 的 `onOk` 在接口报错（如 409103）时抛未捕获异常，已在组织/用户/角色页统一捕获（提示由拦截器处理）；② 上级不可见的节点（子公司管理员的本公司节点）隐藏“移动”（对应 403101）；③ 日志详情中 `data_scope` 显示中文、仅 `before` 的摘要按字段展示；④ 组织/用户表格列宽。UserItem 的 `org_name`、`roles` 与后端 OpenAPI 对齐为可空/可缺省。
  - 联调注意：授权抽屉打开时不要用 Esc 收起下拉（会关闭抽屉）；antd 两个汉字的按钮文字带空格（如“保 存”），自动化脚本用类名选择器而非文字。
  - 契约更新后的前端调整（TQ-06/TQ-07，仅单测验证，未联调）：
    - 组织：集团下可新增“公司/部门”（`allowedChildTypes('group')`），移动时部门可选集团为新上级；**（已被后续契约取代）**前端不再自行推算受保护节点，见下一条；后端 403102 提示由拦截器/删除错误处理直接展示后端 message。删除组织遇 409106 时弹窗列出 `data.roles` 与 `total`（超过列出数量时提示“等 n 个”）；`orgApi.remove` 改为 `skipErrorToast`，由页面分流 409106 与其他错误。
    - 日志摘要（`summary.ts`）按 5.8 结构约定解析：新建仅 after、删除仅 before、编辑 before/after 逐字段对比（常见字段与状态/角色类型/组织类型值显示中文）；组织删除的 `custom_role_refs_removed` 以附加行展示；授权含 `permissions`/`custom_orgs` 的 added/removed 与 `data_scope`；分配角色为角色名数组前后对比；审计查看 `document_name` 以键值展示；其余未知结构 JSON。
  - 组织保护（5.2.0/5.2.1 定稿，仅单测验证，未联调）：删除了前端自行推算的 `protectedOrgIds`。“停用”“删除”按钮直接按组织管理树节点的 `disable_blocked_reason`、`delete_blocked_reason` 置灰（非 null 即不可用），并用 Tooltip 展示文案，不隐藏（`getBlockedReason` + 页面 `renderGuarded`）；已停用节点的“启用”不受限；集团节点后端未给文案时前端兜底置灰“集团节点不能移动、停用或删除”。任何组织变更（新增/编辑/移动/停用/启用/删除）后都会重新拉取树以同步标记。请求仍返回 403102（管辖根，停用/删除）、403103（本人组织链，仅停用）时展示后端 message；409106 弹窗展示角色名单。`iam-contract.ts` 的 `OrgNode` 增加这两个可选字段。新增组织类型限制：集团→公司/部门，公司→公司/部门，部门→部门。“移动”按钮仍仅在上级可见时显示（对应 403101）。
  - 列表错误状态（BUG-12）：所有 ProTable 列表页（组织、用户、角色、角色用户抽屉、操作日志、登录日志）的 `request` 统一用 `hooks/useTableError` 的 `wrap` 包装：接口失败不再抛出，返回空数据并记录错误，通过 `locale.emptyText` 显示 `components/TableErrorState`（“加载失败”+ 后端 message + “重试”按钮，重试即 `actionRef.reload()`），不再保留旧数据；成功后自动清除错误态。错误 toast 仍由拦截器弹出。测试环境补了 `window.matchMedia` 的 jsdom polyfill（`src/test-setup.ts`）。
  - 只读标记 `manageable`（5.2.0a，仅单测验证，未联调）：`OrgNode`、`OrgOption`、`UserItem` 增加可选 `manageable`，缺省视为 true（`isManageable`）。组织行与用户行 `manageable=false` 时操作列只显示“只读”，不渲染任何管理按钮；`OrgTreeSelect` 新增 `disableUnmanageable`，用作写入目标时置灰只读节点——已用于新增组织的上级、移动目标、新增/编辑用户的所属组织、角色 CUSTOM 数据范围的组织多选；筛选用途（如用户页左侧树）不置灰。授权抽屉“数据范围”下方固定显示提示“用户拥有多个角色时，数据范围取所有启用角色的并集，并对该用户拥有的所有功能生效。”。写操作收到 403001 时展示后端 message（默认拦截器提示/`notifyError`，已加单测）。
  - 单测：`pages/system/log/dict.test.ts`、`utils/{orgTree,lockout}.test.ts`、`pages/system/role/grantLogic.test.ts`、`pages/system/role/components/GrantDrawer.test.tsx`（渲染层验证置灰与保持勾选）、`pages/system/log/{timeRange,summary}.test.ts`、`pages/system/user/impact.test.ts`。

- **M1 第 1 轮测试缺陷修复与组织规则变更（iam + platform_common，已实现）**：
  - **组织保护规则（BE-07，5.2.0）**：新增 `app/services/org_protection.py`。`compute(session, op)` 返回不可变的 `OrgProtection(unrestricted, roots, own_chain)`：超管或 `ctx.data_scope.all` → 不计算管辖根；否则按操作人**每个启用且未删除角色**分别取管辖根再并集（COMPANY/COMPANY_AND_CHILD → `op.company_id`；DEPT/DEPT_AND_CHILD → `op.org_id`；CUSTOM → 勾选组织中"祖先链上没有该角色其他勾选组织"的节点，忽略已删除组织；SELF/ALL 无）；`own_chain = ctx.org_path`。`disable_error/delete_error`（顺序：集团 400114 → 管辖根 403102 → 本人链 403103，删除不含 403103）同时驱动树节点的 `disable_blocked_reason/delete_blocked_reason`（已停用节点的停用提示恒为 null）与 `PUT .../status`、`DELETE` 的请求时校验，二者同源。组织树与单节点 `GET /system/orgs/{id}` 返回提示字段；其余接口（创建/编辑/移动/停用/删除的响应）省略为 `null`。
  - **部门挂集团下（BUG-04）**：`_check_hierarchy` 允许部门的上级为集团/公司/部门（创建与移动共用）；集团本部部门 `company_id` = 集团节点 id，移动时子树 company_id 沿用原有重算逻辑。
  - **删除组织（BUG-03）**：检查顺序 409103 → 409104 → 409106（`data={"roles":[最多 10 个名称],"total":n}`，仅统计未删除的公司级角色）→ 409105；通过后在同一事务内物理删除 `sys_role_org` 中该组织的引用，操作日志 summary 增加 `custom_role_refs_removed`（无引用时不含该键）。删除组织提交后**一律** bump epoch（比"有移除时才 bump"更保守，组织删除本身也会改变上下文计算）。
  - **no-op（BUG-02 配套）**：停用/启用状态未变化、移动到当前上级：校验 version（409001）后直接返回当前节点，不写操作日志、不发事件、不吊销会话、不 bump epoch。为此 `oplog_scope` 的 `OpLogHandle` 增加 `suppress` 属性（成功结束且 `suppress=True` 时不入流；失败仍记录，向后兼容）。顺序：400114 → 保护规则（仅"未停用→停用"时）→ version → no-op。`revoke_reason=org_disabled` 早已落实（`RevokeReason.ORG_DISABLED`），无迁移。
  - **共享库（BE-03，向后兼容）**：①`data_scope_filter` 列参数类型放宽为 `SQLColumnExpression[int] | SQLColumnExpression[int | None]`（可直接传 ORM 属性，含可空列），iam `log_repo` 中的 `cast` 已删除，语义不变；②`auth/runtime.py` 增加 `set_context_loader(loader|None)` / `get_context_loader()`，`fetch_context_from_iam` 优先使用已注册 loader，未注册走原 HTTP 实现；iam 在 lifespan 钩子 `authz_service.lifespan_hook` 注册 `load_context_locally`（独立会话直接计算并回写缓存），退出时恢复默认，不再回调自身 `/internal/v1/authz/contexts/{uid}`。
  - **BUG-01 并发登录耗尽连接池**：根因是请求 session 读用户后一直占连接（bcrypt、登录日志期间也占），`_record_login` 又另取一个，30 路并发互相等待到 30s 超时。修复：`login` 读取用户后立即 `session.close()`（对象已加载，仍可读属性），bcrypt 与日志写入期间不占连接，任一时刻最多 1 个连接；停用/组织停用/锁定分支同样先 close 再写日志。刷新、改密路径只用一个请求 session，不存在二次取连接。**连接池配置**：`BaseServiceSettings` 新增 `DB_MAX_OVERFLOW=10`、`DB_POOL_TIMEOUT_SECONDS=10`（原为 SQLAlchemy 默认 30s）、`DB_POOL_RECYCLE_SECONDS=1800`；池耗尽（`sqlalchemy.exc.TimeoutError`）统一映射 503001 而非 500；iam `.env.example` 已同步。
  - **BUG-06 登录锁定原子化**：用 Redis Lua 在一次调用内完成"检查锁 → INCR 失败计数（首次设窗口 TTL）→ 计数超过上限则落锁并清计数"，每个请求拿到唯一的尝试序号，只有序号 ≤ `LOGIN_MAX_FAILURES` 的请求才会校验密码；第 5 次失败立即落锁（序号唯一，只会有一个请求触发）；密码正确即清计数。因此 12 路并发错误密码恰好 5 个返回 401101、其余 401102。副作用：同一账号同时在途的登录请求超过上限（默认 5）时，超出部分即使密码正确也会被判定为锁定（先占位后校验的固有取舍，正常使用不会出现）。
  - **BUG-05 超大整数/NUL 字符**：在共享库层统一处理，不改各接口。①新增 `platform_common/input_guard.py`（纯 ASGI 中间件，位于请求上下文中间件之内）：路径/查询串含 NUL（含 `%00`）或 JSON 请求体任意键值含 NUL（`\u0000`）→ 400001（`data.errors` 为"参数包含非法字符"）；请求体读入后原样回放，超过 2MB 不检查；②`app_factory` 增加 `DBAPIError` 处理器：SQLSTATE 22xxx / asyncpg `DataError`（BIGINT 溢出、非法编码）→ 400001（"参数值超出允许范围"），连接类错误 → 503001，其余 → 500；`RedisError` → 503001。该两层覆盖路径参数、查询参数、JSON 字段的 19 个入口。
  - **BUG-07 入库脱敏**：`log_service.ingest_oplog` 写库前对 `summary` 再执行 `mask_sensitive`（与发送端同一规则，入库端兜底）。
  - **BUG-08**：`authz_service.current_epoch` 在 Redis 异常时抛 `BizError(503001)`；内部授权接口因此返回 503001（原为未处理异常 500）。
  - **BUG-09**：①`StreamConsumer` 默认 `block_ms` 由 5000 降为 2000（须小于 redis-py 默认读超时 5s，原先两者相等导致空闲时每 ~8s 一次 `TimeoutError`），并把 `redis.exceptions.TimeoutError` 视为正常空闲（DEBUG），真实连接错误仍报 ERROR；②`init_redis` 连接池增加 `health_check_interval=15`、`socket_timeout=5`、`socket_connect_timeout=3`、对 `ConnectionError` 指数退避重试 2 次，Redis 重启后池内旧连接自动重连，不再出现恢复后首个请求 503。
  - **BUG-10**：`get_auth_context` 第 3 步在会话存在后解析会话 JSON，`user_id` 必须等于令牌 `sub`，否则 401002（会话值缺失 user_id / 非 JSON 同样判失效）。**对 M2/M3 的影响**：写入 `auth:sess:{sid}` 的只有 iam（`{"user_id","created_at"}`），无需改动；共享库测试辅助已同步。
  - **BUG-11**：`ChangePasswordRequest.new_password` 去掉 `min_length=1`，空串走 service 的规则校验 → 400102，`data.errors` 为中文具体原因。
  - **测试**：iam `tests/unit/test_org_protection.py`（AC-74 全部场景、CUSTOM 多勾选与嵌套、多角色并集、停用角色、超管/ALL、树提示与请求校验同源、集团下建/移部门、409106、CUSTOM 引用清理与 epoch/日志、no-op）、`test_hardening.py`（极小连接池下并发登录、并发锁定恰好 5 次、入库脱敏、Redis 故障 503、sub/sid、空新密码、本地 loader）；共享库 `tests/test_hardening.py`（NUL 拦截、BIGINT 溢出、池耗尽/Redis 异常 503、oplog suppress、context loader、消费者空闲超时）与 `test_auth_deps.py`（sub/sid 归属）。
- **M1 第 2 轮：PRD v0.4 规则落地（iam + platform_common，已实现）**：
  - **`validate_for_runtime()`（BE-02）**：`BaseServiceSettings.validate_for_runtime()` 在 `create_app` 最早调用（失败记 CRITICAL 并抛 `RuntimeError`，进程拒绝启动）：`APP_ENV` 不在 `{"dev","test"}` 时，`INTERNAL_API_TOKEN` 为开发默认值或短于 32 位即拒绝，提示需覆盖 `INTERNAL_API_TOKEN`。默认值提取为常量 `DEFAULT_INTERNAL_API_TOKEN`。iam 的 `Settings` 重写：非 dev/test 且 `SEED_ADMIN_PASSWORD` 仍为默认值时仅告警。
  - **SELF 只读特例（5.2.0a，BE-07/08/09）**：新增 `app/repositories/scope.py`，把两种条件集中在 iam repository 层（共享库 `data_scope_filter` 语义不变）：`manage_user_filter/manage_org_filter`（原规则）、`visible_user_filter/visible_org_filter`（管理范围 OR 特例：仅持 SELF 且无全局范围时追加 `sys_user.id = ctx.user_id` / `sys_org.id IN ctx.org_path`），以及内存版 `user_manageable/user_visible/org_manageable/org_visible`。用户列表/详情、组织树/选择器/详情、`roles/{id}/users` 用可见范围；所有写接口及写前校验（组织：上级/编辑/移动的节点、当前上级、新上级/停用/删除；用户：目标组织/编辑/启停/重置密码/分配角色/删除/`impact`；负责人校验；`roles/assignable` 的 user_id/org_id；角色 CUSTOM 组织校验）只用管理范围。完全不可见 → 404000；可见但不可管理 → 403001（在 5.2.0 保护规则之前）。`assignable` 的 user_id/org_id 命中"可见不可管理"仍返回 404000（该接口只认管理范围，属读接口，不暴露管理意图）。
  - **`manageable` 标记**：`OrgNode`、`OrgOption`、`UserItem` 新增 `manageable: bool`（默认 true；写接口响应恒为 true）。`manageable=false` 的节点 `disable_blocked_reason/delete_blocked_reason` 为 null，保护规则只对可管理节点生效。SELF 与其它范围并存时按行区分（部门内可管理，组织链上其余节点只读）。
  - **账号大小写（4.2）**：现有实现已区分大小写（唯一约束按原值，登录按原值匹配，锁定计数按原值），无需改动；补单测：`lisi` 存在时可新增 `LiSi`、再建 `lisi` → 409111、`LISI` 登录 401101。
  - **测试**：iam `tests/unit/test_self_scope.py`（AC-75 用户/组织只读与 403001、`assignable` 管理范围、混合角色按行 manageable；AC-76 并集与功能来源无关、停用角色后收缩；大小写）；共享库 `tests/test_hardening.py` 增加 `validate_for_runtime` 与 `create_app` 拒绝启动用例。
