# M3 开放检索 技术方案（open 服务 + 生产部署）

- 关联：`./prd.md`（v0.4）F-17 ~ F-19，AC-52 ~ AC-62、AC-70 ~ AC-73；总体方案 `./tech-design.md`；共享库 `./tech-design-m1.md` 3.2；kb 内部接口 `./tech-design-m2.md` 5.9
- 状态：草稿
- 本分册覆盖：BE-24 ~ BE-29、FE-18 ~ FE-22
- 前置：M1 完成；联调开放检索需要 M2 的 BE-21、BE-22

## 1. 范围

| 功能点 | 覆盖 | 说明 |
|---|---|---|
| F-17 | ✅ | 个人密钥（全部可访问 / 指定知识库）、状态计算、管理员审计（停用、删除） |
| F-18 | ✅ | `POST /api/v1/open/datasets/{dataset_id}/retrieve`，API 文档页 |
| F-19 | ✅ | 调用日志（异步入库）、按密钥每分钟限流、近 7 天统计、180 天保留 |
| 部署 | ✅ | 后端多服务镜像、前端 Nginx 镜像、生产 compose |

## 2. open 服务结构

```
backend/services/open/
  main.py  .env.example  alembic.ini  alembic/versions/0001_init_open.py
  app/
    core/config.py
    models/ api_key.py api_key_dataset.py call_log.py ref.py
    schemas/ api_key.py call_log.py audit.py retrieve.py
    repositories/ api_key_repo.py call_log_repo.py ref_repo.py
    services/ api_key_service.py key_status.py key_auth.py rate_limit.py retrieve_service.py
              audit_service.py call_log_service.py kb_client.py
    api/v1/ api_keys.py call_logs.py audit.py open_retrieve.py
    api/internal/ stats.py
    jobs/ call_log_consumer.py ref_sync.py cleanup.py
  tests/unit/
```

配置：

| 配置项 | 默认 | 说明 |
|---|---|---|
| PORT | 8303 | |
| API_KEY_PEPPER | 开发用固定串 | HMAC 密钥，生产必须覆盖；更换会使全部密钥失效 |
| API_KEY_CACHE_SECONDS | 300 | 密钥记录缓存（变更时主动删除） |
| KB_RETRIEVAL_URL | `http://127.0.0.1:8302` | 可指向 kb 的"检索组"实例 |
| OPEN_RETRIEVE_TIMEOUT_SECONDS | 15 | 调 kb 内部检索超时 |
| CALL_LOG_RETENTION_DAYS | 180 | |
| INVALID_KEY_LOG_PER_IP_PER_MIN | 20 | 无法识别密钥的日志按 IP 采样（TQ-04） |
| REF_RECONCILE_INTERVAL_SECONDS | 600 | |

open 进程 lifespan 内启动：`stream:open.call_logs` 消费者（批量入库）、`stream:iam.events` 消费者（`open-ref-sync`，维护 `user_ref`/`org_ref`）、每日清理任务。

## 3. 关键设计

### 3.1 密钥格式与存储
- 明文：`kb-` + 40 位 base62 随机串（`secrets`），共 43 位。
- 存储：`key_hash = HMAC-SHA256(API_KEY_PEPPER, 明文)`（hex）；`key_prefix` = 明文前 7 位（如 `kb-AbCd`）；掩码展示 `kb-AbCd****`。
- 明文只出现在创建与重新生成接口的响应中，不写日志、不写操作日志。

### 3.2 密钥状态（F-17 规则 10）
计算优先级（`key_status.compute(key, owner_ctx, accessible_count)`）：

| 顺序 | status | 中文 | 条件 | 调用时返回 |
|---|---|---|---|---|
| 1 | `admin_disabled` | 已被管理员停用 | 存储状态 | 403601 |
| 2 | `disabled` | 已停用 | 存储状态 | 403601 |
| 3 | `owner_unavailable` | 创建人不可用 | 创建人 AuthContext 为空 / `usable=false` / 无 `openapi:apikey:manage` | 403601 |
| 4 | `expired` | 已过期 | `expires_at <= now` | 403602 |
| 5 | `no_dataset` | 无可检索知识库 | 当前可检索知识库数 = 0 | 不拦截（对具体知识库返回 404601） |
| 6 | `enabled` | 启用 | | |

- 列表中的 `status` 为计算值；`stored_status`（`enabled`/`disabled`/`admin_disabled`）另行返回供前端判断按钮。
- **`admin_disabled` 是终态**（PRD F-17 规则 9、Q-12/A-27：管理员只能停用/删除，不能启用；创建人不能自行启用 → 系统中没有任何人能把它恢复为启用）。因此存储状态为 `admin_disabled` 的密钥，创建人只能**查看、查看可检索名单、查看调用日志、删除**；编辑、重新生成、启用/停用一律拒绝（矩阵见 5.1.0）。创建人如需继续使用开放检索，应新建密钥；管理员若要彻底禁止某人使用，应收回其 `openapi:apikey:manage`（见第 10 节风险）。
- 当前可检索知识库：调 kb `POST /internal/v1/access/accessible-datasets`（`user_ids=[创建人]`，指定模式时带 `dataset_ids`）。列表接口对同一页中的创建人批量调用一次。

### 3.3 开放检索鉴权链（`key_auth.py` + `retrieve_service.py`）

```
1. 读 Authorization: Bearer <key>；缺失/格式不符                          → 401601 KEY_INVALID
2. hash → Redis open:key:{hash}（未命中查库并缓存；不存在缓存 "null" 60s）
   不存在/已删除                                                        → 401601 KEY_INVALID
3. 存储状态 disabled/admin_disabled                                     → 403601 KEY_DISABLED
4. load_auth_context(created_by)：None/不可用/无 openapi:apikey:manage     → 403601 KEY_DISABLED
5. expires_at <= now                                                   → 403602 KEY_EXPIRED
6. ip_whitelist 非空且 client_ip 不匹配                                  → 403603 IP_NOT_ALLOWED
7. 限流：INCR open:rl:{key_id}:{yyyyMMddHHmm}（首次 EXPIRE 120）> 上限   → 429601 RATE_LIMITED
8. 参数校验                                                             → 400001 INVALID_PARAMS
9. 指定模式且 dataset_id 不在指定集合                                     → 404601 DATASET_NOT_FOUND
10. 调 kb /internal/v1/datasets/{id}/retrieve（user_id=创建人, source=open_api）
    kb 404000 → 404601；kb 409303/503301 → 503601 MODEL_UNAVAILABLE；
    kb 不可达/超时 → 503001 SERVICE_UNAVAILABLE；kb 400001 → 400001
11. 成功返回；任一出口都 XADD stream:open.call_logs（第 1~2 步失败的按 IP 采样）
```

- 第 4 步与第 10 步都基于创建人**当前**的 AuthContext 与 kb 当前分配关系，因此"移除分配、停用账号、收回权限"均即时生效（AC-54、AC-70、AC-71、AC-73）。
- `last_used_at`：成功调用后若 `SET open:lastused:{key_id} NX EX 60` 成功则异步更新。
- 密钥记录缓存在以下操作后**同步删除**：编辑、启停、管理员停用、重新生成（删旧哈希）、删除。

### 3.4 调用日志
- 生产：检索请求结束时 XADD `stream:open.call_logs`（字段见 4.3），不等待入库。
- 消费：open 进程内 `StreamConsumer(group=open-calllog, batch=200)` 批量 `INSERT ... ON CONFLICT (request_id) DO NOTHING`。
- 清理：每日分批物理删除 180 天前的记录（保留期策略）。
- 近 7 天统计：`SELECT api_key_id, count(*), count(*) FILTER (WHERE result <> 'success') ... WHERE api_key_id = ANY(:ids) AND created_at >= now() - interval '7 days' GROUP BY api_key_id`（索引 `(api_key_id, created_at)`）。

---

## 4. 数据模型（schema `open`）

迁移 `0001_init_open`：`CREATE SCHEMA IF NOT EXISTS open` + 全部表；downgrade 逐表 `DROP TABLE`，保留空的 `open` schema（`alembic_version` 位于该 schema 内，与 iam 一致）。

### 4.1 `open.api_key`（受数据权限控制：**是**（审计）；本人列 created_by；本人管理按 created_by = 当前用户，不看数据范围）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| name | VARCHAR(50) | NOT NULL | | `uq (created_by, name) WHERE is_deleted=false` |
| description | VARCHAR(200) | NULL | | |
| key_prefix | VARCHAR(16) | NOT NULL | | |
| key_hash | CHAR(64) | NOT NULL, UNIQUE | | |
| scope_type | VARCHAR(16) | NOT NULL | 'all' | `all` / `selected` |
| expires_at | TIMESTAMPTZ | NULL | | NULL = 永不过期 |
| ip_whitelist | TEXT[] | NOT NULL | '{}' | 规范化后的 IPv4 / CIDR |
| rate_limit_per_min | INT | NOT NULL | 60 | 1~600 |
| status | VARCHAR(16) | NOT NULL | 'enabled' | `enabled` / `disabled` / `admin_disabled` |
| admin_disabled_by | BIGINT | NULL | | |
| admin_disabled_at | TIMESTAMPTZ | NULL | | |
| last_used_at | TIMESTAMPTZ | NULL | | |
| company_id | BIGINT | NOT NULL, INDEX | | 创建人创建时的所属公司 |
| dept_id | BIGINT | NOT NULL, INDEX | | 创建人创建时的组织节点 |
| version | INT | NOT NULL | 1 | |

索引：`ix (created_by) WHERE is_deleted=false`。

### 4.2 `open.api_key_dataset`（否；关联表，物理删除）
`api_key_id`、`dataset_id`；`uq (api_key_id, dataset_id)`。

### 4.3 `open.api_call_log`（受数据权限控制：**是**；本人列 created_by = 密钥创建人，无法识别密钥时为 0）
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| request_id | VARCHAR(64) | NOT NULL, UNIQUE | 幂等 |
| api_key_id | BIGINT | NULL | 无法识别时为空 |
| key_name | VARCHAR(50) | NULL | 调用时快照 |
| key_prefix | VARCHAR(16) | NULL | 无法识别时取请求中前 7 位（若格式匹配），否则空 |
| company_id | BIGINT | NULL, INDEX | 密钥的 company_id；无法识别为空（仅 ALL 可见） |
| dept_id | BIGINT | NULL, INDEX | |
| dataset_id | BIGINT | NULL | 请求路径中的知识库 ID（可能无效） |
| dataset_name | VARCHAR(50) | NULL | 成功时快照 |
| query | TEXT | NULL | 原文（参数非法时截断 2000 字） |
| result_count | INT | NOT NULL | 0 |
| latency_ms | INT | NOT NULL | |
| result | VARCHAR(32) | NOT NULL | `success` / `key_invalid` / `key_disabled` / `key_expired` / `ip_not_allowed` / `dataset_not_found` / `invalid_params` / `rate_limited` / `model_unavailable` / `service_unavailable` / `internal_error` |
| error_code | INT | NULL | |
| client_ip | VARCHAR(64) | NULL | |
| called_at | TIMESTAMPTZ | NOT NULL | |

索引：`ix (api_key_id, called_at DESC)`、`ix (created_by, called_at DESC)`、`ix (company_id, called_at DESC)`、`ix (called_at)`。

### 4.4 `open.user_ref` / `open.org_ref`（否；iam 只读副本，结构同 kb，见 M2 4.9）

---

## 5. 接口契约（open）

### 5.0 open 专属错误码

| code | error_type | message |
|---|---|---|
| 401601 | KEY_INVALID | 密钥缺失或无效 |
| 403601 | KEY_DISABLED | 密钥已停用 |
| 403602 | KEY_EXPIRED | 密钥已过期 |
| 403603 | IP_NOT_ALLOWED | IP 不在白名单 |
| 404601 | DATASET_NOT_FOUND | 知识库不存在或未授权 |
| 429601 | RATE_LIMITED | 调用超限，请下一分钟再试 |
| 503601 | MODEL_UNAVAILABLE | 模型服务不可用 |
| 400601 | — | 所选知识库不在您的可访问范围内（`data={"dataset_ids":[..]}`） |
| 400602 | — | 过期时间必须晚于当前时间 |
| 400603 | — | IP 白名单格式不正确或超过 20 条 |
| 400604 | — | 调用日志查询时间跨度不能超过 90 天 |
| 403604 | — | 密钥已被管理员停用，无法启用（5.1.5 状态变更） |
| 403605 | — | 密钥已被管理员停用，无法修改（5.1.4 编辑、5.1.6 重新生成） |
| 409601 | — | 密钥名称已存在 |

开放检索接口（5.4）还会返回 3 个通用错误码。**message 与共享库 `CommonErrors` 完全一致，不另起文案**（API 文档页按此展示，外部系统看到的就是这两句）：

| code | HTTP | error_type | message（固定） | 触发 |
|---|---|---|---|---|
| 400001 | 400 | INVALID_PARAMS | 参数不合法 | 参数校验失败（`data.errors` 指出字段）；含 path 中 `dataset_id` 非整数、body 非合法 JSON |
| 503001 | 503 | SERVICE_UNAVAILABLE | 依赖服务暂不可用，请稍后重试 | 调 kb 检索不可达/超时（`OPEN_RETRIEVE_TIMEOUT_SECONDS`）、Redis/数据库不可用或连接池耗尽、加载创建人权限上下文时 iam 不可用；可重试 |
| 500000 | 500 | INTERNAL_ERROR | 系统繁忙，请稍后重试 | 未预期异常（不暴露堆栈）；可稍后重试，持续出现请联系平台管理员并提供 `request_id` |

- 开放检索接口的**全部 10 个错误码**：401601、403601、403602、403603、404601、400001、429601、503601、503001、500000。任何出口（包括全局异常处理器兜底产生的 503001/500000）`data` 都必须含 `error_type` 与 `request_id`（BE-27）。
- 管理类接口（5.1~5.3，需登录）另会返回通用错误码 400001、401001、401002、403001、403002、404000、409001、500000、503001（含义与 message 见总体方案 4.2），不在 API 文档页展示。

### 5.1 我的 API 密钥

`ApiKeyItem`：
```json
{"id": 7, "name": "客服系统", "description": "客服机器人检索", "key_masked": "kb-AbCd****",
 "scope_type": "selected", "dataset_ids": [10, 11], "accessible_dataset_count": 1,
 "status": "enabled", "stored_status": "enabled",
 "expires_at": "2027-11-11T23:59:59+08:00", "ip_whitelist": ["10.0.0.0/24"], "rate_limit_per_min": 60,
 "calls_7d": 12, "failures_7d": 2, "last_used_at": "2026-11-11T09:00:00+08:00",
 "created_at": "2026-11-11T08:00:00+08:00", "version": 2}
```
`scope_type=all` 时 `dataset_ids=[]`。

#### 5.1.0 创建人操作与存储状态矩阵

| 操作 | `stored_status=enabled` | `disabled` | `admin_disabled` | admin_disabled 时的错误码 |
|---|---|---|---|---|
| 查看详情 / 可检索名单（5.1.3、5.1.8） | 允许 | 允许 | 允许 | — |
| 编辑（5.1.4） | 允许 | 允许 | **拒绝** | 403605 |
| 停用（5.1.5 `status=disabled`） | 允许 | 幂等成功（不写日志、version 不变） | **拒绝** | 403604 |
| 启用（5.1.5 `status=enabled`） | 幂等成功（同上） | 允许 | **拒绝** | 403604 |
| 重新生成（5.1.6） | 允许 | 允许（存储状态保持 disabled） | **拒绝** | 403605 |
| 删除（5.1.7） | 允许 | 允许 | **允许** | — |
| 查看调用日志（5.2.1） | 允许 | 允许 | 允许 | — |

- 计算状态 `owner_unavailable` / `expired` / `no_dataset` 不影响上表（以存储状态判断）；例如已过期的密钥仍可编辑延长过期时间（F-17 规则 8）。
- 校验顺序（4 个写接口一致）：本人且未删除（否则 404000）→ `SELECT ... FOR UPDATE` → 存储状态为 `admin_disabled`（403604 / 403605）→ `version`（409001）→ 业务校验。状态检查放在 version 之前：管理员停用会使 version +1，创建人此时拿旧 version 操作应看到"已被管理员停用"而非"数据已被他人修改"。

#### 5.1.1 `GET /api/v1/open-platform/api-keys`
- 权限码 `openapi:apikey:manage`；范围：仅 `created_by = 当前用户`（不按 data_scope）
- query：`page`、`page_size`、`name`（模糊）、`status`（计算后的 6 种之一；先查出本人全部密钥（预计 <100）再计算过滤与分页）
- 响应：分页 `ApiKeyItem`

#### 5.1.2 `POST /api/v1/open-platform/api-keys`
- 权限码 `openapi:apikey:manage`
- body：
  | 字段 | 类型 | 必填 | 规则 / 默认 |
  |---|---|---|---|
  | name | string | 是 | 1~50 字，本人名下唯一（409601） |
  | description | string | 否 | ≤200 |
  | scope_type | string | 否 | `all`（默认）/ `selected` |
  | dataset_ids | int[] | selected 时必填 | 1~50 个，去重，须全部为本人当前可访问（kb 内部接口校验，400601） |
  | expires_at | string(ISO) \| null | 否 | null = 永不过期；须晚于当前时间（400602）。前端默认"当前日期 + 1 年"当天 23:59:59 |
  | ip_whitelist | string[] | 否 | ≤20 条，IPv4 或 IPv4 CIDR（400603），规范化存储 |
  | rate_limit_per_min | int | 否 | 1~600，默认 60 |
- 响应 data：`{"api_key": "kb-AbCd...（43 位明文）", "item": ApiKeyItem}`
- 操作日志 api_key/create（摘要不含明文）

#### 5.1.3 `GET /api/v1/open-platform/api-keys/{id}` — 本人密钥；他人 → 404000；响应 `ApiKeyItem`

#### 5.1.4 `PUT /api/v1/open-platform/api-keys/{id}`
- 权限码 `openapi:apikey:manage`；仅本人
- body：同创建（全部字段）+ `version`；校验同创建
- 存储状态为 `admin_disabled` → 403605（5.1.0）
- 删除缓存；操作日志 api_key/update（检索范围变化在摘要中体现）
- 响应 data：`ApiKeyItem`

#### 5.1.5 `PUT /api/v1/open-platform/api-keys/{id}/status`
- 权限码 `openapi:apikey:manage`；仅本人
- body：`status`（`enabled`/`disabled`）、`version`
- 存储状态为 `admin_disabled` 时无论目标值 → 403604；目标值与当前存储状态相同 → 幂等成功（返回当前 `ApiKeyItem`，不写操作日志，version 不变）
- 响应 data：`ApiKeyItem`；操作日志 api_key/status

#### 5.1.6 `POST /api/v1/open-platform/api-keys/{id}/regenerate`
- 权限码 `openapi:apikey:manage`；仅本人
- body：`version`；生成新明文、替换哈希与前缀，旧值立即失效（删除旧哈希缓存）；存储状态不变（`disabled` 的密钥重新生成后仍为 `disabled`）
- 存储状态为 `admin_disabled` → 403605（5.1.0）
- 响应 data：`{"api_key": "kb-...", "item": ApiKeyItem}`；操作日志 api_key/regenerate

#### 5.1.7 `DELETE /api/v1/open-platform/api-keys/{id}`
- 权限码 `openapi:apikey:manage`；仅本人；**任何存储状态都允许**（含 `admin_disabled`，创建人可清理被停用的密钥）
- 逻辑删除，删除缓存；操作日志 api_key/delete（被管理员停用的密钥删除时摘要带 `"stored_status":"admin_disabled"`，便于审计追溯）
- 响应 data：`null`

#### 5.1.8 `GET /api/v1/open-platform/api-keys/{id}/accessible-datasets`
- 仅本人；data：`[{"id": 10, "name": "集团制度"}]`（当前真正可检索的知识库：创建人可访问 ∩ 指定集合）

### 5.2 我的调用日志

#### 5.2.1 `GET /api/v1/open-platform/call-logs`
- 权限码 `openapi:log:list`；范围：`created_by = 当前用户`（本人密钥的日志，含已删除密钥）
- query：`page`、`page_size`、`start_time`、`end_time`（默认近 7 天，跨度 ≤90 天，400604）、`api_key_id`、`dataset_id`、`result`
- 排序 called_at desc
- 响应 items：
  ```json
  {"id": 900, "called_at": "2026-11-11T10:00:00+08:00", "request_id": "req-...",
   "api_key": {"id": 7, "name": "客服系统", "key_masked": "kb-AbCd****"},
   "dataset": {"id": 10, "name": "集团制度"}, "query": "年假几天", "result_count": 3,
   "latency_ms": 420, "result": "success", "error_code": null, "client_ip": "10.0.0.8"}
  ```

### 5.3 API 密钥审计（管理员）

| 接口 | 权限码 | 数据范围 | 说明 |
|---|---|---|---|
| `GET /api/v1/open-platform/audit/api-keys` | openapi:apikey:audit | `api_key.company_id / dept_id / created_by` | query：`page`、`page_size`、`creator_keyword`（user_ref 姓名/账号）、`org_id`（dept_id 含下级，org_ref）、`status`（`enabled`/`disabled`/`admin_disabled`/`expired`/`owner_unavailable` 可筛选；`owner_unavailable` 筛选按 user_ref 状态近似，展示值仍为精确计算）。items：`ApiKeyItem` 去掉 `dataset_ids` 与 `ip_whitelist`，增加 `creator: {"id","name","username","status"}`、`company: {"id","name"}`、`dept: {"id","name"}` |
| `PUT /api/v1/open-platform/audit/api-keys/{id}/disable` | openapi:apikey:audit | 过滤 | body：`version`；存储状态为 `enabled` **或 `disabled`**（创建人自行停用的也可锁定，防止其日后自行启用）→ `admin_disabled`，记录 `admin_disabled_by/at`，version +1；删除缓存；操作日志 api_key/admin_disable（摘要含停用前存储状态）。已是 `admin_disabled` → 幂等成功（不校验 version、不写日志、version 不变）。响应 data：审计列表的单项结构 |
| `DELETE /api/v1/open-platform/audit/api-keys/{id}` | openapi:apikey:audit | 过滤 | 任何存储状态都允许；逻辑删除；删除缓存；操作日志 api_key/admin_delete；响应 data：`null` |
| `GET /api/v1/open-platform/audit/call-logs` | openapi:apikey:audit | `api_call_log.company_id / dept_id / created_by` | query：同 5.2.1 + `creator_keyword`、`include_unknown`（bool，默认 false）；items 增加 `creator: {"id","name"} \| null` |
| `GET /api/v1/open-platform/audit/capabilities` | openapi:apikey:audit | 不按数据范围（只读当前用户的 AuthContext） | 无参数；data：`{"can_view_unknown_calls": true}`，见下文 |

**`include_unknown` 与能力标记（2026-11-12 新增）**：
- 判定函数 `audit_service.can_view_unknown_calls(ctx) -> bool = ctx.is_super_admin or ctx.data_scope.all`（PRD F-19 规则 6"集团管理员和超级管理员"在实现上对应"超管或任一启用角色数据范围为 ALL"，与 M1 5.2.0"无管辖根限制"口径一致）。capabilities 接口与 call-logs 查询**必须调用同一函数**，保证"开关显示"与"开关生效"一致。
- `include_unknown=true` 且 `can_view_unknown_calls=true`：查询条件 = `(data_scope_filter) OR api_key_id IS NULL`，其余筛选条件照常叠加（因此同时带 `api_key_id` 或 `creator_keyword` 时自然不会返回无法识别密钥的行）。
- `include_unknown=true` 但无此能力：**静默忽略**（按 false 处理，不报错），不泄露是否存在此类记录。
- capabilities 响应：
  | 字段 | 类型 | 说明 |
  |---|---|---|
  | can_view_unknown_calls | bool | 为 true 时前端显示"含无法识别密钥的调用"开关 |
  
  取舍：不放进 `/auth/me`（iam）——该规则属于 open 的业务语义，放 iam 会让 iam 承载 open 的判断口径，且需改动已完成并测试的 M1 契约与前端全局 store；也不放进 call-logs 的分页响应——会破坏统一分页结构，且开关需要在首次查询前就决定是否显示。权限上下文按 epoch 失效，角色数据范围调整后下一次请求即生效，无需重新登录。

审计接口**不提供**编辑、启用、重新生成（AC-72：对应个人接口按 created_by 过滤，管理员调用他人密钥 → 404000）。

### 5.4 开放检索 API（外部系统）

#### `POST /api/v1/open/datasets/{dataset_id}/retrieve`
- 权限码：**public**（外部系统不登录，凭 API 密钥鉴权，鉴权链见 3.3）
- 数据范围：不按 data_scope；按密钥创建人的知识库日常访问权 ∩ 密钥指定范围
- 请求头：`Authorization: Bearer kb-xxxxxxxx`、`Content-Type: application/json`；可选 `X-Request-Id`
- path：`dataset_id`（int）
- body：
  | 字段 | 类型 | 必填 | 规则 |
  |---|---|---|---|
  | query | string | 是 | 1~1000 字（trim 后非空） |
  | search_method | string | 否 | `vector` / `full_text` / `hybrid` |
  | top_k | int | 否 | 1~20 |
  | score_threshold | number | 否 | 0~1；传入即启用阈值 |
  | reranking_enable | bool | 否 | 仅对 vector/full_text 生效；为 true 时使用知识库默认设置中的 Rerank 模型，未配置则跳过并在 `rerank_skipped` 中说明 |
  未知字段忽略。
- 成功响应（HTTP 200）：
  ```json
  {"code": 0, "message": "ok", "data": {
    "request_id": "req-7f3a...",
    "dataset": {"id": 10, "name": "集团制度"},
    "query": "年假几天",
    "retrieval_config": {"search_method": "hybrid", "top_k": 3, "score_threshold_enabled": false,
                         "score_threshold": 0.5, "reranking_enable": false, "reranking_model_name": null,
                         "hybrid_mode": "weighted", "vector_weight": 0.7},
    "rerank_skipped": false, "rerank_skipped_reason": null,
    "records": [
      {"segment_id": 5001, "position": 12, "segment_type": "general", "content": "年假为每年 10 天……",
       "score": 0.8731, "keywords": ["年假"],
       "document": {"id": 101, "name": "员工手册.pdf"}, "dataset": {"id": 10, "name": "集团制度"},
       "child_chunks": []},
      {"segment_id": 6002, "position": 3, "segment_type": "parent", "content": "父块全文……",
       "score": 0.82, "keywords": [],
       "document": {"id": 120, "name": "制度汇编.docx"}, "dataset": {"id": 10, "name": "集团制度"},
       "child_chunks": [{"id": 9001, "position": 2, "content": "子块……", "score": 0.82},
                        {"id": 9002, "position": 3, "content": "子块……", "score": 0.75}]}
    ]}}
  ```
  （同一知识库只会是一种分段方式，示例仅为展示两种结构。）
- 失败响应：HTTP 状态 = code // 1000，例如：
  ```json
  {"code": 404601, "message": "知识库不存在或未授权", "data": {"error_type": "DATASET_NOT_FOUND", "request_id": "req-..."}}
  {"code": 400001, "message": "参数不合法", "data": {"error_type": "INVALID_PARAMS", "request_id": "req-...",
    "errors": [{"field": "top_k", "message": "取值范围 1~20"}]}}
  ```
- 错误码：401601、403601、403602、403603、404601、400001、429601、503601、503001、500000
- 幂等：只读接口，天然幂等；每次调用都计入限流与日志。
- 响应头：`X-Request-Id`；限流时附 `Retry-After: <到下一分钟的秒数>`。

### 5.5 内部接口

#### `GET /internal/v1/stats/api-keys`
- `require_internal`；query：`user_id`；data：`{"count": 1}`（未删除密钥数），供 iam 用户影响提示。

### 5.6 iam 联动
- M3 上线时 iam 配置 `OPEN_STATS_ENABLED=true`（M1 5.3.9 影响提示中的 `api_key_count` 生效）。

---

## 6. 权限设计

使用的权限码已在 M1 seed 写入：`openapi:menu:root`、`openapi:apikey:manage`、`openapi:log:list`、`openapi:doc:view`、`openapi:apikey:audit`。M3 不新增权限点。

- 普通员工默认拥有前四项；公司管理员、集团管理员另有 `openapi:apikey:audit`。
- 子公司管理员：只能审计本公司及下属公司员工的密钥与日志（按密钥 company_id/dept_id）；不能看到"无法识别密钥"的日志（`GET /audit/capabilities` 返回 `can_view_unknown_calls=false`，前端不显示开关）。
- 收回某角色的 `openapi:apikey:manage`：持有人的全部密钥即时变为"创建人不可用"（3.2）。

## 7. 后端任务清单

### BE-24（open）服务骨架、迁移、只读副本同步
- 文件：`services/open/main.py`、`.env.example`、`alembic.ini`、`alembic/env.py`、`alembic/versions/0001_init_open.py`、`app/core/config.py`、`app/models/*.py`、`app/jobs/ref_sync.py`、`app/repositories/ref_repo.py`、`app/services/kb_client.py`、tests
- 内容：第 4 节全部表；ref 同步（同 kb 实现方式，可参考 kb 代码但**不得 import kb**）；`kb_client`（InternalClient 封装：accessible-datasets、brief、retrieve）；devctl 识别 open。
- 完成标准：迁移 upgrade/downgrade/upgrade；服务可启动；ref 同步单测。

### BE-25（open）我的 API 密钥 — F-17
- 文件：`app/api/v1/api_keys.py`、`app/schemas/api_key.py`、`app/services/{api_key_service,key_status}.py`、`app/repositories/api_key_repo.py`、`app/api/internal/stats.py`、tests
- 内容：5.1 全部、5.5；3.1、3.2；缓存删除。
- 完成标准：AC-52、AC-53、AC-71（数量展示部分）、AC-72（创建人不能启用被管理员停用的密钥）单测；明文只在两个接口出现；跨用户 ID 直访 404000；5.1.0 矩阵逐格单测（admin_disabled 下编辑/重新生成 403605、启停 403604、删除成功；状态检查先于 version；启停同值幂等）。

### BE-26（open）密钥审计 — F-17、F-19
- 文件：`app/api/v1/audit.py`、`app/schemas/audit.py`、`app/services/audit_service.py`、tests
- 内容：5.3 全部（审计调用日志的查询函数与 BE-28 共用 `call_log_repo`，若 BE-28 未完成则本任务先实现查询部分）。
- 完成标准：AC-55、AC-72 单测；7 种数据范围在密钥审计上生效；`include_unknown` 仅 ALL/超管生效、其他人静默忽略；`GET /audit/capabilities` 与 call-logs 共用 `can_view_unknown_calls`（超管 / ALL → true，COMPANY_AND_CHILD 等 → false，单测覆盖）；管理员停用 `disabled` 的密钥成功、对 `admin_disabled` 幂等。

### BE-27（open）开放检索 API 与调用日志写入 — F-18、F-19
- 文件：`app/api/v1/open_retrieve.py`、`app/schemas/retrieve.py`、`app/services/{key_auth,rate_limit,retrieve_service}.py`、`app/jobs/call_log_consumer.py`、tests
- 内容：3.3、3.4（生产与消费）、5.4；无效密钥日志按 IP 采样；`Retry-After`；对 `/api/v1/open/` 前缀注册异常处理包装：任何错误响应（含全局处理器兜底的 400001/503001/500000）`data` 都补齐 `error_type`（按 5.0 映射）与 `request_id`，message 沿用共享库 `CommonErrors` 原文，并照常写调用日志（result 分别为 `invalid_params` / `service_unavailable` / `internal_error`）。
- 完成标准：AC-54、AC-56~AC-60、AC-62、AC-70、AC-71、AC-73 单测（kb 内部接口用 mock）；每个出口都产生且仅产生一条日志；限流窗口边界；50 并发压测（mock kb，open 自身开销 P95 ≤ 50ms，结果写入实现说明）。

### BE-28（open）调用日志查询、统计、清理 — F-19
- 文件：`app/api/v1/call_logs.py`、`app/schemas/call_log.py`、`app/services/call_log_service.py`、`app/repositories/call_log_repo.py`、`app/jobs/cleanup.py`、tests
- 内容：5.2、近 7 天统计（供 5.1 列表与审计列表）、180 天清理。
- 完成标准：AC-61 单测；90 天跨度校验；他人日志不可见。

### BE-29（部署）生产镜像与编排 — 非功能需求
- 文件：`backend/Dockerfile`、`backend/.dockerignore`、`deploy/docker-compose.prod.yml`、`deploy/.env.prod.example`、`deploy/README.md`
- 内容：
  - `backend/Dockerfile`：`python:3.12-slim` 多阶段；`ARG SERVICE`；安装 `requirements.txt` 与 `libs/platform_common`；复制 `services/${SERVICE}`；工作目录为服务目录；默认命令 `python main.py`；非 root 用户；`HEALTHCHECK` 调 `/healthz`（worker 例外）。
  - `docker-compose.prod.yml`：`nginx`（前端镜像，FE-22）、`iam`、`kb`、`kb-worker`（kb 镜像，`command: python worker.py`）、`open`、`postgres`（pgvector/pgvector:pg16）、`redis`、`minio`；一次性迁移服务 `iam-migrate`/`kb-migrate`/`open-migrate`（`alembic upgrade head`，iam 额外 `python -m app.seed`），业务服务 `depends_on` 迁移完成；所有密钥类配置（JWT 私钥/公钥文件挂载、`INTERNAL_API_TOKEN`、`MODEL_SECRET_KEY`、`API_KEY_PEPPER`、数据库与 MinIO 凭据）通过 `.env.prod` 注入，`.env.prod.example` 只放占位符；服务监听 `0.0.0.0`，容器内沿用各服务默认端口（iam 8301、kb 8302、open 8303），中间件使用容器端口（5432/6379/9000）与服务名互联，不暴露到宿主机（或按需映射）；前端 Nginx 上游即 `iam:8301`、`kb:8302`、`open:8303`。
  - README：构建（`docker build --build-arg SERVICE=iam -t kbp-iam:<ver> backend`）、单服务升级、扩容（`--scale kb-worker=4`）、各服务 DB 账号与 schema 授权 SQL 示例。
  - **PostgreSQL 参数与账号**：postgres 服务按 M2 3.10.3"生产"列设置 `command` 参数（按实际主机内存比例调整，README 给出换算方法）；kb 服务的 DB 账号须为 `kb` schema 下表的 owner（worker 需在运行时创建/删除 HNSW 索引，M2 3.10.2），README 授权 SQL 体现。
  - **安全基线（必须）**：
    - 所有服务 `APP_ENV=prod`；`INTERNAL_API_TOKEN` 必须覆盖为 ≥32 位随机串（`.env.prod.example` 中写 `INTERNAL_API_TOKEN=<openssl rand -hex 32 生成>`），否则服务按共享库 `validate_for_runtime()` 拒绝启动；`MODEL_SECRET_KEY`、`API_KEY_PEPPER`、数据库/MinIO/Redis 密码同理必须覆盖（kb/open 启动校验）。
    - `TRUSTED_PROXIES` **只填前端 Nginx 容器的地址或其所在 compose 网段**（例如为 compose 网络固定子网 `172.30.0.0/24` 并把 Nginx 固定为 `172.30.0.10/32`），不得包含 `127.0.0.1`、`0.0.0.0/0` 或宿主机网段；否则可通过伪造 `X-Forwarded-For` 绕过 API 密钥 IP 白名单与日志 IP。
    - Nginx 对外请求一律 `proxy_set_header X-Forwarded-For $remote_addr`（覆盖而非追加客户端传入值，FE-22 同步）；若前面还有一层负载均衡，需在 README 说明如何把其地址加入 `TRUSTED_PROXIES` 并改为追加模式。
    - 内部接口 `/internal/` 不经 Nginx 暴露；iam/kb/open 端口不映射到宿主机。
    - README 列出"上线前检查清单"：上述密钥均已替换、`APP_ENV=prod`、`TRUSTED_PROXIES` 正确、`SEED_ADMIN_PASSWORD` 已改且首次登录强制改密。
- 完成标准：本机可 `docker compose -f deploy/docker-compose.prod.yml up -d` 起全部服务，通过 Nginx 访问登录页并登录成功（M1 已完成即可验证）；镜像内无 `.env`、`.secrets`；`INTERNAL_API_TOKEN` 保持默认值时服务拒绝启动；伪造 `X-Forwarded-For` 不影响记录的客户端 IP。

## 8. 前端任务清单

> 服务文件：`src/services/open.ts`。

### FE-18 我的 API 密钥页 — F-17
- 路由 `/openapi/keys`；文件 `src/pages/openapi/keys/index.tsx`、`components/{ApiKeyFormModal,ApiKeySecretModal,AccessibleDatasetsModal}.tsx`
- 接口：5.1 全部、M2 `GET /api/v1/kb/datasets/options`（指定知识库多选，远程搜索）
- 权限码：`openapi:apikey:manage`
- 内容：查询（名称、状态）；列表列按 PRD（检索范围显示"全部可访问 / 指定 x 个"、当前可检索数可点击查看名单、状态 6 种中文标签、近 7 天调用/失败、操作：编辑/停用启用/重新生成/删除/日志（跳 `/openapi/logs?api_key_id=`））；`stored_status=admin_disabled` 时按 5.1.0 只保留"删除""日志"（及可检索名单查看），**隐藏编辑、停用/启用、重新生成**，标签"已被管理员停用"并在悬停提示"已被管理员停用，无法修改或启用，可删除后新建"；写操作收到 403604/403605（列表数据过期时）提示后刷新列表；表单：检索范围单选与多选（1~50）、过期时间（永不过期 / 日期，默认一年后）、IP 白名单（多行输入，前端格式校验）、每分钟上限（1~600）；创建/重新生成成功弹窗显示明文 + 复制按钮 + 醒目提示"关闭后将无法再次查看"，勾选"我已妥善保存"才能关闭；重新生成、删除二次确认。
- 完成标准：AC-52~AC-54、AC-71、AC-72 前端行为。

### FE-19 调用日志页（本人） — F-19
- 路由 `/openapi/logs`；文件 `src/pages/openapi/logs/index.tsx`、`src/components/CallLogTable.tsx`（通用，支持 `mode="mine"|"audit"`，audit 时显示创建人列与 include_unknown 开关）
- 接口：5.2.1、5.1.1（密钥下拉）、M2 datasets/options（知识库下拉）
- 权限码：`openapi:log:list`
- 内容：时间范围默认近 7 天、最长 90 天；查询文本截断 50 字、悬停全文；结果中文映射（3.3 的 result 枚举）；支持 URL 参数 `api_key_id` 预填。
- 完成标准：AC-61 前端行为。

### FE-20 API 密钥审计页 — F-17、F-19
- 路由 `/system/api-keys`；文件 `src/pages/system/apikey-audit/index.tsx`、`components/AuditCallLogDrawer.tsx`（内嵌 `CallLogTable mode="audit"`，按密钥过滤）
- 接口：5.3 全部、M1 orgs/options
- 权限码：`openapi:apikey:audit`
- 接口补充：`GET /api/v1/open-platform/audit/capabilities`（5.3）
- 内容：查询（创建人、所属组织树、状态）；列表列按 PRD；操作仅：停用（仅 `stored_status=admin_disabled` 时隐藏；`enabled`、`disabled` 均显示，二次确认文案"停用后创建人无法自行启用"）、删除（二次确认）、查看调用日志；页面另提供"全部调用日志"抽屉：打开抽屉时请求 capabilities，`can_view_unknown_calls=true` 才显示"含无法识别密钥的调用"开关（请求失败或 false 均不显示、不传 `include_unknown`）；按单个密钥打开的 `AuditCallLogDrawer` 不显示该开关。
- 完成标准：AC-55、AC-58（日志可见性）、AC-72 前端行为。

### FE-21 API 文档页 — F-18
- 路由 `/openapi/docs`；文件 `src/pages/openapi/docs/index.tsx`、`docs/content.tsx`
- 接口：无（静态内容）
- 权限码：`openapi:doc:view`
- 内容：调用地址（`{window.location.origin}/api/v1/open/datasets/{dataset_id}/retrieve`）、鉴权方式、请求参数表、成功/失败响应示例（取 5.4）、错误码与 error_type 表（5.0，10 行；message 一字不差取 5.0，其中 503001 为"依赖服务暂不可用，请稍后重试"、500000 为"系统繁忙，请稍后重试"）、curl 示例：
  ```bash
  curl -X POST "https://kb.example.com/api/v1/open/datasets/10/retrieve" \
    -H "Authorization: Bearer kb-AbCd..." -H "Content-Type: application/json" \
    -d '{"query": "年假几天", "top_k": 3}'
  ```
  代码块带复制按钮；知识库 ID 获取方式说明（知识库详情页显示 ID——FE-11 左侧信息区需显示"知识库 ID"，已在本任务中一并补充到 `src/pages/kb/detail/Layout.tsx`）。
- 完成标准：示例与契约字段一致。

### FE-22 前端生产镜像 — 部署
- 文件：`frontend/Dockerfile`、`frontend/nginx/default.conf.template`、`frontend/.dockerignore`
- 内容：node 构建（pnpm）→ `nginx:alpine`；静态资源 + SPA 回退；`/api/v1/auth`、`/api/v1/system` → `${IAM_UPSTREAM}`；`/api/v1/kb` → `${KB_UPSTREAM}`；`/api/v1/open-platform`、`/api/v1/open` → `${OPEN_UPSTREAM}`；**不代理 `/internal/`**；`client_max_body_size 20m`；`X-Forwarded-For` 以 `$remote_addr` 覆盖（不信任客户端传入值，见 BE-29 安全基线），透传 `X-Request-Id`；上游地址用 nginx 官方镜像的 envsubst 模板机制注入。
- 完成标准：`docker build` 成功；配合 BE-29 compose 可访问。

## 9. 任务依赖与并行

| 阶段 | 后端（open / 部署） | 前端 |
|---|---|---|
| 1 | BE-24（依赖 M1 BE-03） | FE-21、FE-18、FE-19、FE-20（对契约开发） |
| 2 | BE-25、BE-28（可并行，文件不重叠） | — |
| 3 | BE-26（依赖 BE-25、BE-28 的 repo）、BE-27（依赖 M2 BE-22 才能联调；可先用 mock 开发） | 联调 FE-18、FE-19、FE-20 |
| 4 | BE-29（依赖全部服务可运行） | FE-22（与 BE-29 并行） |

- BE-24~BE-28 可与 M2 后半程（BE-18 之后）并行开发；BE-27 的端到端联调需要 M2 BE-21、BE-22 完成。

## 10. 风险与兼容性
- 无存量数据；回滚 `alembic downgrade base`（open schema）。open 服务回退不影响 iam/kb。
- 调用日志写入依赖 Redis Stream：Redis 故障时检索也会因会话/上下文无法读取而失败（fail-closed），不会出现"调用成功但无日志"的大面积情况；单条 XADD 失败只记运行日志。
- `API_KEY_PEPPER` 一旦设置不可更换（否则全部密钥失效），部署文档中需醒目说明。
- 管理员停用只针对单个密钥：创建人仍可删除后新建密钥继续调用（PRD 未禁止）。若需禁止某人使用开放检索，应收回其角色的 `openapi:apikey:manage`（其全部密钥即时变为"创建人不可用"）。admin_disabled 为终态，误停用只能由创建人新建密钥恢复使用。

## 11. 测试要点（M3）
- 鉴权链每一步的错误码与 error_type（AC-54、AC-57、AC-58）；错误顺序：无效密钥优先于 IP，停用优先于过期。
- 即时生效（AC-70）：移除分配、调岗、停用创建人、收回 `openapi:apikey:manage`、管理员停用、重新生成后，下一次调用立即反映。
- 指定范围（AC-71）：失去/恢复权限时可检索数变化。
- 管理员密钥不含管理视图范围（AC-73）；超管同样。
- 审计数据范围：A 公司管理员看不到 B 公司密钥，对 B 公司密钥的停用/删除 → 404000（AC-55）；管理员不能编辑/启用/重新生成他人密钥（AC-72）。
- admin_disabled 终态（5.1.0）：创建人编辑/重新生成 → 403605、启用/停用 → 403604、删除成功；拿管理员停用前的旧 version 操作返回 403605/403604 而非 409001；管理员可停用创建人已自行停用的密钥，之后创建人启用 → 403604；重复停用幂等。
- 无法识别密钥开关：超管、ALL 角色 capabilities 为 true 且 `include_unknown=true` 能查到 `api_key_id IS NULL` 的行；COMPANY_AND_CHILD 公司管理员 capabilities 为 false，直接构造 `include_unknown=true` 请求也查不到；调整角色数据范围后无需重新登录即生效。
- 开放检索 503001/500000 响应体含 `error_type`、`request_id`，message 与 API 文档页一致（停 kb 模拟 503001）。
- 限流（AC-62）：同一分钟第 11 次起 429601，跨分钟恢复；超限调用写日志；多实例 open 共享计数。
- 参数校验（AC-59）：query 空/超 1000、top_k=50、score_threshold=-1、search_method 非法 → 400001 且指出字段。
- 只返回启用内容（AC-60）。
- 日志：每次调用一条；无法识别密钥的日志仅 ALL 可见（AC-58）；同 IP 刷无效密钥时采样生效。
- 性能：50 并发、单库 10 万分段不开 Rerank P95 ≤ 1.5s（含 Embedding 模型调用，需使用真实或低延迟模型服务，报告中注明模型耗时）。
- 部署：生产 compose 一键启动；单独重建并重启 open 镜像时 iam/kb 不中断。
- 回归：M1 用户停用影响提示中的 API 密钥数；M2 召回测试与开放检索结果一致（同参数）。

## 12. 变更记录
| 日期 | 变更内容 | 原因 | 影响任务 |
|---|---|---|---|
| 2026-11-11 | 初稿 | 新需求 | 全部 |
| 2026-11-11 | 端口改为专属：open `PORT=8303`，`KB_RETRIEVAL_URL` 默认 `http://127.0.0.1:8302`；生产编排中服务与 Nginx 上游端口同步 | 用户确认：本机多项目共用 | BE-24、BE-29、FE-22 |
| 2026-11-11 | 0001 迁移 downgrade 改为逐表 DROP、保留空 schema | 与 iam 一致：版本表在本服务 schema 内 | BE-24 |
| 2026-11-11 | BE-29 增加生产安全基线：必须覆盖 `INTERNAL_API_TOKEN` 等密钥（启动校验）、`TRUSTED_PROXIES` 只填 Nginx 地址、Nginx 覆盖 `X-Forwarded-For`、上线检查清单；FE-22 同步 | 测试提出的部署安全建议，用户确认 | BE-29、FE-22 |
| 2026-11-12 | BE-29 增加生产 PG 参数（M2 3.10.3）与 kb 账号需为表 owner（运行时建 HNSW 索引） | BE-21b 检索性能优化 | BE-29 |
| 2026-11-12 | ①新增 `GET /api/v1/open-platform/audit/capabilities`（`openapi:apikey:audit`，data `{"can_view_unknown_calls": bool}`），与 audit/call-logs 共用 `can_view_unknown_calls(ctx)=超管 or data_scope.all`；明确 `include_unknown` 的叠加语义与"无能力时静默忽略"；**不改 `/auth/me`（M1 契约不变）**（5.3、第 6 节）。②5.0 补全开放检索 3 个通用错误码的固定 message：503001"依赖服务暂不可用，请稍后重试"、500000"系统繁忙，请稍后重试"（与共享库 `CommonErrors` 一致）及触发条件；所有出口须带 `error_type`/`request_id`。③admin_disabled 定为终态，新增 5.1.0 操作矩阵与 403605：创建人编辑/重新生成 → 403605，启停 → 403604，删除允许；状态检查先于 version；启停同值幂等；管理员可停用 `disabled` 的密钥，重复停用幂等；5.1.4~5.1.7 补齐权限码与响应 | FE-18/FE-20/FE-21 契约澄清申请（用户授权按推荐方案决定） | BE-25、BE-26、BE-27、FE-18、FE-20、FE-21 |

## 13. 实现说明（开发补充）
- 后端：
- 前端（FE-18~FE-21，对契约开发 + mock 单测，未与 open 后端联调）：
  - 类型与接口：`src/services/types/open-contract.ts`（手写，后端 OpenAPI 就绪后以 `pnpm gen:api` 生成的 `open.d.ts` 为准并核对差异）、`src/services/open.ts`（`apiKeyApi`/`callLogApi`/`auditApi`）；`src/services/kb.ts` 新增 `datasetApi.options`（M2 5.2.2）与类型 `DatasetOption`。创建/编辑密钥用 `skipErrorToast`，由 `logic.ts` 的 `mapSubmitError` 把 409601/400601/400602/400603/400001(errors) 映射到表单字段；其余写操作走默认拦截器提示。
  - FE-18 `pages/openapi/keys`：ProTable（名称、状态筛选）；检索范围"全部可访问 / 指定 x 个"，"当前可检索"数可点开名单（5.1.8）；状态 6 种中文标签；`stored_status=admin_disabled` 时不显示停用/启用（标签"已被管理员停用"）；操作：编辑、停用/启用（停用二次确认）、重新生成与删除（二次确认）、日志（跳 `/openapi/logs?api_key_id=`）。表单 `ApiKeyFormModal`：范围单选 + 知识库远程多选（`components/DatasetOptionSelect.tsx`，数据来自 kb 5.2.2，仅本人可访问的知识库；编辑时用 5.1.8 名单回显名称，名单外的已选项标注"当前不可访问"）；过期时间"指定日期（默认今天+1 年，提交为当天 23:59:59）/永不过期"；IP 白名单多行输入（每行一条，也容许逗号/空白分隔，最多 20 条，IPv4 或 IPv4 CIDR，前端逐条校验并列出非法项）；限流 1~600 整数默认 60。注意：ProForm 的 `onFinish` 会把 DatePicker 的 dayjs 转成字符串，`toExpiresIso` 统一用 `dayjs()` 解析；ModalForm 需显式 `name="api_key_form"`，否则与搜索表单的 `name` 字段 id 冲突。
  - 明文只显示一次：创建/重新生成响应的 `api_key` 只放在页面组件的 `useState`（不用 `useMutation`/query 缓存，不写 storage），`ApiKeySecretModal` 不可点遮罩/Esc/右上角关闭，必须勾选"我已妥善保存"才能点"关闭"，关闭后状态置空；复制走 `utils/clipboard.ts`（Clipboard API，非安全上下文回退 `execCommand`）。
  - FE-19 `pages/openapi/logs` + 通用 `components/CallLogTable.tsx`（`mode="mine"|"audit"`）：时间范围默认近 7 天、最长 90 天（`components/callLog.ts`：选择器 `disabledDate` + 请求前校验，不可选未来）；查询文本截断 50 字、悬停全文；结果 11 种中文映射（未知值回退原值）；`?api_key_id=` 预填密钥筛选；密钥下拉取 `apiKeyApi.list(page_size=100)`；知识库下拉取 kb 5.2.2。审计模式额外显示创建人列/筛选，并走 `auditApi.callLogs`；`api_key=null` 的行显示"无法识别密钥"。
  - FE-20 `pages/system/apikey-audit`：查询（创建人、所属组织树、状态 5 种）；操作列只有"停用"（仅 `stored_status=enabled` 时显示，二次确认）、"删除"（二次确认）、"调用日志"（`AuditCallLogDrawer`，固定该密钥）；工具栏"全部调用日志"抽屉带"含无法识别密钥的调用"开关（`include_unknown`，tooltip 注明仅集团管理员/超管有效）。页面没有编辑、启用、重新生成入口（AC-72）。创建人状态非启用时在创建人列追加标签。
  - FE-21 `pages/openapi/docs`：静态内容放 `content.ts`（调用地址取 `window.location.origin`、请求参数表、curl/Python 示例、成功/失败响应示例取 5.4、10 个开放接口错误码与 error_type 表取 5.0/5.4），`CodeBlock.tsx` 带复制按钮。同时在 `pages/kb/detail/Layout.tsx` 左侧信息区补"知识库 ID"（可复制）。
  - 路由：`router/routes.tsx` 替换 M3 四个占位（`/openapi/keys|logs|docs`、`/system/api-keys`），权限码 `openapi:apikey:manage`、`openapi:log:list`、`openapi:doc:view`、`openapi:apikey:audit`；vite proxy 无需改动。
  - 单测（均 mock 接口）：`pages/openapi/keys/{logic,index}.test.tsx`、`components/ApiKeySecretModal.test.tsx`（明文只显示一次、需勾选才能关闭、关闭后 DOM 无明文、复制写剪贴板、IP/限流/范围校验、409601 字段错误、重新生成/删除二次确认、admin_disabled 无启用按钮）、`components/{callLog.test.ts,CallLogTable.test.tsx}`（90 天限制、截断、结果映射、预填密钥、审计模式）、`pages/openapi/docs/{content.test.ts,index.test.tsx}`（示例与契约字段一致、错误码表）、`pages/system/apikey-audit/{logic,index}.test.ts(x)`（无编辑/启用/重新生成、停用确认带 version）。
  - 自查：因 5174 被其他进程占用，用 `vite --port 5199` + Playwright 路由 mock 截图检查四个页面与新建/明文弹窗渲染正常，已只关闭本次启动的进程。
  - 契约澄清后的调整（2026-11-12）：①FE-18 `rowActions`：`admin_disabled` 只保留"删除""日志"（隐藏编辑、停用/启用、重新生成），行内显示"不可修改"并悬停提示"已被管理员停用，无法修改或启用，可删除后新建"；启停/重新生成/编辑收到 403604/403605 时提示后端 message 并刷新列表（编辑弹窗同时关闭）。②FE-20 `auditRowActions`：停用仅在 `admin_disabled` 时隐藏，`enabled`/`disabled` 均显示，确认文案"停用后创建人无法自行启用"；"全部调用日志"抽屉打开时请求 `auditApi.capabilities()`（`GET /audit/capabilities`，`skipErrorToast`，不重试），仅 `can_view_unknown_calls===true` 才显示开关并可传 `include_unknown`，失败/false 均不显示、不传；按单个密钥打开的抽屉不请求也不显示。③FE-21 错误码表 503001 改"依赖服务暂不可用，请稍后重试"、500000 改"系统繁忙，请稍后重试"，与 5.0 逐项核对 10 个开放接口错误码；403604/403605 属管理类接口错误码，按 5.0 不在 API 文档页展示（单测断言不含）。
