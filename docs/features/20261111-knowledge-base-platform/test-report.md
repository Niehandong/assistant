# 企业级知识库管理平台 测试报告（M1 第 1 轮 + 第 2 轮回归）

> 第 2 轮回归结果见文末第 7 节；第 1~6 节为第 1 轮原始记录（缺陷状态以第 7 节为准）。

- 关联文档：`./prd.md`（v0.3，AC-01 ~ AC-21、AC-74 属 M1）、`./tech-design.md`、`./tech-design-m1.md`
- 范围：M1 平台地基（F-01 ~ F-06）。M2/M3 功能不在本轮。
- 测试环境：
  - 被测构建：工作区未提交代码（HEAD `6d6131d`）。iam 进程 13:20 启动（`--env test`，后端源码最后修改 13:10，测试期间后端源码无变化）；前端 vite 5174（源码含 13:33 前的前端改动）。
  - 数据：独立库 `kbp_test`、Redis db 1、桶 `kbp-test`（已用 `/proc/<pid>/environ` 核对 `DATABASE_URL=…/kbp_test`、`REDIS_URL=…/1`）。开发库 `kbp` 未触碰。
  - **文档在测试期间有更新**：13:31 ~ 13:34 主会话把 PRD 升到 v0.3、`tech-design-m1.md` 增加 5.2.0（管辖根保护 403102/403103）、409106、集团下可直接建部门等规则；被测后端尚未实现这些规则（见 BUG-02 ~ BUG-04）。这几项按 v0.3 判定，请开发实现后在第 2 轮回归。
- 结论：**不通过**（2 个严重、4 个一般、6 个轻微缺陷，见第 4 节）

## 1. 测试数据

- 组织（集成测试 `world`，每次运行前由 `reset_env.sh` 重置 `kbp_test` 并重新 seed）：
  集团 → 公司 `qaA`（部门 研发部 A_D1 → 前端组 A_D1_F、测试部 A_D2；子公司 `qaA1` → 部门 A1_D）、公司 `qaB`（部门 B_D1、B_D2）。
- 账号（口令均为首次登录后改密）：
  | 账号 | 组织 | 角色 | data_scope | 用途 |
  |---|---|---|---|---|
  | admin | 集团 | super_admin | 不受限 | 造数、超管对照 |
  | qa_gadmin | 集团 | group_admin（内置） | ALL | 集团管理员 |
  | qa_aadmin | A 公司节点 | company_admin（内置） | COMPANY_AND_CHILD | 子公司管理员 |
  | qa_badmin | B 公司节点 | company_admin | COMPANY_AND_CHILD | B 公司管理员（AC-16） |
  | qa_aself | A 研发部 | employee | SELF | 普通员工 |
  | qa_bstaff | B 一部 | employee | SELF | B 公司普通员工 |
  | qa_noperm | A 研发部 | 无 | - | 无任何权限 |
  | ks_u1 ~ ks_u5 | 研发部 / 测试部 / A1 部门 / B 公司节点 / 前端组 | u1 持探测角色，其余无角色 | 探测角色依次切换 7 种范围 | AC-17 样本（用户、组织、操作日志、登录日志） |
  | a05_z | A 公司节点（直属公司） | 探测角色 | DEPT / DEPT_AND_CHILD / COMPANY / COMPANY_AND_CHILD | A-05 口径 |
  | 其余 | 每个用例自建（f3*、f1* 等） | | | 保证用例互相独立 |
- E2E 数据：`E2E-A公司（研发部、测试部）`、`E2E-B公司（一部）` + e_gadmin / e_aadmin / e_emp / e_noperm / e_bstaff。
- 测试代码位置（不进 git）：`backend/services/iam/tests/integration/`（pytest + httpx，真实 8301/PG/Redis）、`frontend/e2e/`（Playwright，Python 版；失败自动保存截图与 trace 到 `frontend/e2e/artifacts/`）。
- 复跑：
  - `.venv/bin/python backend/scripts/devctl.py --env test migrate && .venv/bin/python backend/scripts/devctl.py --env test up -d iam`
  - 集成：`cd backend && ../.venv/bin/python -m pytest services/iam/tests/integration`（会话开始时自动执行 `reset_env.sh` 重置 kbp_test）
  - E2E：`cd frontend && pnpm dev`（另一终端），再 `cd frontend/e2e && python3 -m pytest test_m1_auth.py test_m1_admin.py`
  - Redis 故障用例会停止/启动 `kbp-redis` 容器（用例内 finally 恢复）。

## 2. AC 覆盖矩阵

| AC | 用例（集成 / E2E） | 结果 |
|---|---|---|
| AC-01 登录成功 | 集成 `test_ac01_login_success_menu_and_log`、`test_ac01_no_perm_user_has_empty_menu`、`test_ac01_me_contract`；E2E `test_ac01_login_success_shows_permitted_menus_only`、`test_ac01_wrong_password_message_and_not_enumerating` | 通过 |
| AC-02 密码错误与锁定 | 集成 `test_ac02_lock_after_5_failures_and_remaining_time`、`..._nonexistent_account_same_message_and_lock`、`..._success_resets_counter`、`..._concurrent_wrong_logins_lock_exactly`、参数校验/注入；E2E `test_ac02_lock_message_and_single_submit`（5 次错误→第 6 次锁定提示含分钟数、双击只提交一次） | 通过；并发场景见 BUG-01、BUG-06 |
| AC-03 停用账号/组织不可登录 | 集成 `test_ac03_disabled_user_cannot_login`、`test_ac03_disabled_ancestor_org_cannot_login`（含失败原因入登录日志、已登录会话立即失效、错误密码不泄露状态） | 通过 |
| AC-04 会话续期与失效 | 集成 `test_ac04_refresh_*`（轮换、旧令牌重用 401104、并发只有 1 个成功、7 天未用到期、Redis 会话丢失、TTL=7 天）、令牌伪造/过期/篡改/alg=none/算法混淆；E2E `test_ac04_expired_access_token_refreshes_transparently_and_revoked_goes_login` | 通过；BUG-10 |
| AC-05 改密/重置/停用后会话失效 | 集成 `test_ac05_change_password_keeps_current_kills_others`、`..._admin_reset_password_kills_all`、`..._admin_disable_kills_all`、`..._admin_delete_kills_all`；E2E `test_ac05_second_browser_kicked_after_password_change` | 通过 |
| AC-06 首次登录强制改密 | 集成 `test_ac06_must_change_password_gate`（全部业务接口 403002，me/password 白名单）、`test_ac06_password_rules`、`..._messages_distinct`；E2E `test_ac06_forced_password_change_flow` | 通过；BUG-11 |
| AC-07 组织层级维护 | 集成 `test_ac07_*`（层级、重名、编码、校验、排序、过滤、XSS/SQL 载荷）；E2E `test_ac07_org_page_*`；**v0.3 新增：集团下直接建部门** `test_ac07_v03_dept_directly_under_group_and_user_company_is_group` | 旧口径通过；v0.3 新增口径失败（BUG-04） |
| AC-08 子公司管理员组织范围 | 集成 `test_ac08_*`（树/选择器范围、B 公司节点所有直接请求统一 404000 且与不存在 ID 响应一致、不能移动本公司节点 403101、不能建同级公司、负责人须在范围内） | 通过 |
| AC-09 删除被引用的组织 | 集成 `test_ac09_*`（下级 409103、用户 409104、逻辑删除、编码不可复用、操作日志）；E2E `test_ac09_delete_org_with_users_confirm_and_reason` | 通过；公司级角色/CUSTOM 引用见 BUG-03 |
| AC-10 新增用户 | 集成 `test_ac10_*`（成功、重名 409111、含已删除账号、手机号 409112、系统生成密码只返回一次、参数校验 20 项、带 role_ids、跨公司创建 404000）；E2E `test_ac10_user_create_generated_password_shown_once_and_duplicate`、`test_user_form_validation_messages` | 通过 |
| AC-11 跨公司用户隔离 | 集成 `test_ac11_cross_company_isolation`（列表查不到，编辑/停用/重置/分配角色/删除/impact 全部 404000 且数据库行无变化）、分页边界、过滤与注入；E2E `test_ac11_company_admin_sees_only_own_company_users_and_orgs` | 通过 |
| AC-12 停用与删除限制 | 集成 `test_ac12_*`（停用/删除自己 403111、内置 admin 403112、停用后会话/刷新/登录失效、impact 降级态）；E2E `test_ac12_user_actions_self_hidden_disable_confirm_with_impact`（自己/admin 无停用删除按钮、确认弹窗含 API 密钥失效提示、取消无变化） | 通过（M1 下游未接入，知识库数量按降级文案） |
| AC-13 角色权限生效 | 集成 `test_ac13_*`（授权/取消下一请求即生效、角色停用/取消分配即时失权、菜单树规则）；E2E `test_ac13_menu_and_buttons_follow_role_grants_and_403`（菜单出现但无“新增”按钮、取消后菜单消失、直接访问 403 页） | 通过 |
| AC-14 授权不能超出自身 | 集成 `test_ac14_*`（模型配置 403123 含 forbidden_codes、ALL/CUSTOM 越界 403124、角色无变化、保存时保留不拥有的权限、权限树 grantable）；E2E `test_ac14_grant_drawer_disables_options_beyond_own_authority`（权限节点与 ALL 选项置灰） | 通过 |
| AC-15 无权限访问角色管理 | 集成 `test_ac15_employee_gets_403_on_all_system_endpoints`（3 类账号 × 29 个读写接口全部 403001）、未登录全部 401001；E2E `test_ac15_employee_direct_url_403_and_menu_hidden` | 通过 |
| AC-16 公司级角色可见范围 | 集成 `test_ac16_company_role_invisible_to_other_company`（列表不可见、详情/编辑/授权/删除/用户 404000、分配 403121、创建用户带该角色 403121）、上级公司角色可分配给子公司而非反向 | 通过 |
| AC-17 7 种数据范围 | M1 在**用户列表、组织树、操作日志、登录日志、按 ID 直接访问**上用 AC-17 组织样本逐种验证：集成 `test_ac17_*`（ALL / COMPANY_AND_CHILD / COMPANY / DEPT_AND_CHILD / DEPT / SELF / CUSTOM，含写操作越界、CUSTOM 不含下级、直属公司节点 A-05、集团本部）。**知识库管理视图部分属 M2，本轮不适用** | 通过 |
| AC-18 多角色并集 | 集成 `test_ac18_multi_role_union`（DEPT ∪ CUSTOM(B)）、`test_ac18_union_company_and_dept_scopes`（含停用其一后立即收缩） | 通过 |
| AC-19 超级管理员不受限 | 集成 `test_ac19_super_admin_and_group_admin_see_everything`（用户、组织、含 company 为空的登录日志）；知识库管理视图、API 密钥审计属 M2/M3，不适用 | 通过 |
| AC-20 关键操作留痕 | 集成 `test_ac20_*`（重置密码、角色数据范围变更 before/after、用户/角色/组织各类操作 13 种均有日志、失败操作记 failure、日志无明文密码、事件幂等、非法事件不拖垮消费者）。5 类操作中知识库查看/转移与停用 API 密钥属 M2/M3，用“向 `stream:oplog` 投递事件”验证入库管道 | 通过；BUG-07 |
| AC-21 日志数据权限 | 集成 `test_ac21_*`（A 公司管理员只见 A 及下属的操作/登录日志、按 ID 访问 B 日志 404000、过滤条件无法绕过、POST/PUT/PATCH/DELETE 全部 404/405）；E2E `test_ac21_log_pages_scope_and_no_mutations` | 通过 |
| AC-74 管辖根与本人组织链保护（v0.3 新增） | 集成 `test_ac74_*`（M/G/S0 三类账号、CUSTOM 管辖根、409106、CUSTOM 引用清理）；E2E `test_ac74_ui_root_org_buttons_disabled_for_company_admin` | **失败**（BUG-02、BUG-03，后端未实现） |

AC 覆盖：22 / 22 个 M1 AC 均有用例；AC-17/18/19/20 中属于 M2/M3 的部分（知识库管理视图、API 密钥审计、转移所有权）不适用。

## 3. 多维度测试结果

用例总数 258（集成 234 + E2E 24），通过 216，失败 38，预期失败/待决策 4（`xfail`，见第 6 节）。集成用例按名称规则粗略归入单一维度。

| 维度 | 用例数 | 通过 | 失败 | 说明 |
|---|---|---|---|---|
| 功能验收 | 41 | 39 | 2 | 失败：BUG-04（集团直属部门）、BUG-02 相关 |
| 权限 / 越权 | 33 | 31 | 2 | 水平越权（组织/用户/角色/日志按 ID）全部返回统一 404000；失败：BUG-10、BUG-02 |
| 数据范围 | 19 | 19 | 0 | 7 种范围 × 用户/组织/操作日志/登录日志 + 并集 + A-05 |
| 输入校验与边界 | 74 | 53 | 21 | 失败：BUG-05（19 项）、BUG-06 并发、BUG-11 |
| 业务规则与异常流程 | 58 | 45 | 9 | 并发修改 409001、重复提交、删除被引用；失败：BUG-02/03/04、BUG-01 |
| 接口契约一致性 | 含在各用例中 | - | - | 响应结构/字段/错误码逐项断言（UserItem、RoleItem、OrgNode、分页、日志、me、权限树）；唯一差异：OrgNode 缺 v0.3 新增的 `*_blocked_reason`（BUG-02） |
| 服务故障与一致性 | 4 | 3 | 1 | Redis 停止/恢复；失败：BUG-08。M1 仅 iam 一个服务，跨服务故障不适用 |
| 性能（NFR 列表 P95 ≤ 1s） | 5 | 5 | 0 | 2 万用户 / 2000 组织 / 10 万日志：用户列表、深分页、组织树、日志、DEPT_AND_CHILD、epoch 失效后首请求均 ≤ 1s |
| UI / 交互（E2E） | 24 | 21 | 3 | 失败：AC-74 按钮置灰、列表错误状态（BUG-12）、孤儿 CUSTOM 引用保存（BUG-03） |
| 回归 | 不适用 | - | - | 首个需求，无存量功能 |

## 4. 缺陷列表

### BUG-01 [严重][后端] 并发登录耗尽 DB 连接池，iam 挂起 30 秒并返回 500
- 关联：AC-01、AC-02（可用性）
- 复现步骤：
  1. 对 `POST /api/v1/auth/login` 并发发起 24 个请求（任意不存在账号即可，无需认证）：`test_ac02_concurrent_logins_do_not_exhaust_db_pool`。
  2. 8 核机器上 10~16 并发正常（约 1 秒），24 并发开始出现。
- 期望结果：高并发登录只是变慢，全部返回 401101/401102。
- 实际结果：约 20 个以上并发时，多个请求挂起约 31 秒，其中一部分返回 500（500000）。
- 证据：iam 日志 `sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 30.00`；测试输出 `慢请求 [31.1, 31.1, …]，异常码 [500000 × 4]`。
- 可疑位置：`app/services/auth_service.py::login`。请求级 session 在 `get_by_username` 后一直占着一个连接，`_record_login` 又用独立事务再取一个连接，每个登录占 2 个连接，10 个并发就占满 `DB_POOL_SIZE(10)+overflow(10)`，互相等待直到 30s 超时。其他同样“持有请求 session 同时另开事务”的路径（刷新、改密）也应排查。
- 状态：未修复

### BUG-02 [严重][后端+前端] AC-74 管辖根/本人组织链保护未实现，管理员可停用本公司（或本人所在组织）导致全员被锁
- 关联：AC-74、F-02 规则 9（对应主会话重点关注 1）
- 复现步骤：
  1. A 公司管理员（company_admin，COMPANY_AND_CHILD，主组织为 A 公司节点或 A 研发部）登录。
  2. `PUT /system/orgs/{A 公司 id}/status {"status":"disabled"}`；部门管理员对自己所在部门同样操作；超管对自己所在组织链上的节点同样操作。
  3. `GET /system/orgs/tree` 查看节点字段。
- 期望结果：按 AC-74 / 方案 5.2.0：管辖根停用、删除返回 403102；停用本人所在组织及其上级返回 403103（含超管）；树节点带 `disable_blocked_reason`/`delete_blocked_reason`；页面按钮置灰并有提示。
- 实际结果：
  - 停用本公司节点返回 200。随后该公司全部用户（含操作人）会话立即失效，重新登录 401103，只有集团管理员能恢复；
  - 部门管理员停用自己所在部门、超管停用自己所在部门均返回 200；
  - `OrgNode` 没有 `disable_blocked_reason`/`delete_blocked_reason` 字段；组织页面“停用”“删除”按钮未置灰。
- 证据：集成 `test_ac74_company_admin_cannot_disable_or_delete_root_company`、`test_ac74_group_admin_all_scope_and_super_admin`、`test_ac74_super_admin_cannot_disable_own_org_chain`、`test_ac74_custom_scope_roots_and_multi_role`；事实记录 `test_focus1_observe_self_lockout_consequences_and_recovery`（200、`me`→401002、登录→401103、集团管理员可恢复）；E2E `test_ac74_ui_root_org_buttons_disabled_for_company_admin`（`is_disabled()` 为 False）。
- 备注：删除本公司节点在现有实现下被 409103/409104 兜底（有下级/用户），不会真的删掉。
- 状态：未修复（被测后端尚未包含 v0.3 规则）

### BUG-03 [一般][后端] 删除被角色引用的组织：公司级角色成孤儿，CUSTOM 范围保留已删除组织，授权保存报错
- 关联：AC-09、AC-14、F-04（对应重点关注 2；方案 5.2.8 的 409106 与 CUSTOM 清理未实现）
- 复现步骤：
  1. 建公司 C 并建公司级角色（owner_company_id=C）；删除 C（无下级、无用户）。
  2. 建 CUSTOM 角色，勾选部门 D1、D2；删除 D1。
  3. `GET /system/roles/{id}` 查看；再用回显的 `custom_org_ids` 原样 `PUT /grants`；或在页面打开授权抽屉直接点保存。
- 期望结果：步骤 1 删除返回 409106（列出角色，最多 10 个）；步骤 2 删除后角色的 `custom_org_ids` 自动移除 D1、bump epoch、记日志；保存授权成功。
- 实际结果：
  - 删除公司 C 返回 200，公司级角色仍在列表中，仍显示已删除公司名且 `editable=true`；
  - 删除 D1 返回 200，角色详情的 `custom_org_ids` 仍含已删除的 D1；再保存返回 400001“所选组织不存在”，页面上用户看不到该组织（树里没有），无法自行修复，页面提示“所选组织不存在”。
  - 积极面：持有者的数据范围会立即排除已删除组织，CUSTOM 组织全部被删后范围为空（不会放大成全部）；孤儿公司级角色可被删除；不能再给已删除公司建角色。
- 证据：集成 `test_focus2_role_detail_after_custom_org_deleted_can_be_resaved`、`test_ac74_409106_delete_company_with_company_roles`、`test_ac74_delete_org_cleans_custom_references_and_bumps_epoch`；E2E `test_role_custom_org_deleted_then_open_grant_and_save`（提示 `保存被拒: 所选组织不存在`）；`test_focus2_orphan_company_role_no_crash_and_manageable`（通过，记录现状）。
- 状态：未修复（被测后端尚未包含该规则）

### BUG-04 [一般][后端] AC-07 v0.3：集团节点下不能直接新建部门
- 关联：AC-07（v0.3）、F-02 规则 1/2、F-03 规则 1
- 复现步骤：超管 `POST /system/orgs {"parent_id":1,"org_type":"dept","name":"集团财务部","code":"X"}`。
- 期望结果：创建成功；该部门下用户的所属公司为集团（集团本部）。
- 实际结果：400 / 400001“部门的上级只能是公司或部门”。
- 证据：`test_ac07_v03_dept_directly_under_group_and_user_company_is_group`。
- 状态：未修复（被测后端尚未包含 v0.3 规则）

### BUG-05 [一般][后端] 超大整数 ID/参数与 NUL 字符导致 500（非 400001/404000）
- 关联：输入校验（契约 4.2：参数不合法应返回 400001）
- 复现步骤（任一，admin 身份）：
  - `GET /system/users/900000000000000000000`（orgs、roles、operation-logs 同样）；`GET /system/users?org_id=9e20`、`?page=9e20`；`GET /system/roles/assignable?user_id=9e20`；`GET /system/roles?owner_company_id=9e20`；
  - `POST /system/users`（org_id=9e20）；`POST /system/orgs`（parent_id 或 leader_user_id=9e20）；`PUT /system/orgs/3/move`（parent_id=9e20）；`POST /system/roles`（owner_company_id=9e20）；
  - 任何字符串字段含 `\u0000`：`POST` 用户/组织/角色名称、`GET /system/users?username=a%00b`、操作/登录日志的 `operator`/`username` 过滤、登录 `username`。
- 期望结果：400001（参数不合法）或 404000。
- 实际结果：500（500000“系统繁忙”，不暴露堆栈，但属于未处理异常）。
- 证据：`test_validation.py` 19 个参数化用例；`test_ac02_login_injection_payloads[a\x00b]`；`test_idor_id_type_tampering`；iam 日志 asyncpg `DataError`（BIGINT 溢出 / 0x00）。
- 可疑位置：id/org_id/page 等 int 字段、路径参数缺少 `ge/le` 约束（需限制在 BIGINT 范围）；字符串字段缺少 NUL 校验。
- 状态：未修复

### BUG-06 [一般][后端] 登录锁定可被并发请求绕过（暴力破解防护削弱）
- 关联：AC-02
- 复现步骤：对同一存在账号并发 12 个错误密码登录：`test_ac02_parallel_burst_guess_limit`。
- 期望结果：最多 5 次密码被实际校验，之后立即锁定。
- 实际结果：12 个请求全部在“检查锁”之后、“写失败计数”之前通过，12 次密码都被校验（均返回 401101）。并发越高，单个锁定周期内可用的猜测次数越多（受 bcrypt 耗时和连接池限制）。最终账号仍会被锁定。
- 证据：测试输出 `并发 12 次中有 12 次密码被实际校验（上限应为 5）`。
- 可疑位置：`auth_service.login` 先 `_lock_remaining`，再 `bcrypt`，最后 `_register_failure`，检查与计数之间没有原子性（例如先 `INCR` 占位再校验）。
- 状态：未修复

### BUG-07 [轻微][后端] 操作日志入库端不脱敏，其他服务误带明文凭据会原样落库
- 关联：AC-20、第 8 节安全（密钥/凭据不得明文出现在操作日志摘要）
- 复现步骤：向 `stream:oplog` 投递 `summary={"api_key":"sk-…","password":"P@ss12345","nested":{"token":"t0k"}}` 的合法事件，查询 `sys_operation_log.summary`。
- 期望结果：敏感键被掩码（与 `mask_sensitive` 一致）。
- 实际结果：明文入库。目前脱敏只在发送端 `emit_oplog` 做，iam 消费端不兜底；M2/M3 服务一旦绕过 `emit_oplog` 就会泄露。
- 证据：`test_ac20_sensitive_values_masked_in_incoming_events`。
- 状态：未修复

### BUG-08 [轻微][后端] Redis 停止时内部授权接口返回 500，应为 503001
- 关联：第 4 节服务故障约定（明确报错而非放行）
- 复现步骤：停止 `kbp-redis`，带正确内部令牌调用 `GET /internal/v1/authz/contexts/{uid}`。
- 期望结果：200（缓存写入失败只记日志）或 503001。
- 实际结果：500（500000）。
- 证据：`test_redis_outage_internal_authz_endpoint_returns_503_not_500`。对照：Redis 停止期间所有对外接口（已登录请求、登录、刷新、登出、写接口）均快速返回 503/503001（耗时 < 8s），`/readyz` 返回 503 且 `redis=fail`，`/healthz` 正常，无任何放行。
- 状态：未修复

### BUG-09 [轻微][后端/共享库] 日志消费者空闲时周期性报 ERROR；Redis 恢复后首个请求仍返回 503
- 关联：AC-20（日志管道）、第 4 节服务故障恢复
- 现象：
  1. 日志消费者 `StreamConsumer` 在流空闲时约每 8 秒打印一条 ERROR“消费循环异常，稍后重试”（`redis.exceptions.TimeoutError: Timeout reading from localhost:16379`），本轮运行 53 分钟累计 390 条，会淹没真实故障。
  2. Redis 容器重启并 healthy 后，iam 的第一个请求仍返回 503001（连接池里的旧连接失效，随后自愈）。测试中被触发了 3 次。
- 证据：`logs/iam.log`；手工验证“重启 Redis → 顺序请求 [503, 200, 200 …]”。
- 可疑位置：`events/consumer.py` 的 `block_ms=5000` 与 Redis 客户端读超时相当；`redis.py` 连接池未设置 `health_check_interval`/`retry`。
- 状态：未修复

### BUG-10 [轻微][后端] 令牌 `sub` 与会话 `sid` 的归属不校验
- 关联：AC-04（纵深防御）
- 复现步骤：用私钥签发 `sub=<员工 id>`、`sid=<admin 的有效会话>` 的令牌，调用 `/auth/me`。
- 期望结果：401002（会话不属于该用户）。
- 实际结果：200，以员工身份通过校验。利用前提是持有签名私钥，故评为轻微；会话 JSON 里已存 `user_id`，比对即可。
- 证据：`test_token_sub_sid_mismatch_rejected`。
- 状态：未修复

### BUG-11 [轻微][后端] 新密码为空字符串时返回 400001，提示为英文
- 关联：AC-06（“新密码不符合规则时，提示具体原因”）
- 复现步骤：`PUT /auth/password {"old_password":"…","new_password":""}`。
- 期望结果：400102 并给出中文具体原因。
- 实际结果：400001，`errors[0].message = "String should have at least 1 character"`。前端有自己的规则校验，直接调接口才会出现。
- 证据：`test_ac06_empty_new_password_message_is_chinese`。
- 状态：未修复

### BUG-12 [轻微][前端] 列表页接口失败时无错误占位和重试入口
- 关联：CLAUDE.md 第 6 节（每页处理加载/空/错误/无权限四种状态）
- 复现步骤：打开用户管理，拦截 `GET /api/v1/system/users` 返回 503，点击“查询”。
- 期望结果：表格区域显示错误状态并提供重试。
- 实际结果：只弹 toast“依赖服务暂不可用，请稍后重试”，表格仍显示旧数据，无错误占位、无重试按钮（左侧组织树有错误态与重试，ProTable 没有）。组织、角色、日志页使用同一模式，未逐页验证。
- 证据：E2E `test_user_list_error_state_has_retry_or_clear_message`，截图 `frontend/e2e/artifacts/user-list-error-state.png`。
- 状态：未修复

## 5. 回归记录

| 轮次 | 日期 | 重跑用例 | 结果 | 缺陷状态变化 |
|---|---|---|---|---|
| 第 1 轮 | 2026-11-11 | 全量（集成 234 + E2E 24） | 通过 216 / 失败 38 / 预期失败 4 | 新增 BUG-01 ~ BUG-12 |
| 第 2 轮 | 2026-11-11 | 全量（集成 266 + E2E 38，含旧用例按 v0.4 更新与新增用例） | 通过 304 / 失败 0 / 跳过 0 | BUG-01 ~ BUG-12 全部已修复；新增 BUG-13（轻微，待决策） |

## 6. 遗留问题与风险

需要用户/主会话决策的问题：

1. **账号大小写**：PRD 只说“账号全局唯一”。当前 `Alice` 与 `alice` 可作为两个账号（登录锁定计数也按原样区分）。是否要求不区分大小写？（用例 `test_ac10_username_case_variant_not_duplicable` 标为 xfail 待决策）
2. **SELF 范围看不到自己**：用户/组织由 admin 创建，`SELF` 角色（按 `created_by`）在用户列表和组织树里连自己都看不到。符合 PRD“创建人”定义，但可能不符合直觉，请确认。
3. **多角色并集解耦**：数据范围取所有启用角色的并集，与权限码来自哪个角色无关。例如角色 R1（日志权限，DEPT）+ R2（无日志权限，CUSTOM B 公司）时，操作日志可见 B 公司数据。符合“取并集”，请确认这是期望。
4. **内部令牌默认值**：`INTERNAL_API_TOKEN` 默认 `dev-internal-token-change-me`，持有它的人可拉取任意用户的权限上下文和用户同步数据。部署时必须覆盖；`TRUSTED_PROXIES` 默认含 127.0.0.1，经本机反向代理时 `X-Forwarded-For` 可被客户端伪造（登录日志 IP 取该头）。建议在部署文档（M3）中强调。
5. 3 个 xfail 对应主会话重点 1/2 的“待决策”：本公司节点停用（已被 AC-74 覆盖）、公司被公司级角色引用时的删除（已被 409106 覆盖）。待 BUG-02/03 修复后这些用例会转为实际通过。

未覆盖/受限项：

- 7 天未用刷新到期用 DB 改 `expires_at` 模拟；锁定到期用删除 Redis 锁键模拟（未等待真实 15 分钟/7 天）。
- 180 天日志清理定时任务仅在东八区 03 点执行，本轮未触发（开发单测已覆盖分批清理）。
- 前端仅验证 dev server，未验证生产构建；E2E 仅 Chromium。
- 下游联动（知识库数量、API 密钥数量、删除组织时的知识库检查）M1 未接入，仅验证降级文案与 503 行为。
- M1 只有 iam 一个服务，“停止单个服务时其他服务表现”不适用；已验证 Redis 故障。
- 压测仅覆盖列表查询 P95，未做持续并发压测；但 BUG-01 表明 20+ 并发登录即会出问题，上线前建议做登录并发压测。

## 7. M1 第 2 轮回归

- 依据：`prd.md` v0.4、`tech-design-m1.md`（5.2.0 / 5.2.0a / 5.9 / 第 12、13 节第 2 轮说明）
- 被测构建：工作区未提交代码；iam 以 `--env test` 启动（已用 `/proc/<pid>/environ` 核对 `DATABASE_URL=…/kbp_test`、`REDIS_URL=…/1`、`S3_BUCKET=kbp-test`），前端 vite 5174。测试结束后已停止 iam 与 vite，kbp-redis 保持运行（故障用例后已恢复，healthy）。
- 结论：**通过**（0 个失败；BUG-01 ~ BUG-12 全部修复；新增 1 个轻微问题 BUG-13，等待决策，不阻塞）

### 7.1 旧用例按 v0.4 更新（不算缺陷）

| 用例 | 变更 |
|---|---|
| `test_focus.py::test_focus1_observe_self_lockout_consequences_and_recovery` | 子公司管理员停用本公司 → 403102，状态不变、会话不受影响；改由超管停用后验证全员 401002/401103 与恢复路径 |
| `test_focus1_company_node_delete_blocked_by_children_and_users` | 子公司管理员删除本公司现先 403102（有用户/有下级时也一样）；超管才触达 409103 |
| `test_focus2_orphan_company_role_no_crash_and_manageable` | 删除被公司级角色引用的公司 → 409106；删除角色后可删公司 |
| `test_ac17_self_scope`（test_scope.py） | SELF 下用户列表只含本人账号且 `manageable=false`；组织树只读展示本人组织链（集团→A→研发部）；created_by=本人的用户可见且 `manageable=true` |
| 3 个 `xfail`（focus1 两个、focus2 删除公司）与账号大小写 xfail | 去掉 xfail 作为正式断言；大小写用例重写为 `test_ac10_username_case_sensitive_variants_are_distinct`（`ab`/`Ab` 各自可建、同值 409111、全大写变体登录 401101、两个真实账号各自可登录） |
| “多角色并集与权限来源无关” | 代码中本就是正式断言（`test_ac18_multi_role_union`），无 xfail；另新增 AC-76 用例 |

### 7.2 缺陷状态

| 缺陷 | 级别 | 第 2 轮结果 | 验证依据 |
|---|---|---|---|
| BUG-01 并发登录耗尽连接池 | 严重 | **已修复** | `test_ac02_concurrent_logins_do_not_exhaust_db_pool` 通过（24 并发全部 401101/401102，无 500，无 30s 挂起）；日志无 `QueuePool` 超时 |
| BUG-02 AC-74 管辖根/本人链保护 | 严重 | **已修复** | 集成 `test_ac74_*`（v03 5 个 + v04 8 个）、E2E 置灰/Tooltip 用例通过；`OrgNode` 带 `disable_blocked_reason`/`delete_blocked_reason` |
| BUG-03 删除被引用组织 | 一般 | **已修复** | 409106（含 `roles` 最多 10 个、`total`）、CUSTOM 引用自动清理、epoch 递增、操作日志含 `custom_role_refs_removed`；原“已删除组织无法保存授权”场景（集成 + E2E `test_role_custom_org_deleted_then_open_grant_and_save`）通过 |
| BUG-04 集团下建部门 | 一般 | **已修复** | `test_ac07_v03_*`、`test_ac07_v04_*`（子树/用户 company_id 随移动重算） |
| BUG-05 超大整数/NUL 导致 500 | 一般 | **已修复** | `test_validation.py` 19 个参数化用例、登录 `a\x00b`、`test_idor_id_type_tampering` 全部通过（400001/404000，无 500） |
| BUG-06 并发绕过登录锁定 | 一般 | **已修复** | `test_ac02_parallel_burst_guess_limit`：12 并发恰好 5 次校验密码 |
| BUG-07 入库端不脱敏 | 轻微 | **已修复** | `test_ac20_sensitive_values_masked_in_incoming_events` |
| BUG-08 Redis 停止时内部接口 500 | 轻微 | **已修复** | `test_redis_outage_internal_authz_endpoint_returns_503_not_500`（503001） |
| BUG-09 消费者空闲 ERROR / Redis 恢复后首请求 503 | 轻微 | **已修复** | 日志统计：iam 启动后空闲 9 分钟以上，除故意构造的死信与 Redis 停机窗口外零条“消费循环异常”（第 1 轮 53 分钟 390 条）；手工验证 `停止 kbp-redis → 503 → 启动并 healthy → 连续 5 个请求 [200,200,200,200,200]` |
| BUG-10 sub/sid 不校验归属 | 轻微 | **已修复** | `test_token_sub_sid_mismatch_rejected` |
| BUG-11 空新密码英文提示 | 轻微 | **已修复** | `test_ac06_empty_new_password_message_is_chinese`（400102 中文原因） |
| BUG-12 列表无错误占位/重试 | 轻微 | **已修复** | E2E `test_bug12_list_error_placeholder_and_retry`（用户/组织/角色/操作日志/登录日志 5 页，首次加载失败显示“加载失败 + 重试”、无旧数据，解除拦截后重试恢复）与 `test_bug12_user_list_error_after_query_clears_stale_rows_then_recovers`；截图 `frontend/e2e/artifacts/v04-list-error-*.png` |

#### 新增缺陷

### BUG-13 [轻微][契约/PRD] SELF 用户对自己创建的节点点击“移动”必然被 403101 拒绝，但界面仍显示“移动”按钮
- 关联：AC-75（“小组 1 可以按功能权限操作”）、tech-design-m1 5.2.0a（移动：节点、当前上级、新上级均用管理范围）
- 复现步骤：
  1. 用户 U（SELF，前端组成员）创建组织“小组 1”“小组 2”（均挂在只读的前端组下）。
  2. U 在组织页对“小组 1”点“移动”，目标选“小组 2”（可管理）或“研发部”（只读）。
  3. 或直接请求 `PUT /system/orgs/{小组1}/move {"parent_id": 小组2, "version": n}`。
- 期望结果：按 AC-75，“小组 1”可按功能权限操作；至少界面不应展示一个必然失败的按钮，或允许在管理范围内的节点之间移动。
- 实际结果：两种目标都返回 403 / 403101（“不能调整本公司节点的上级”）——因为当前上级“前端组”对 U 只读（5.2.0a 把“当前上级”也纳入管理范围校验，失败沿用 403101）；页面“移动”按钮仍显示（截图 `frontend/e2e/artifacts/v04-org-self-readonly.png`），文案“不能调整本公司节点的上级”对部门节点也不准确。
- 备注：行为与 tech-design-m1 5.2.0a 的写法一致，属于方案与 PRD 示例之间的缝隙，不是实现偏差；无越权风险（拒绝方向）。需要用户/架构师决定：(a) 保持现状并对“当前上级只读”的节点隐藏“移动”；(b) 允许 SELF 用户在其管理范围内移动。
- 状态：新增（待决策）

### 7.3 新增用例与结果

| 范围 | 用例 | 结果 |
|---|---|---|
| AC-74 | `test_v04.py`：M 的树提示与请求一致（公司节点两个按钮 403102 文案、研发部停用 403103/删除无提示、测试部与下级无提示、详情接口同源、拒绝后状态不变、已停用节点停用提示为空）；判定顺序（403102 先于 403103、集团节点 400114、超管看到集团节点两提示均为“集团节点不能移动、停用或删除”）；G（ALL）树提示与请求（集团财务部停用 403103、删除走 409104、停用 A 公司成功）；S0 超管本人链 403103、集团节点 400114；4 种范围（DEPT / DEPT_AND_CHILD / COMPANY / COMPANY_AND_CHILD）的管辖根；CUSTOM 嵌套勾选只取最上层根、已删除组织被忽略；多角色并集 + 停用角色后收缩 + 加 ALL 角色后解除管辖根限制；只读节点写请求 403001 先于 403102/403103 | 通过 |
| AC-75 | SELF 用户列表（本人 manageable=false + 本人创建的 X manageable=true，不含同组同事 Y，按 org_id 过滤不泄露）；组织树/选择器/详情（链路只读、`*_blocked_reason` 为空、B 公司 404000）；对只读节点的 10 类写请求（编辑/移动/停用/删除/新增下级、在只读组织建用户、编辑/停用/重置密码/分配角色/删除本人）全部 403001 且库无变化；完全不可见资源的 10 类请求统一 404000 且与不存在 ID 响应一致；可管理节点可编辑/停用/启用；`assignable` 对只读本人 404000；SELF+DEPT 并存按行 manageable；SELF+ALL 无只读行；非 SELF 范围无链路特例 | 通过 |
| AC-76 | R1(DEPT)+R2(COMPANY，仅 `kb:admin:list`)：Z 可见 → 停用 R2 后不可见（列表与详情 404000）、权限码消失、启用后恢复；范围来自无用户功能的 CUSTOM 角色同样并入 | 通过 |
| AC-07（v0.4） | 集团直属部门及其子部门/用户 company_id=集团；移到公司下子树与用户 company_id 随之重算、移回恢复；公司仍不能挂在部门下；子公司管理员看不到集团本部部门（404000） | 通过 |
| 409106 / CUSTOM | 判定顺序 409103 → 409104 → 409106；`total` 与名单、已删除角色不计入、清空后可删；子公司管理员删本公司 403102 先于 409106、删下级公司 409106；CUSTOM 引用清理（多角色引用、epoch 递增、日志含 `custom_role_refs_removed`、无引用时不含、空 CUSTOM 保存 400121、回显原样保存成功） | 通过 |
| no-op | 状态未变化：不吊销会话、不写日志；版本冲突 409001 先于 no-op | 通过 |
| AC-10 | 账号区分大小写（见 7.1） | 通过 |
| `validate_for_runtime` | 独立子进程 `test_zz_runtime_config.py`（端口 18391~18393，不影响主服务）：`APP_ENV=prod` + 默认令牌、`prod` + 短令牌 `short-token`、`staging` + 默认令牌 → 进程退出码非 0，日志 CRITICAL“必须覆盖配置项 INTERNAL_API_TOKEN”；`prod` + 32 位以上令牌 与 `dev` + 默认令牌 → 正常启动、`/healthz` 200 | 通过 |
| E2E AC-74 | `test_m1_v04.py`：M 登录——公司节点停用/删除置灰并显示 403102 Tooltip、研发部停用置灰（403103 Tooltip）删除可用、测试部均可用；点击置灰按钮无任何 PUT/DELETE 请求、无确认弹窗；停用测试部二次确认后成功、出现“启用”；G 登录——集团财务部停用置灰、公司可用、集团节点置灰并显示“集团节点不能移动、停用或删除”；过期页面（抹掉提示字段）仍发起请求时展示后端 403102 文案且状态不变 | 通过 |
| E2E AC-75 | SELF 用户组织页：集团/公司/研发部/前端组各行显示“只读”且无任何管理按钮，小组 1 行有“新增下级/编辑/移动/停用/删除”；“上级组织”选择器中只读节点置灰、小组 1 可选；用户页：本人行“只读”无按钮、X 行有“编辑”、同事 Y 不可见；新增用户“所属组织”选择器同样置灰；过期页面对只读节点发起停用 → 展示 403001“无权限”提示 | 通过 |
| E2E AC-76 | 授权抽屉“数据范围”区域固定显示“用户拥有多个角色时，数据范围取所有启用角色的并集，并对该用户拥有的所有功能生效。”，切换范围后仍在 | 通过 |
| E2E 409106 | 删除含 3 个公司级角色的公司：弹窗标题“该公司下仍有公司级角色，不能删除”，列出 3 个角色名与“共 3 个”，关闭后公司仍在 | 通过 |
| E2E BUG-12 | 见 7.2 | 通过 |

### 7.4 用例汇总与回归记录

- 集成 266 个（含新增 `test_v04.py` 28、`test_zz_runtime_config.py` 4，第 1 轮其余用例全部重跑），全部通过；E2E 38 个（第 1 轮 24 + 新增 14），全部通过；失败 0、跳过 0、xfail 0。
- 重跑范围：登录/刷新/改密/会话失效（AC-01 ~ AC-06）、用户/角色/组织增删改（AC-07 ~ AC-16）、7 种数据范围与并集、日志、Redis 故障（停止/恢复 kbp-redis，已恢复 healthy）、性能（2 万用户/2000 组织/10 万日志的列表 P95 均 ≤ 1s，本轮复跑通过）。无回归。
- AC 覆盖矩阵：22 个 M1 AC（AC-01 ~ AC-21、AC-74）+ AC-75、AC-76 共 24 / 24 有用例并通过；AC-17/18/19/20 中属于 M2/M3 的部分（知识库管理视图、API 密钥审计、转移所有权）仍不适用；AC-75 末条“知识库管理视图仍只看自己的知识库”属 M2，不适用。AC-18 补充（停用其中一个角色后范围收缩）由 `test_ac18_union_company_and_dept_scopes` 与 AC-76 用例覆盖。

| AC | 第 2 轮结果 |
|---|---|
| AC-01 ~ AC-06、AC-08 ~ AC-16、AC-19 ~ AC-21 | 通过（回归） |
| AC-07 | 通过（含集团下建部门） |
| AC-17 | 通过（SELF 期望已按 v0.4 更新） |
| AC-18 | 通过 |
| AC-74 | 通过 |
| AC-75 | 通过（BUG-13 为按钮体验问题，不阻塞） |
| AC-76 | 通过 |

### 7.5 遗留与风险

1. BUG-13 等待决策（见上）。
2. 角色 CUSTOM 组织选择器对 `manageable=false` 节点置灰：SELF 用户无法维护角色（创建角色被 403125），该界面在 M1 内无法通过 SELF 账号到达；混合角色用户的该选择器未做 E2E，仅 `OrgTreeSelect` 的组织/用户两处用法被验证，后端校验（管理范围）有 `assignable` 用例覆盖。
3. 未修复的第 1 轮决策项 4：`TRUSTED_PROXIES` 默认含 127.0.0.1，经本机反向代理时 `X-Forwarded-For` 可被客户端伪造（登录日志 IP 取该头），建议在部署文档强调；`INTERNAL_API_TOKEN` 默认值问题已由 `validate_for_runtime` 在 prod/staging 拦截。
4. 登录锁定原子化的副作用（开发已说明）：同一账号并发在途登录超过 5 个时，超出部分即使密码正确也会被判锁定，属于已知取舍，未单独测试。
5. 延续第 1 轮：前端仅验证 dev server 与 Chromium；7 天刷新到期/15 分钟锁定到期用改库/删键模拟；180 天日志清理定时任务未触发；下游联动（知识库/API 密钥）M1 未接入。
6. 共享库已知问题（Redis db1 的 `authz:epoch` 非空导致共享库某单测失败）与本轮无关，未处理。
