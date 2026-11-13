# 企业级知识库管理平台 测试报告（M1 第 1~2 轮；M2/M3 第 1 轮见第 8、9 节；M2/M3 第 2 轮回归见第 10 节）

> **总体结论（最新，2026-11-13）：通过，可交付验收。** BUG-14 ~ BUG-20 全部关闭；后端集成 455/455、前端 E2E 104/104 通过；真实模型网关冒烟通过（第 11 节）。
>
> M1 第 2 轮回归结果见第 7 节；第 1~6 节为 M1 第 1 轮原始记录（缺陷状态以第 7 节为准）；M2 第 1 轮见第 8 节，M3 第 1 轮见第 9 节（BUG-14 ~ BUG-18 的状态以第 10 节为准）。

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


---

## 8. M2 第 1 轮（知识库 kb + kb-worker + 前端页面）

- 关联文档：`./prd.md`（AC-22 ~ AC-51、AC-63 ~ AC-69）、`./tech-design-m2.md`（含第 12/13 节、BE-21b 验收结论）
- 日期：2026-11-12；被测构建：HEAD `8c06ac1`（工作区干净）。
- 结论：**有条件通过**——无致命/严重缺陷；3 个轻微缺陷（BUG-14 ~ BUG-16）；M2 全部 AC 均有用例覆盖。真实模型网关冒烟不在本轮（由主会话完成）。

### 8.1 测试环境与数据

- 服务：`devctl --env test up -d` 启动 iam / kb / kb-worker / open；库 `kbp_test`、Redis db1、桶 `kbp-test`（每次会话开始由 `reset_env.sh` 清空 iam+kb 表、Redis 相关键、测试桶对象，并重启 kb-worker 触发副本全量同步）。开发库 `kbp`、`kbp-prod` 及其他项目容器未触碰；开发服务测试前未运行。
- 假模型：`scratchpad/fakemodel.py`（本机 19997：`/v1/embeddings` 32 维字符二元组哈希向量、`/v1/rerank` 字符重叠打分；`/_ctl` 可切换失败/延迟/要求 Bearer 密钥；查询含 `BOOM`/`RRFAIL` 触发 500）。没有使用 `backend/.env` 的真实网关，也未读取其密钥。
- 组织：集团 → `qaA公司`（研发部 → 前端组、测试部、产品部；子公司 `qaA1` → 部门）、`qaB公司`（一部）。账号：gadmin（集团管理员）、aadmin（A 公司管理员）、badmin、own/own2（研发部员工）、edit（产品部）、read（测试部）、read2（前端组）、a1（子公司员工）、out（同部门无分配）、bstaff（B 公司）、noperm（无角色）；管理视图 7 种数据范围由每个用例临时建角色与账号。
- 文件：`backend/services/kb/tests/integration/gen_files.py` 生成 txt/md/csv/xlsx/docx/pdf（手写最小 PDF，pypdf 可提取）与 **`.xls`**。环境没有 LibreOffice Calc/xlwt，故把 `xlwt 1.3.0` 用 `pip install --target` 装到会话临时目录（**未改动项目 .venv**）生成真正的 Excel 97-2003 BIFF8（`file` 识别为 `CDFV2 Microsoft Excel`，魔数 `D0CF11E0`，含两个工作表），用例 `test_xls_is_real_biff_binary_and_sheet_headings` 校验魔数与解析结果（`# 人员`、`姓名: 孙八`、`金额: 30000`）。
- 测试代码（均不进 git）：`backend/services/kb/tests/integration/`（`kit.py`、`conftest.py`、`reset_env.sh`、`gen_files.py`、`test_01 ~ test_08`）；`frontend/e2e/test_m2_kb.py`（Python Playwright，失败截图/trace 在 `frontend/e2e/artifacts/`）。
- 复跑：`.venv/bin/python -m pytest backend/services/kb/tests/integration -q`（约 8 分钟）；E2E 需先起服务 + 假模型 + `pnpm dev`，`cd frontend/e2e && python3 -m pytest test_m2_kb.py`。

### 8.2 结果汇总

| 类别 | 用例数 | 通过 | 失败 | 说明 |
|---|---|---|---|---|
| kb 集成（pytest + httpx，真实服务） | 122 | 121 | 1 | 失败 = BUG-14；首轮另有 3 个用例因测试数据串扰失败，属用例缺陷，已修正并重跑通过 |
| 前端 E2E（Playwright/Chromium） | 20 | 18 | 2 | 失败 = BUG-15、BUG-16（用例即缺陷证据） |
| M1 回归（既有 iam 集成套件，排除 `test_zz_redis_down`/`test_zz_perf`） | 257 | 257 | 0 | 排除项会停 Redis 容器/压测，本轮不执行 |
| 合计 | 399 | 396 | 3 | 通过率 99.2%（缺陷用例 3 个均为真实缺陷） |

### 8.3 AC 覆盖矩阵

| AC | 用例（文件::用例） | 结果 |
|---|---|---|
| AC-22 | test_01::test_ac22_*（连接成功回填维度、错地址返回 success=false 不抛 503、启用失败 400301、维度不一致、凭据掩码且不进日志/列表）；E2E test_ac22_model_config_* | 通过（并发同名建模型 500 见 BUG-14） |
| AC-23 | test_01::test_ac23_*（409302 带知识库名、409301 改地址/标识/维度、停用后上传/预览/向量/全文/混合检索均 409303）| 通过 |
| AC-24 | test_01::test_ac24_*（aadmin/员工/无权限/B 员工全部模型接口 403；options 无地址与凭据）；E2E test_ac24_* | 通过 |
| AC-25 | test_02::test_ac25_stats_exact（3 可用文档 10/20/30 段、禁用 5 段、1 失败、1 处理中 → 5/1/1/60，字符数=可用文档之和）、test_ac25_parent_child_stats（父 4/子 12） | 通过 |
| AC-26 | test_02/test_03::test_ac26_*（含 aadmin 不出现他人库）；test_06::test_ac26_admin_view_not_in_my_list | 通过 |
| AC-27 | test_02::test_ac27_*；E2E test_ac27_empty_state_*（空状态 + 创建按钮；无权限 403 + 无菜单） | 通过 |
| AC-28 | test_02::test_ac28_*（默认值、所有者/组织、收回新建权限 403、模型无效 400303）；E2E test_ac28_ac29_* | 通过 |
| AC-29 | test_02::test_ac29_*、并发创建同名（test_08）无 500 | 通过 |
| AC-30 | test_02::test_ac30_*（400311/400001、软删、检索标志清零、同名可重建、日志含分配数）；E2E test_ac48_settings_*（删除需输入名称、提示分配数） | 通过 |
| AC-31 | test_02::test_ac31_*、test_03 矩阵（可编辑不能删/分配/转移/改模型；管理员 404000） | 通过 |
| AC-32 | test_02::test_ac32_*（409312、403311、409503 锁定） | 通过 |
| AC-33 | test_03::test_ac33_*、test_dept_include_children_semantics | 通过 |
| AC-34 | test_03::test_ac34_*（选择器不含 B 公司/集团节点；400402；集团员工分配 B 公司含下属后可见） | 通过 |
| AC-35 | test_03::test_ac35_*、调岗/停用/收回功能码即时生效 | 通过 |
| AC-36 | test_04::test_ac36_*（.exe/无扩展名/双扩展名/0 字节/15MB+1/20MB PDF/损坏 docx、pdf、xlsx、xls/伪 docx/加密 PDF；恰好 15MB 通过；提交 21 个 400001）；E2E test_ac36_*（逐文件标红原因、>20 个限制） | 通过 |
| AC-37 | test_04::test_ac37_*（预览前 10 段 ≤200 tokens；与处理后分段逐段一致，7 种类型矩阵同样校验） | 通过 |
| AC-38 | test_04::test_ac38_*（改名重复 409501 含原文档名；同批重复；删除后可再传）；并发提交同内容只一个成功 | 通过 |
| AC-39 | test_04::test_ac39_*（30/49/4001/5000、重叠 >50%、空/超长分隔符、子块>父块、超模型 max_input_tokens=512 均 400001；边界 50/512/50% 通过）；E2E test_ac39_* | 通过 |
| AC-40 | test_04::test_ac40_*（queued→parsing→splitting→indexing→available 单调，可用前检索不到） | 通过 |
| AC-41 | test_04::test_ac41_*（索引中停用模型 → EMBEDDING_DISABLED；停用时重试 409303；恢复后重试可用；可用文档重试 409505；索引卡死改库后巡检 → TIMEOUT 可重试） | 通过 |
| AC-42/43 | test_04::test_ac42_ac43_*、test_ac25（删除后 60→40 的统计）、处理中删除文档/知识库（test_04、test_08） | 通过 |
| AC-44 | test_04::test_ac44_*（丢弃人工编辑、处理期间不可检索、409001/409503/409504） | 通过 |
| AC-45 | test_05::test_ac45_*（索引更新期间检索旧内容、完成后新内容、已编辑、400511/400512 边界）；E2E test_ac45_* | 通过 |
| AC-46 | test_05::test_ac46_*（向量/全文/混合均不返回；列表仍可见；恢复/删除） | 通过 |
| AC-47 | test_03 ACL 矩阵（只读对全部写接口 403311 且无副作用）；E2E（只读无编辑按钮/开关禁用） | 通过 |
| AC-48 | test_02::test_ac48_*（0/21/1.2/步长/非法方式/无 rerank 模型）；E2E test_ac48_* | 通过 |
| AC-49 | test_05::test_ac48_ac49_threshold_filters_exactly（动态取第 3/4 名中点，只返回前 3 条） | 通过 |
| AC-50 | test_05::test_ac50_*（降序、4 位小数、Top K 临时覆盖不改默认、记录 +2 仅本人、保留 20 条、只读可测） | 通过 |
| AC-51 | test_05::test_ac51_*（高阈值无结果；embedding 500 → 503301，全文不受影响；rerank 500 → 503301）；E2E 空结果提示/错误提示 | 通过 |
| AC-63 | test_04::test_ac63_*（父块≤1024、子块≤256、预览=处理结果、锁定父子；全文模式超长 400506） | 通过 |
| AC-64 | test_05::test_ac64_*（父块去重、得分=最高子块分、子块降序、条数≤Top K）、内部检索接口同结构 | 通过 |
| AC-65 | test_05::test_ac65_*（子块编辑、父块 409512 确认后重建、新增子块可检索、禁用父块子块不召回、409511、父子文档新增分段 400513） | 通过 |
| AC-66 | test_02::test_ac25_parent_child_*；E2E test_ac66_ac25_*（列表“通用分段/父子分段”“父块 6 / 子块 n”） | 通过 |
| AC-67 | test_06::test_ac67_*（元信息/分配/文档/分段可看；audit_entry、30 分钟去重、翻页不重复记录、兜底留痕；16 种写/召回/下载请求全部被拒且无副作用）；E2E test_ac67_ac68_*（横幅“审计查看，操作将被记录”、无写入口） | 通过 |
| AC-68 | test_06::test_ac68_*（范围外/停用/不存在/自己 400321/400322，同名 409321 含 conflicts，409001，成功后组织=产品部、原所有者 404、测试部分配保留）、所有者自行转移范围、并发转移只一个成功；E2E 转移流程 | 通过 |
| AC-69 | test_06::test_ac69_*（停用后分配部门成员仍可访问；待交接筛选 3 个、所有者“已停用”；批量转移冲突整体回滚；成功后待交接为空） | 通过 |
| AC-17/18/19（kb 管理视图视角） | test_06::test_ac17_*（ALL/COMPANY_AND_CHILD/COMPANY/DEPT_AND_CHILD/DEPT/SELF/CUSTOM 列表+按 ID 直访+文档列表）、并集、超管（且超管无日常访问，AC-73） | 通过 |

### 8.4 多维度结论

1. **功能**：知识库 CRUD、上传向导、通用/父子分段、解析失败与重试、文档启停删除、分段增删改启停、检索（向量/全文/混合/阈值/Top K/Rerank 降级）、模型配置（测试连接/启停/默认/被引用保护）、管理视图与转移全部通过；文件类型 txt/md/csv/xlsx/**xls（真 BIFF8）**/pdf/docx 均完成“上传→预览→处理→分段内容→下载字节一致”，另测 html、pptx、GBK/UTF-8 BOM/UTF-16 文本、无文本 PDF（NO_TEXT）。结论：通过。
2. **权限/越权**：约 40 个 kb 接口 ×（未登录 401；无功能权限 403）及核心读写接口 ×（owner/edit/read/无分配矩阵）全部符合 403311/404000；路径中的 dataset 与对象（segment/document/assignment）不匹配的 IDOR 全部 404 且无副作用；伪造 token（alg=none、篡改 payload、HS256+公钥算法混淆、过期、不存在的 sid、非 Bearer）全部 401；登出/改密（他会话）/重置/停用/改角色/收回权限码/调岗跨服务即时生效。结论：通过。
3. **数据范围**：管理视图 7 种范围 + 并集 + 超管见 8.3 AC-17~19；部门含/不含下级、公司含/不含下属的分配成员判定通过（注：公司分配“不含下属”= 该公司全员含其下属部门，仅不含子公司，符合 3.1 设计）。结论：通过。
4. **边界异常**：空/超大/不支持类型/伪装与损坏/加密文件、文件名特殊字符（路径穿越、CRLF、引号、emoji、XSS、SQL、250/400 字符）、NUL 字节（上传内容、分段内容均无 500）、超长/空白/501 字查询、tsquery 特殊字符（21 种载荷 × 3 种检索方式，均无 500）、分段长度上下限、分页越界（page=0/超大/page_size 0 与 101）、文档数上限 409502（向测试库灌入 9998 行后验证）、并发上传 12 个文件、worker 停止后恢复、worker `kill -9` 后接管恢复。结论：通过（BUG-14）。
5. **并发/幂等**：并发提交同一 upload（1 成功）、同内容不同 upload（1 成功）、并发重试同一失败文档（1 成功，分段位置无重复无空洞）、并发保存同一分段版本（409511）、并发转移（1 成功）、并发创建同名知识库/并发重复分配（均 409 无 500）。并发创建同名模型返回 500 见 BUG-14。
6. **回归**：M1 既有集成套件 257 通过；本轮另验登录/菜单（kb 菜单出现且员工无“模型配置”“知识库管理”）/组织/用户/角色，组织移动到另一公司后知识库所属公司随之重算（3.9）。结论：通过。
7. **UI**：列表页加载（骨架屏）/空/错误（重试）/无权限（403）四态；上传向导主流程（选文件→逐文件校验→预览→保存并处理→可用）；文档页启停与删除二次确认；分段编辑；召回测试空结果与模型错误态；设置页校验与删除需输入名称；模型配置测试连接；管理视图只读横幅与转移；XSS 载荷（知识库名/描述/文件名）按文本渲染。结论：通过（BUG-15、BUG-16）。
8. **服务故障与一致性**：iam 停止且 Redis 权限上下文缓存为空时 kb 返回非 200（fail-closed，不放行）；kb 停止时 iam 不受影响；worker 停止时文档保持 queued、读与检索不受影响、重启后自动处理完成；worker 被 `kill -9`（向量化中途，`TASK_CLAIM_IDLE_SECONDS=120`、`SWEEP_INTERVAL_SECONDS=5`）后新 worker 接管并补齐向量；Redis 容器停止未执行（`kbp-redis` 与开发共用，M1 已验证）。结论：通过。

### 8.5 缺陷列表

### BUG-14 [轻微][后端] 并发创建同名模型返回 500（应为 409304）
- 关联：AC-22（模型配置）、4.3 接口约定（业务冲突应为 409 而非 500）
- 复现步骤：以集团管理员并发（≥4 个线程）对 `POST /api/v1/kb/models` 提交同一 `name`（如 `{"name":"cm1","model_type":"embedding","base_url":"http://127.0.0.1:19997/v1","model_name":"f","dimension":32,"status":"disabled"}`）。用例 `test_08_extra.py::test_concurrent_model_create_same_name_no_500`。
- 期望结果：1 个成功，其余返回 409 / 409304“模型名称已存在”。
- 实际结果：1 个成功，其余部分返回 409304，部分返回 500 `{"code":500000,"message":"系统繁忙，请稍后重试"}`。
- 证据：kb 日志 `数据库异常`（path `/api/v1/kb/models`，唯一约束冲突）。知识库同名（409311）、重复分配（409401）的并发场景均已正确处理，仅模型创建缺少对唯一约束冲突的捕获。
- 可疑位置：`backend/services/kb/app/services/model_service.py::create`（先查后插，仅在 `exc` 处映射了部分路径，并发时第二个 INSERT 违反唯一索引未转换为 `ERR_DUP_NAME`；改名更新路径同理需确认）。
- 状态：**已关闭**（第 2 轮验证，见第 10 节）

### BUG-15 [轻微][前端] 二次确认弹窗的取消按钮显示英文 “Cancel”
- 关联：CLAUDE.md 第 6 节（只做简体中文）
- 复现步骤：用 owner 登录 → 知识库 → 文档页 → 点击某文档“删除”。用例 `test_ui_confirm_dialog_buttons_are_chinese`（截图 `frontend/e2e/artifacts/test_ui_confirm_dialog_buttons_are_chinese-0.png`）。
- 期望结果：取消按钮为“取 消”。
- 实际结果：按钮文案为 `Cancel`（确认按钮 `okText: '删除'` 为中文）。
- 影响范围：`App.useApp()` 的 `modal.confirm` 未传 `cancelText` 的位置都可能受影响（kb 文档/分段/分配/设置、系统管理多处使用同一写法，本轮只验证了文档删除）。
- 可疑位置：`frontend/src/pages/kb/detail/documents/index.tsx::confirmDelete`；整体上 `App.tsx` 的 `ConfigProvider locale={zhCN}` 未作用到 `modal.confirm` 的静态弹窗（建议统一在 `<App>` 的 context 或封装 `confirm` 工具里设置 `cancelText`）。
- 状态：**已关闭**（第 2 轮验证，见第 10 节）

### BUG-16 [轻微][PRD/契约 + 前端] 上传向导默认分段参数在默认模型下即校验失败，必须先手动改小才能预览
- 关联：AC-36/AC-37（向导主流程）、tech-design-m2 3.5（max_tokens ≤ 模型 max_input_tokens）与 5.1（模型 `max_input_tokens` 默认 512）
- 复现步骤：配置 Embedding 模型时不填“最大输入 tokens”（默认 512）→ 创建知识库 → 上传文档 → 第 2 步“分段设置与预览”。用例 `test_ui_upload_wizard_default_rule_is_valid_with_default_model`（截图 `test_ac36_ac37_upload_wizard_main_flow_and_file_validation-0.png` 的前一轮）。
- 期望结果：默认参数可直接预览/提交（或界面按模型上限自动夹取默认值）。
- 实际结果：默认“分段最大长度 1024”被红字提示“不能超过所选向量模型的单次最大输入（512 tokens）”，预览按钮置灰；用户必须先改参数。真实模型通常为 8192 时不受影响，但模型默认值 512 与分段默认值 1024 相互矛盾，属契约默认值不一致。
- 建议决策：模型 `max_input_tokens` 默认值改为不小于 1024，或向导默认值取 `min(1024, 模型上限)`（需主会话与架构师确认）。
- 状态：**已关闭**（第 2 轮验证，见第 10 节）

### 8.6 观察项与风险（非缺陷，供决策）

1. **worker 崩溃接管的时序依赖**：文档处理锁 TTL（`DOC_LOCK_TTL_SECONDS=90`，带心跳）与 `TASK_CLAIM_IDLE_SECONDS=600` 必须保持“接管空闲 > 锁 TTL”。实测把接管空闲调到 15 秒（小于锁 TTL）时，接管者因锁未过期把任务当“重复投递”确认丢弃，文档停在“索引中”，直到 30 分钟巡检置为“处理超时”（可重试）；调到 120 秒（> 锁 TTL）则正常恢复。默认配置（600 秒）无此问题，建议在配置校验里加该不等式约束或在 `.env.example` 注明。
2. **对象存储残留与键冲突**：删除文档/知识库不物理删除 MinIO 对象（设计已声明）；解析文本键 `parsed/{upload_file_id}.txt` 只含自增 ID，测试中重置数据库而未清空桶时，新文档被复用旧解析文本（内容串到别的文件）。生产正常运行不会触发，但“库重建/恢复备份/ID 回绕”场景需同时清桶，建议运维文档注明或键加入知识库/哈希。
3. 改密时“当前会话保留、其他会话失效”（tech-design-m1 5.1 既定，与 PRD AC-05 “所有会话失效”字面有出入，M1 已决策，本轮仅在 kb 侧验证一致）。
4. 公司分配“不含下属”按设计 = 该公司全部人员（含其部门），仅排除子公司；如产品原意是“仅公司节点直属人员”需确认。
5. 未覆盖：Redis 容器停止（与开发共用，不执行）；解析炸弹（高压缩比 docx/xlsx、百万行 xlsx）与 15MB 大 PDF 解析耗时；BE-21b 检索性能（10 万分段 P95）未复测；HNSW 索引创建/对账只在小库走精确路径；真实模型网关冒烟（主会话负责）；`KB_STATS_ENABLED` 开启时的组织删除联动（iam 测试实例未开启该开关）；浏览器仅 Chromium。
6. 测试期间文档无更新；用例中少数宽松断言（接受 200/400）用于“不得 500”类探测，已在用例注释标明。

### 8.7 发布建议

- 本轮 M2 功能、权限、数据范围、并发与故障恢复均通过，无致命/严重缺陷，**建议可发布**（有条件）：BUG-14/15/16 均为轻微，可随后续修复，其中 BUG-16 需主会话确认默认值口径；发布前由主会话用真实 Embedding/Rerank 网关做一次冒烟（含 .xls 真实文件、真实维度与 HNSW 索引创建）。
- 修复后回归：重跑 `test_08_extra.py::test_concurrent_model_create_same_name_no_500` 与 E2E 两个 `test_ui_*` 用例即可。

## 9. M3 第 1 轮（open 开放平台服务 + 前端四页面）

- 关联文档：`./prd.md`（F-17 ~ F-19，AC-52 ~ AC-62、AC-70 ~ AC-73）、`./tech-design-m3.md`（5.0 错误码、5.1.0 操作矩阵、第 12/13 节）
- 日期：2026-11-12 ~ 13；被测构建：HEAD `8c06ac1` + 工作区未提交改动（含前端智能体修 BUG-15/16 的改动，BUG-15 在本轮已观察到修复）。
- 结论：**不通过（有条件）**——无致命缺陷；2 个一般缺陷（BUG-17、BUG-18）。建议修复 BUG-17 后发布，BUG-18 视部署形态决策（生产经 Nginx 且 TRUSTED_PROXIES 正确时无实际影响）。

### 9.1 测试环境与数据

- 服务：`devctl --env test` 启动 iam / kb / kb-worker / open；库 `kbp_test`、Redis db1、桶 `kbp-test`；iam 以 `OPEN_STATS_ENABLED=true` 启动。未使用 `backend/.env`、开发库 `kbp`、`kbp-prod` 与其他项目容器。
- 假模型：scratchpad `fakemodel.py`（19997，embedding/rerank，可切换失败/延迟）。另有三个本轮自带的辅助进程：假 kb 检索端点 `mockkb_m3.py`（19996，用于触发 kb 异常映射/500000/超时）、第二至第四个 open 实例（8393 指向假 kb 且超时 2s；8394 `TRUSTED_PROXIES` 与 `FORWARDED_ALLOW_IPS` 均不含回环；8395 只改 `TRUSTED_PROXIES`）、本机 `nginx:alpine` 容器（host 网络，18081，使用 `frontend/nginx/default.conf.template` 同款配置，测试后已删除）。
- 组织与账号：集团 → qaA公司（研发部、测试部、子公司 qaA1 → 部门）、qaB公司（一部、二部）；集团管理员、A/B 公司管理员、u1/u2（研发部）、u3（测试部）、a1（子公司）、b1/b2、无权限用户；动态用例临时建用户/角色（7 种 data_scope 各建一个审计角色）。
- 测试代码（不进 git）：`backend/services/open/tests/integration/`（`kit.py`、`conftest.py`、`reset_env.sh`、`mockkb_m3.py`、`test_01 ~ test_05`）；`frontend/e2e/test_m3_open.py`（Python Playwright）。
- 复跑：`.venv/bin/python -m pytest backend/services/open/tests/integration -q`（约 4 分钟，自带重置并重启服务）；E2E 需先起服务 + 假模型 + `pnpm dev`，`cd frontend/e2e && python3 -m pytest test_m3_open.py`（约 3 分钟）。

### 9.2 结果汇总

| 类别 | 用例数 | 通过 | 失败 | 说明 |
|---|---|---|---|---|
| open 集成（pytest + httpx，真实服务） | 71 | 68 | 3 | 失败 = BUG-17（2 个用例：Embedding、Rerank 上游失败）、BUG-18（1 个用例） |
| 前端 E2E（Playwright/Chromium） | 14 | 14 | 0 | 四页面四态、明文弹窗、admin_disabled 按钮、审计开关 |
| M1 回归（iam 集成套件，排除 redis_down / perf） | 257 | 257 | 0 | |
| M2 回归（kb 集成套件） | 122 | 122 | 0 | BUG-14 已不复现 |
| 合计 | 464 | 461 | 3 | 通过率 99.4%（3 个失败均为真实缺陷） |

首轮编写阶段有若干用例因测试代码自身问题失败（共享密钥触发限流、HTTP 头非法字符、对契约理解有误等），已修正，不计入缺陷。

### 9.3 AC 覆盖矩阵

| AC | 用例（文件::用例） | 结果 |
|---|---|---|
| AC-52 | test_01::test_ac52_*（43 位格式、仅两个接口出现明文、列表/详情/日志/名单均无明文、库内只存哈希、操作日志与服务日志无明文）；E2E test_ac52_*（弹窗不可 Esc/遮罩/右上角关闭，勾选后才能关闭，关闭后 DOM 与 storage 无明文，重新生成流程） | 通过 |
| AC-53 | test_01::test_ac53_*（选项不含他人库与管理视图可见库；提交他人库 400601 带 dataset_ids；管理员也不能选；被只读分配后可选）、test_no_manage_perm_forbidden | 通过 |
| AC-54 | test_01::test_ac54_*、test_02::test_403601_*、test_ac54_owner_disable_enable、test_owner_deleted_and_perm_revoked（停用/过期/重新生成/删除/创建人停用后恢复/删除创建人/收回 manage） | 通过 |
| AC-55 | test_03::test_ac55_*、test_scope_lists_*；E2E test_ac55_ac72_*（B 公司密钥不可见） | 通过 |
| AC-56 | test_02::test_ac56_*、test_consistency_with_kb_retrieve_test（向量/全文/混合×3 查询，段 ID、得分、内容与 kb 召回测试逐项一致；阈值同参一致） | 通过 |
| AC-57 | test_02::test_ac57_*（存在无权 / 不存在响应除 request_id 外逐字节一致） | 通过 |
| AC-58 | test_02::test_ac58_*（14 种畸形/无效密钥；Bearer 大小写不敏感）、test_403603_*、test_03（无法识别密钥日志仅 ALL/超管可见）、test_05（经 Nginx 伪造 XFF） | 通过（BUG-18 为部署安全缺陷） |
| AC-59 | test_02::test_ac59_*（22 种非法参数逐一指出字段；边界值通过；非 JSON/非对象；dataset_id 非法） | 通过 |
| AC-60 | test_02::test_ac60_*（文档禁用、分段禁用、处理中文档，向量/全文/混合） | 通过 |
| AC-61 | test_03::test_ac61_*（12 次调用/2 次失败统计；字段；密钥/知识库/结果/时间筛选；分页；他人不可见）、边界/90 天/180 天清理；E2E test_ac61_* | 通过 |
| AC-62 | test_02::test_429_*（第 N+1 次起 429、Retry-After、下一分钟恢复、超限写日志）、窗口键口径、test_04（40 并发限额 20 恰好 20 成功；两个 open 实例共享计数）、test_05（Retry-After 与到下一分钟秒数相差 ≤1） | 通过 |
| AC-64 | test_02::test_ac64_*（父块去重、得分=最高子块、子块降序、条数 ≤ Top K、与召回测试一致） | 通过 |
| AC-70 | test_02::test_ac70_*（移除/调岗/新分配 5 秒内生效）、test_04::test_owner_disabled_with_stale_cache、test_dynamic_all_scope_count_* | 通过 |
| AC-71 | test_01::test_ac71_*（失去 K2 后可检索数 2→1、名单、全失去 → no_dataset、恢复后 2）、test_02::test_ac71_* | 通过 |
| AC-72 | test_01::test_ac72_*、test_admin_disable_of_user_disabled_key_*、test_03::test_ac72_*；E2E test_ac72_*、test_keys_page_stale_403604_refreshes | 通过 |
| AC-73 | test_02::test_ac73_*（集团管理员、超管均 404601） | 通过 |

### 9.4 多维度结论

1. **功能**：密钥全生命周期（创建/明文一次/编辑/启停/重新生成旧值立即失效/删除）、两种检索范围、过期（含恰到期秒级）、IP 白名单（单 IP、CIDR、/32 规范化、0.0.0.0/0）、每分钟上限 1~600、成功响应字段与文档页一致、调用日志/统计/筛选/90 天/180 天清理、审计停用/删除/capabilities/include_unknown 均通过。10 个错误码：401601、403601、403602、403603、404601、400001、429601（含 Retry-After）、503001、500000 均逐一触发且带 `error_type` + `request_id`、message 与文档一致；**503601 仅在“模型被停用（kb 409303）”路径正确，上游模型调用失败（kb 503301）错误地返回 503001，见 BUG-17**。
2. **动态权限**：失去/恢复知识库权限、创建人停用/启用/删除、收回 `openapi:apikey:manage`（检索 403601，管理接口 403，恢复后自动可用）、admin_disabled 矩阵（403604/403605，旧 version 也返回 403604/403605 而非 409001，删除允许，管理员对 disabled 密钥可停用、重复停用幂等）均通过。
3. **越权**：他人密钥/日志按 ID 访问全部 404000（含管理员、集团管理员，个人接口）；无权限码 403；未登录/伪造 token（篡改、alg=none）401；公司管理员看不到、也无法停用/删除其他公司密钥；`include_unknown` 仅超管与 ALL 生效，其余静默忽略，调整角色范围/多角色并集后无需重新登录即时生效；管理员无编辑/启用/重新生成路由。
4. **data_scope**：ALL / COMPANY_AND_CHILD / COMPANY / DEPT_AND_CHILD / DEPT / SELF / CUSTOM 7 种范围在审计密钥列表和审计日志上的可见集合逐一断言通过，对范围外密钥的停用/删除均 404000。
5. **边界异常**：密钥畸形（空、短、无前缀、大写前缀、SQL、百分号、Basic 方案）、Bearer 大小写、`query` 1001/5000 字/2MB、top_k 越界、NUL（原始字节与 `\u0000` 转义）、64KB+ 请求体、重复/非法 `X-Request-Id`（重复使用时每次调用仍恰好一条日志）、kb 停止（503001，<5s，日志 service_unavailable，恢复后正常）、iam 停止且权限缓存为空（fail-closed，503001）、限流窗口边界、无效密钥按 IP 采样（同 IP 35 次仅落 20 条、另一 IP 独立、已识别密钥失败不采样）均通过。open 停止时 iam/kb 不受影响。
6. **并发/幂等**：同一密钥 40 并发限额 20 恰好 20 成功；双实例共享计数（限额 10，24 并发恰好 10 成功）；并发重新生成 1 成功其余 409001；并发编辑同 version 1 成功；并发同名创建 1 成功其余 409601；编辑与管理员停用并发无 500；启停同值幂等（version 不变、不写操作日志）；每个出口（成功 + 各错误 + NUL/坏 JSON/非法 dataset_id）恰好一条日志，405/404 仅补信封不写日志。
7. **端到端链路**：API 密钥 → open → kb 内部接口 → 结果，与 kb 召回测试同参数逐项一致（见 AC-56）。
8. **回归**：M1 257、M2 122 全部通过；iam 用户停用影响提示 `api_key_count` 正确（3，已删除不计）；`/internal/v1/stats/api-keys` 无/错 token 被拒；Nginx 不暴露 `/internal/`。
9. **UI**：我的 API 密钥、调用日志、密钥审计、API 文档四页面的加载中（延迟响应出现 Spin）/ 空 / 错误（“加载失败”+重试恢复）/ 无权限（403 页，菜单不含开放平台）四态；明文弹窗必须勾选才可关闭；admin_disabled 时仅保留“删除”“日志”并显示“不可修改”及悬停提示；审计页停用按钮仅对 admin_disabled 隐藏、无编辑/启用/重新生成；二次确认文案与“取消”按钮均为中文（BUG-15 在当前工作区已修复）；“含无法识别密钥的调用”开关仅集团管理员的“全部调用日志”抽屉出现，公司管理员与单密钥抽屉均不出现且单密钥抽屉不请求 capabilities；XSS 名称按文本渲染；文档页 10 个错误码、message、复制按钮。

### 9.5 缺陷列表

### BUG-17 [一般][后端] 向量/Rerank 模型调用失败时开放检索返回 503001 而非 503601（MODEL_UNAVAILABLE）
- 关联：F-18 规则 6（“模型服务不可用”）、tech-design-m3 3.3 第 10 步（kb 409303/503301 → 503601）、5.0
- 复现步骤：用密钥检索，把假 embedding 服务置为 500（`POST 127.0.0.1:19997/_ctl {"fail":true}`），查询使用未缓存的新文本，`search_method=vector`；或知识库配置 Rerank 模型后查询含 `RRFAIL` 触发 rerank 500。用例 `test_02_retrieve.py::test_503601_embedding_upstream_failure_maps_to_model_unavailable`、`test_503601_rerank_upstream_failure`。
- 期望结果：HTTP 503，code 503601，error_type MODEL_UNAVAILABLE，message“模型服务不可用”，日志 result=model_unavailable。
- 实际结果：HTTP 503，code 503001，error_type SERVICE_UNAVAILABLE，“依赖服务暂不可用，请稍后重试”，日志 result=service_unavailable。kb 直接调用时返回 503301（HTTP 503）。仅“模型被停用（kb 409303）”路径得到 503601。
- 证据：响应 `{"code":503001,...,"data":{"error_type":"SERVICE_UNAVAILABLE"...}}`；kb 直调 `{"code":503301,"message":"模型服务调用失败：向量模型返回错误（HTTP 500：boom）"}`。
- 可疑位置：`backend/libs/platform_common/platform_common/http_client.py` 第 52~53 行（`status_code >= 500` 时直接抛 503001，未解析 kb 响应体中的 503301）；open 的 `retrieve_service.py` 第 120 行附近的 503301 映射因此永远走不到（单测用替身直接抛 BizError(503301) 所以未发现）。
- 状态：**已关闭**（第 2 轮验证，见第 10 节）

### BUG-18 [一般][后端/部署] `TRUSTED_PROXIES` 不能单独阻止直连伪造 X-Forwarded-For：uvicorn 的 proxy_headers 默认信任 127.0.0.1
- 关联：AC-58（IP 白名单）、tech-design-m3 BE-29 安全基线（“TRUSTED_PROXIES 只填 Nginx 地址，否则可伪造 XFF”）
- 复现步骤：启动 open 时设置 `TRUSTED_PROXIES=["10.255.255.1/32"]`（不含回环），密钥白名单 `10.0.0.0/24`，从本机直连 8303 发送 `X-Forwarded-For: 10.0.0.5`。用例 `test_02_retrieve.py::test_xff_spoof_when_only_trusted_proxies_changed`。
- 期望结果：403603（对端不在可信代理内，XFF 被忽略）。
- 实际结果：200，调用日志 IP 记为 10.0.0.5。原因：`uvicorn.run(...)` 默认 `proxy_headers=True`、`forwarded_allow_ips=127.0.0.1`，uvicorn 先改写 `scope["client"]`，应用层 `get_client_ip` 看到的对端已是伪造值；仅当同时设置环境变量 `FORWARDED_ALLOW_IPS`（第三个实例验证：设置后 403603、日志 IP 为 127.0.0.1）才生效。
- 影响：生产上客户端必须经 Nginx（对端为 Nginx 容器地址，不是 127.0.0.1），实际风险低；但 `TRUSTED_PROXIES` 文档化的控制点并不完整，iam/kb/open 同样适用，本机开发/直连部署可绕过白名单。
- 可疑位置：各服务 `main.py` 的 `uvicorn.run("main:app", host=..., port=..., reload=False)`（建议由开发评估 `proxy_headers=False` 或与 `TRUSTED_PROXIES` 对齐）。
- 状态：**已关闭**（第 2 轮验证，见第 10 节）

本轮未发现前端缺陷（BUG-15 在当前工作区已显示“取消”；BUG-16 本轮未复测）。

### 9.6 关于 TRUSTED_PROXIES 本地默认值的结论（用户要求记录）

- 共享库默认 `TRUSTED_PROXIES = ["127.0.0.1/32", "::1/128"]`（`.env.example` 一致），即本机回环地址默认被视为可信代理。
- 直连服务（对端 127.0.0.1）时 XFF 被信任：取 XFF **最右侧**第一个非可信地址为客户端 IP。实测 `XFF: 10.0.0.5` → 视为 10.0.0.5（白名单可被绕过）；`6.6.6.6, 10.0.0.5` → 10.0.0.5；`10.0.0.5, 6.6.6.6` → 6.6.6.6（被拒）；非法值 → 回退到对端地址；IPv4 映射 IPv6 按 IPv4 比较。因此**本地默认配置下，同机直连可伪造 IP，属预期的开发默认值**，生产必须改为仅 Nginx 地址（BE-29 已要求），并见 BUG-18（还要处理 uvicorn 层）。
- 经 Nginx（前端镜像同款配置，`X-Forwarded-For $remote_addr` 覆盖）：伪造 `10.0.0.5`、`6.6.6.6, 10.0.0.5`、`::ffff:10.0.0.5`、`X-Real-IP`、`Forwarded` 均无法绕过白名单（403603），日志记录的 IP 为真实对端。

### 9.7 观察项与风险（非缺陷）

1. `Authorization: Bearer  <key>`（两个空格）被接受（宽松解析）；`bearer`/`BEARER` 大小写均被接受（符合 RFC 7235）。
2. `status=owner_unavailable` 的审计筛选为近似（user_ref 状态）；按优先级，创建人停用时已过期密钥也显示“创建人不可用”，与 3.2 状态优先级一致。
3. 编辑时已选但当前失去权限的知识库保留在指定集合内（契约解读②），恢复权限后自动生效，已验证。
4. 同一 `X-Request-Id` 24 小时内重复使用，日志 request_id 追加随机后缀（设计已知局限）。
5. 未覆盖：Redis 停止（与开发共用，不执行）；生产 compose 实机编排与镜像（BE-29 由开发验证，且本轮不碰 `kbp-prod`）；50 并发/10 万分段性能（开发已出数据，需真实模型与 SSD 复测）；浏览器仅 Chromium；E2E 未覆盖“编辑密钥表单中指定知识库多选”的交互细节（API 层已覆盖）。
6. 环境提示：测试收尾执行 `devctl --env test down` 时，kb-worker 输出的停止 PID（8006）与本轮启动的 worker 不一致，疑似遗留的旧 pid 文件；未影响其他项目进程的判断依据不足，请主会话留意是否有被误停的进程。

### 9.8 发布建议

- 无致命/严重缺陷。建议先修复 BUG-17（契约明确、实现简单、影响调用方对“可重试 / 模型故障”的区分），BUG-18 由主会话/架构师决策（确认生产仅经 Nginx 时可随后续迭代处理，但需把 `FORWARDED_ALLOW_IPS` 或 `proxy_headers` 纳入部署文档）。
- 修复后回归：重跑 `test_02_retrieve.py` 中 3 个失败用例，并抽查 `test_kb_error_mapping_with_mock`。

## 10. M2/M3 第 2 轮（回归）

- 日期：2026-11-13；被测构建：HEAD `8c06ac1` + 工作区未提交的修复（kb `model_service.py`/`config.py`、open `kb_client.py`、三服务 `main.py`、`devctl.py`、前端 `locale.ts`/`routes.tsx`（路由懒加载）/向导与重新分段默认长度等）。
- 依据：`docs/bugfixes/20261112-m2-qa-round1/bugfix.md`、`tech-design-m2.md` 第 13 节前端条目。
- 结论：**通过，建议发布。** BUG-14 ~ BUG-19 与 worker 配置校验全部验证关闭；回归套件无失败的真实缺陷；新增 1 个轻微缺陷（BUG-20）。

### 10.1 环境

- 服务：`devctl --env test up -d`（iam / kb / kb-worker / open，open 以 `OPEN_STATS_ENABLED=true`），库 `kbp_test`、Redis db1、桶 `kbp-test`；模型为本机假模型服务（19997），未读取 `backend/.env`；前端 `pnpm dev`（5174，路由懒加载后的开发服务器）。开发库 `kbp`、`kbp-prod`、其他项目容器未触碰。
- 结束时：`devctl --env test down` 停掉全部服务，并停止自己启动的假模型与 vite；另清理了 kb-worker 被 SIGKILL 测试遗留的孤儿进程池子进程（见 BUG-20，均为 cwd 在 `backend/services/kb` 且 ppid=1 的本项目进程）。
- 测试代码（不进 git）：新增 `backend/services/kb/tests/integration/test_09_round2.py`（BUG-14，5 例）、`frontend/e2e/test_m2m3_round2.py`（BUG-15/16，32 例）。

### 10.2 结果汇总

| 套件 | 用例数 | 通过 | 失败 | 说明 |
|---|---|---|---|---|
| M1 iam 集成（排除 `test_zz_redis_down`、`test_zz_perf`，同前） | 257 | 257 | 0 | |
| M2 kb 集成（原 122 + 新增 test_09 的 5 例） | 127 | 127 | 0 | 见下“用例/脚本调整” |
| M3 open 集成（含第 1 轮失败的 BUG-17×2、BUG-18×1） | 71 | 71 | 0 | 3 个失败用例转绿 |
| 跨服务套件 | — | — | — | 仓库没有独立的跨服务套件（`backend/tests_e2e_api/` 为空）；跨服务场景（iam 停止 fail-closed、kb-worker 停止/kill、副本同步、kb↔open 链路、双 open 实例限流）已包含在上面 kb test_07 与 open test_04/05 中 |
| 前端 E2E M2（`test_m2_kb.py`） | 20 | 20 | 0 | 含 `test_ui_confirm_dialog_buttons_are_chinese`、`test_ui_upload_wizard_default_rule_is_valid_with_default_model`（第 1 轮失败的两例转绿） |
| 前端 E2E M3（`test_m3_open.py`） | 14 | 14 | 0 | 首次执行 1 例因浏览器网络抖动失败，单独重跑通过（见“用例/脚本调整”） |
| 前端 E2E 本轮新增（`test_m2m3_round2.py`：BUG-15 确认框 25 + 内置文案 2、BUG-16 共 5，合计 32 个用例） | 32 | 32 | 0 | |
| 前端 E2E M1（`test_m1_*.py`，额外回归，因全局 locale 变更影响所有页面） | 38 | 38 | 0 | 2 例定位器随 locale 修正而调整（见下） |
| 合计 | 559 | 559 | 0 | 后端 455 / 前端 104 |

用例/脚本调整（均非产品缺陷）：

1. **BUG-19 带来的测试脚手架调整**：`kb/tests/integration/reset_env.sh` 原用 `devctl.py down kb-worker`（不带 `--env test`）。BUG-19 修复后 pid 文件按环境分离，不带 `--env` 的 `down` 只看 `.run/`，不再停止 test 环境的进程，导致 worker 未重启、副本未重新同步（首次执行 kb 套件 120 例 “kb 副本同步超时”）。改为 `--env test down` 后全绿。这正是修复后的预期行为（也证明环境隔离生效），但**请知悉：以前依赖“dev 与 test 共用 pid 目录”的习惯用法都要加 `--env test`**。
2. **locale 修正后的界面文案变化**：antd/ProForm 现在显示中文内置文案，旧用例中依赖英文回退的定位器失效：`test_ac28_ac29`（ModalForm 提交按钮由原先的“确认”变为 antd 标准的“确 定”）、M1 的两处 `get_by_text("暂无数据")`（图片 `<title>` 与描述文字同为“暂无数据”，严格模式匹配到 2 个元素）。已改定位器，界面行为本身正确。
3. `test_m3_open.py::test_audit_states_empty_error_403` 首次执行时第二个页面加载模块出现 `net::ERR_NETWORK_CHANGED`（trace 中 `routes.tsx`、`guards.tsx` 等模块请求 -1，本机网络接口变动所致），页面空白；单独重跑通过。判定为环境抖动，非缺陷。
4. 首次编写的 test_09 中 3 个用例因 `PUT /kb/models/{id}` 需要完整请求体（`base_url`/`model_name` 必填）而 400，已修正测试体后全部通过。

### 10.3 缺陷验证结论

| 缺陷 | 结论 | 验证方式与证据 |
|---|---|---|
| BUG-14 并发同名模型返回 500 | **已关闭** | 原用例 `test_08_extra::test_concurrent_model_create_same_name_no_500` 通过；新增 test_09：12 线程并发创建同名 ×3 轮（恰 1 个 200，其余全部 409/409304，无 500）；串行改名到已存在名称 → 409304，冲突后原记录可继续正常更新；8 个模型并发改成同一名称 ×3 轮（1 成功，其余 409304）；4 个并发创建 + 1 个改名抢同一名称（1 成功，其余 409304）；删除后名称释放可重建 |
| BUG-15 确认框取消按钮为英文 | **已关闭** | 在真实页面逐个点开并断言按钮文案无英文、取消按钮为“取 消”，共 25 个弹窗：文档删除（单个/批量）、分段删除、子块删除、父块保存确认、设置页“刷新并放弃修改”、分配移除、API 密钥（停用/重新生成/删除）、密钥审计（停用/删除）、模型（停用/删除）、组织（停用/删除）、用户（停用/删除/启用）、角色删除、批量转移、重新分段弹窗（普通 Modal 页脚：取 消 / 确认并重新处理）。三个“保存后将失去页面权限”自锁确认（用户分配角色、角色编辑、角色授权）因后端条件难以在界面上造出，用路由拦截返回 409124 触发，弹窗按钮均为“取 消 / 确认保存|确 定”（自锁判定本身已在 M1 覆盖）。内置文案：分页“第 1-20 条/总共 30 条”“10/20/50/100 条/页”，日期选择器占位“请选择”且面板为中文（年月、周一~周日），空状态“暂无数据”，下拉无结果“暂无数据”，页面主体无 Cancel/OK/No data/Loading。根因（CJS locale 经 Vite 预构建被包成 `{default}`）已由 `src/locale.ts` 修复，所有页面一致生效 |
| BUG-16 向导默认分段长度 | **已关闭** | 默认模型（`max_input_tokens`=512）：向导默认最大长度 512，无校验报错，预览与“保存并处理”可用；模型上限 8192 → 默认 1024，上限 300 → 默认 300；父子分段：子块默认 300（上限 300）、父块仍为 1024，可预览；用户手改为 400 后，即便模型选项接口被人为延迟 2.5 秒后才返回，也不被覆盖，返回上一步再进入仍为 400；“恢复默认”回到 min(1024, 上限)；重新分段弹窗：已有规则回显（200），手改为 250 不被覆盖，“恢复默认”得到 300（上限 300） |
| BUG-17 503301 → 503601 | **已关闭** | open 套件 `test_02_retrieve.py` 中 `test_503601_embedding_upstream_failure_maps_to_model_unavailable`、`test_503601_rerank_upstream_failure` 转绿；`test_kb_error_mapping_with_mock`（kb 其他 5xx/500000/超时仍为 503001）通过 |
| BUG-18 伪造 X-Forwarded-For | **已关闭** | open 套件 `test_xff_spoof_when_only_trusted_proxies_changed` 转绿（`TRUSTED_PROXIES` 不含回环时，直连伪造 XFF 返回 403603，调用日志 IP 为 127.0.0.1）。另在 iam 上实测：两个临时实例（18301：`TRUSTED_PROXIES=["10.255.255.1/32"]`；18302：默认值含回环），同样携带 `X-Forwarded-For: 10.0.0.77` 登录，登录日志 IP 分别为 `127.0.0.1`（不采信）与 `10.0.0.77`（回环可信，开发默认值，符合第 9.6 节记录）。三服务 `main.py` 均为 `proxy_headers=False`。临时实例已停止 |
| BUG-19 devctl 误杀与 pid 隔离 | **已关闭** | 只用自己启动的 `sleep` 当“外部进程”：①把 `sleep` 的 PID 写入 `.run/test/iam.pid` 与 `.run/iam.pid`，分别执行 `--env test down iam`、`down iam`：提示“不是本项目的该服务进程（陈旧 pid 文件），已删除，未终止进程”，`sleep` 均存活，pid 文件被清理；②cwd 在 `backend/services/kb` 但 cmdline 无 `worker.py` 的 `sleep` 写入 `kb-worker.pid` → 未终止；③cwd 在 `backend/services/iam` 但 cmdline 无 `main.py` → 未终止；④pid 文件内容为非数字/已死亡 PID → 提示“未运行”并清理；⑤真实 `kb` 的 PID 写进 `kb-worker.pid` → 身份校验失败，kb 存活（healthz 200）；⑥环境分离：`--env test up -d iam kb` 后 pid 文件仅在 `.run/test/`，`.run/` 下无；不带 `--env` 的 `down iam` 与 `status` 看不到、也不影响 test 实例，`--env test status` 正确显示运行中。第 9.7 节第 6 条“down 停掉的 PID 与本轮启动的不一致”的风险因此消除 |
| worker 配置校验 | **已关闭** | 直接启动 `python worker.py`（环境变量 `TASK_CLAIM_IDLE_SECONDS` / `DOC_LOCK_TTL_SECONDS`）：60/90 与 90/90 均退出码 1，报 `RuntimeError: TASK_CLAIM_IDLE_SECONDS（n）必须大于 DOC_LOCK_TTL_SECONDS（90）…`；91/90、600/90（默认）正常启动运行（用 `timeout` 终止） |

### 10.4 新缺陷

### BUG-20 [轻微][后端] kb-worker 被 SIGKILL 后，文档处理进程池的子进程成为孤儿并长期驻留
- 关联：CLAUDE.md 4.2（CPU 密集操作放进程池/worker）、AC-40/41（worker 崩溃后接管恢复）
- 复现步骤：`devctl --env test up -d kb-worker`，让 worker 处理若干文档（使进程池拉起），对 worker 主进程执行 `kill -9`（kb 套件 `test_07_faults_regression.py::test_zz_worker_killed_mid_processing_recovers` 即如此），再 `ps` 查看。
- 期望结果：主进程被强杀后，其 `multiprocessing` 子进程（resource_tracker 与 spawn 出来的池工作进程）随之退出，或至少不无限期驻留。
- 实际结果：每次强杀遗留 2 个 `python -c "from multiprocessing…"` 进程（ppid=1，cwd=`backend/services/kb`，约 120 MB RSS），本轮开始前就有 4 对（来自前几轮测试，时间 11-12 22:40、22:44、23:12、11-13 00:15），本轮又新增 1 对（00:47）。SIGTERM 可正常终止。
- 影响：容器部署下容器退出会整体回收，无实际影响；本机裸进程/systemd 非 cgroup 回收场景会持续累积内存。故定为轻微，不阻塞发布。
- 证据：`ps -o pid,ppid,lstart,cwd` 见上述 10 个进程（已手工终止）。
- 可疑位置：`backend/services/kb/worker.py` 与文档处理使用的进程池创建位置（`ProcessPoolExecutor` 的 spawn 上下文）；父进程异常退出时子进程未随之退出。
- 状态：未修复

### 10.5 观察项与风险（非缺陷）

1. **运维习惯变化**：devctl 的 pid 文件按环境分离后，升级前用 `--env test` 启动、pid 在 `.run/` 下的进程需手工处理（开发说明已写明；本机已无）。
2. 仓库根目录有两个未跟踪文件 `fake.pid`、`fake_r.pid`（前几轮遗留的假模型 pid 记录，内容为 PID），不是本轮产生，未处理；本轮创建的临时文件（误写入的 `sleep` 文件）已删除。
3. 未覆盖（沿用第 8.6/9.7 节）：Redis 容器停止、解析炸弹/大文件耗时、10 万分段性能、真实模型网关冒烟（由主会话完成）、生产 compose 实机编排；E2E 仅 Chromium；三个自锁确认框使用接口拦截模拟 409124；Vite 开发服务器与生产构建的懒加载行为可能有差异，建议发布前对 `pnpm build` 产物做一次人工页面抽查（路由切换时的加载占位、首屏）。
4. 路由懒加载后未观察到功能回归：M1/M2/M3 全部页面 E2E 通过，加载占位（Spin）不影响断言（用例均以 `expect(...).to_be_visible(timeout)` 等待）。

### 10.6 发布建议

- **建议发布。** 6 项修复全部关闭，回归全绿，无致命/严重/一般缺陷遗留；BUG-20 为轻微，可随后续迭代处理。
- 发布前仍请主会话完成：①真实 Embedding/Rerank 网关冒烟（含 `.xls`、HNSW 索引创建）；②对前端生产构建做一次页面抽查（懒加载）；③生产 `TRUSTED_PROXIES` 仅填 Nginx 地址（BE-29 基线）。

## 11. 真实模型冒烟与 BUG-20 验证（主会话，2026-11-13）

- 环境：开发库 `kbp`（devctl 开发环境），模型网关为用户提供的真实网关（地址与密钥取自 `backend/.env`，未写入任何文档/日志；事后核对 `logs/*.log` 中真实密钥出现 0 次）。
- 结果（全部通过）：

| 步骤 | 结果 |
|---|---|
| bge-m3（Embedding，1024 维）测试连接 / 创建并设为默认 | 通过 |
| bge-reranker-v2-m3（Rerank）测试连接 / 创建并设为默认 | 通过 |
| kb-worker 运行时自动创建 HNSW 索引 | 通过（`ix_seg_hnsw_m32`、`ix_child_hnsw_m32`） |
| 上传真实 `.xls`（BIFF8，xlwt 生成，2 个工作表）、`.xlsx`、`.docx`、`.md` → 预览 → 提交 | 通过，4 个文档均为"可用" |
| 召回测试：向量 + Rerank / 全文 / 混合（rerank 模式）"年假有几天" | 三种方式 Top1 均为 `假期制度.xls` 年假行（向量 0.924） |
| API 密钥开放检索"差旅住宿标准是多少" | 通过，Top1 为 `.xls` 第二个工作表"差旅住宿 600 元"行 |
| 冒烟 API 密钥删除、admin 恢复 `Admin12345` 且 `must_change_password=true` | 通过 |

- 保留数据（供验收）：模型 `bge-m3`、`bge-reranker-v2-m3`；知识库"演示知识库"（4 个文档）。
- BUG-20：开发已修复（进程池子进程守护线程检测父进程变化后退出，见 `docs/bugfixes/20261112-m2-qa-round1/bugfix.md`），kb 单测 286 通过，子进程在父进程被 SIGKILL 后约 2.7 秒内退出 —— **已关闭**。
- 最终结论：M1/M2/M3 **通过，可交付验收**；遗留事项见 `prd.md`/各 tech-design 第 13 节与 `deploy/README.md` 上线检查清单（SSD 环境性能复测、生产 PG 参数按内存调整、`TRUSTED_PROXIES` 仅填 Nginx）。
