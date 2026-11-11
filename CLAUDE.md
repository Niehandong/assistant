# 项目协作规范（所有智能体共享）

> 本文件是整个项目的"宪法"。主会话和所有子智能体在动手前都必须遵守这里的约定。
> 规范需要调整时，先改本文件，再改代码。

## 0. 语言约定

- 与用户交流、文档、代码注释、提交信息描述：**简体中文**
- 标识符（变量、函数、类、表名、字段名、路由、权限码）：**英文**
- 日志原文、命令、报错保持原样

## 1. 仓库结构（monorepo）

```
.
├── CLAUDE.md                 # 本文件
├── .venv/                    # 全项目唯一的 Python 虚拟环境（不进 git）
├── docker-compose.yml        # 本地中间件：PostgreSQL + Redis
├── frontend/                 # React + Ant Design
├── backend/                  # Python + FastAPI
├── docs/
│   ├── templates/            # PRD / 技术方案 / 测试报告 / bug 记录模板
│   ├── features/<YYYYMMDD-简称>/
│   │   ├── input/            # 原始需求描述、截图等
│   │   ├── prd.md            # 产品经理产出
│   │   ├── tech-design.md    # 架构师产出
│   │   └── test-report.md    # 测试产出
│   └── bugfixes/<YYYYMMDD-简称>/
│       ├── bugfix.md         # 现象、根因、修改点、影响范围
│       ├── tech-design.md    # 仅跨端/改契约/改表结构/改权限模型时才有
│       └── test-report.md
└── .claude/
    ├── agents/               # 5 个子智能体
    └── commands/             # /feature、/bugfix 流程命令
```

## 2. 智能体团队与职责边界

| 智能体 | 只允许写入 | 不允许做 |
|---|---|---|
| `product-manager` | `docs/` | 写技术方案（表结构、接口、选型）、改代码 |
| `architect` | `docs/` | 改业务代码、改测试代码 |
| `frontend-dev` | `frontend/`、需求目录下的实现说明 | 改后端、私自改接口契约 |
| `backend-dev` | `backend/`、`docker-compose.yml`、需求目录下的实现说明 | 改前端、私自改接口契约 |
| `qa-tester` | `backend/tests/integration/`、`frontend/e2e/`、`test-report.md` | 改业务代码（只报缺陷） |

通用规则：
- **子智能体不执行任何 git 写操作**（commit / push / merge / reset / checkout 分支等），git 由主会话负责。
- 子智能体之间不能直接通信，一律通过 `docs/` 下的文档交接。
- 接口契约以 `tech-design.md` 为准。开发发现契约不合理时，**不得私改**，在返回结果中提出"契约变更申请"，由主会话交给架构师更新文档后再继续。
- 引用需求统一用编号：功能点 `F-xx`、验收标准 `AC-xx`、后端任务 `BE-xx`、前端任务 `FE-xx`、缺陷 `BUG-xx`。

## 3. 技术栈基线

新增依赖或中间件必须在 `tech-design.md` 中提出并说明理由，不得在开发中随手引入。

### 前端
- TypeScript + React 18 + Vite，包管理 **pnpm**
- Ant Design 5 + `@ant-design/icons` + `@ant-design/pro-components`
- React Router 6；TanStack Query（服务端数据）+ axios（统一实例）；Zustand（仅全局 UI/用户状态）
- dayjs；`lodash-es` 按需引入；不引入 Tailwind
- 质量：ESLint + Prettier，`tsc --noEmit`
- 测试：Vitest + React Testing Library（单测），Playwright（E2E）
- 只做简体中文，不做国际化

### 后端
- Python 3.12 + FastAPI + Pydantic v2 + pydantic-settings
- SQLAlchemy 2.0（async）+ asyncpg + Alembic
- **不使用 uv / poetry**。环境：仓库根目录 `python3.12 -m venv .venv`，所有后端共用这一个环境；依赖用 `pip` 管理，`backend/requirements.txt`、`backend/requirements-dev.txt`，**版本固定**
- 质量：Ruff（lint + format）+ mypy
- 测试：pytest + pytest-asyncio + httpx（AsyncClient）

### 中间件与部署
- 本地：`docker compose` 只起中间件 —— **PostgreSQL 16 + Redis 7**
- 前后端本地开发**不进容器**
- 生产：Docker 部署（Dockerfile 由"项目初始化"需求规划）

## 4. 后端规范

### 4.1 启动与配置
- `backend/main.py` 创建 app，并包含：
  ```python
  if __name__ == "__main__":
      uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
  ```
- 启动方式：`cd backend && ../.venv/bin/python main.py`。**不开热加载**，修改后端代码后必须**重启进程**再验证。
- 配置集中在 `backend/app/core/config.py`（pydantic-settings），**所有配置项带本地开发默认值**（默认连本地 compose 的 Postgres/Redis），可被 `backend/.env` 或环境变量覆盖。
- `backend/.env` 不进 git；`backend/.env.example` 进 git，新增配置项时必须同步。

### 4.2 分层（单向依赖：api → service → repository → model）
```
backend/
  main.py
  requirements.txt / requirements-dev.txt
  alembic.ini / alembic/
  app/
    core/          # config、security(JWT/密码哈希)、database、redis、logging、exceptions
    deps/          # get_db、get_current_user、require_perm、data_scope
    models/        # SQLAlchemy ORM（按模块分文件）
    schemas/       # Pydantic 请求/响应
    repositories/  # 所有查询；数据权限过滤在此统一注入
    services/      # 业务逻辑、事务边界
    api/v1/        # 路由：只收参、声明权限、调 service
  tests/           # 不进 git：unit/（开发写）、integration/（测试写）
```
- 路由层不写业务、不直接操作 session。
- 全异步：`async def` + asyncpg，请求链路中不做阻塞 IO。

### 4.3 接口约定
- 前缀 `/api/v1`，RESTful 资源命名，复数名词。
- 统一响应：`{"code": 0, "message": "ok", "data": ...}`；分页 `data = {"items": [], "total": n, "page": 1, "page_size": 20}`。
- 业务错误抛 `BizError(code, message)`，由全局异常处理器转换；不向前端暴露堆栈。
- **每个接口必须声明权限**：`dependencies=[Depends(require_perm("system:user:create"))]`；公开接口必须显式标注为 public 并在技术方案中说明。
- 以 FastAPI 生成的 OpenAPI 为契约事实来源，前端类型由 `openapi-typescript` 生成。

### 4.4 数据库约定
- 主键 `id BIGINT` 自增。
- 所有表含：`created_at`、`updated_at`、`created_by`、`updated_by`、`is_deleted`（逻辑删除）。
- 表结构变更**必须**走 Alembic 迁移，禁止 `metadata.create_all`。
- 受数据权限控制的业务表**必须**含 `company_id`、`dept_id`、`created_by`。
- 登录、授权变更、删除等关键操作写操作日志表。

## 5. 认证与权限模型（RBAC + 组织 + 数据权限）

### 5.1 认证
- JWT access token（默认 30 分钟）+ refresh token（存库/Redis，可吊销）。
- 密码哈希使用 bcrypt / argon2；登录失败次数限制放 Redis。

### 5.2 组织
- 统一组织树 `sys_org`：`parent_id` + `ancestors`（祖级路径字符串，如 `0,1,5`）+ `org_type`：
  - `group` 集团 / `company` 公司（可多级子公司）/ `dept` 部门
- **一人一主组织**：用户归属一个 `dept` 或 `company` 节点；所属公司 = 向上最近的 `company` 节点。
- 跨公司看数据的需求，通过"自定义组织"数据范围的角色解决。

### 5.3 RBAC
- 用户 ↔ 角色 ↔ 权限，均为多对多。
- `sys_user_role` 预留 `org_id`（角色在哪个组织下授予），为将来"一人多组织任职"做准备。
- 权限类型：`menu`（菜单/路由）、`button`（页面操作）、`api`（接口）。菜单树由权限表驱动并下发前端。
- 权限码格式：`模块:资源:操作`，例如 `system:user:create`、`order:list:export`。
- 角色分为**集团级**（全集团可分配）和**公司级**（归属某公司，由该公司管理员维护）。
- 内置 `super_admin` 角色，跳过所有权限与数据范围校验。
- **子公司管理员**只能管理本公司（含下属）的用户、角色、组织，不能授予超出自身拥有的权限。

### 5.4 数据权限
角色字段 `data_scope`：

| 值 | 含义 |
|---|---|
| `ALL` | 全部数据 |
| `COMPANY_AND_CHILD` | 本公司及下属公司 |
| `COMPANY` | 本公司 |
| `DEPT_AND_CHILD` | 本部门及以下 |
| `DEPT` | 本部门 |
| `SELF` | 仅本人（`created_by` = 当前用户） |
| `CUSTOM` | 自定义组织（`sys_role_org` 关联） |

- 用户有多个角色时**取并集**。
- 实现：`repositories` 层通过统一函数生成 SQLAlchemy `where` 表达式注入查询，**禁止拼接 SQL 字符串**。
- 技术方案中必须标明每张新表"是否受数据权限控制"。

### 5.5 前端权限
- 登录后拉取当前用户信息、菜单树、权限码列表，存入 Zustand。
- 路由守卫：未登录跳登录页，无权限显示 403。
- 按钮权限只能用 `<Access code="...">` 或 `usePermission()`，**禁止**按角色名硬编码判断。
- 前端隐藏只是体验，**安全边界在后端**。

## 6. 前端规范

```
frontend/src/
  api/          # axios 实例、拦截器（注入 token、401 自动刷新、统一错误提示）
  services/     # 按模块的接口函数与类型（类型由 openapi-typescript 生成）
  pages/<模块>/ # 一个页面一个目录：index.tsx、components/、hooks
  components/   # 跨页面通用组件
  layouts/      # ProLayout 主布局
  access/       # usePermission、<Access>
  router/       # 路由表与守卫
  stores/       # Zustand
  utils/
```
- 列表页统一 ProTable；表单统一 ProForm / ModalForm / DrawerForm，不手写分页与查询表单。
- 样式：AntD `ConfigProvider` 主题 token + 少量 CSS Modules。
- 每个页面必须处理：加载中、空数据、错误、无权限四种状态。

## 7. 测试规范

| 类型 | 负责人 | 位置 | 工具 |
|---|---|---|---|
| 后端单元/接口测试 | backend-dev | `backend/tests/unit/` | pytest |
| 前端单测 | frontend-dev | `frontend/src/**/*.test.ts(x)` | Vitest |
| 后端集成测试（按 AC） | qa-tester | `backend/tests/integration/` | pytest + httpx，真实 Postgres/Redis |
| E2E | qa-tester | `frontend/e2e/` | Playwright |

- **测试代码和运行产物不进 git**；测试报告 `test-report.md` 进 git。
- 测试库使用独立数据库（如 `app_test`），不得污染开发库。

## 8. Git 规范

- 子智能体不做 git 写操作。
- 分支：`feature/<YYYYMMDD-简称>`、`fix/<YYYYMMDD-简称>`，由主会话在流程开始时从 `main` 创建。
- 测试通过后，主会话汇总改动给用户确认，**用户确认后才提交**。
- 提交信息：Conventional Commits + 中文描述，例如 `feat(system): 新增组织管理`、`fix(auth): 修复刷新令牌过期未跳转登录`。
- 不自动合并到 `main`，不自动推送远程。

## 9. 常用命令

```bash
# 中间件
docker compose up -d

# 后端环境（首次）
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# 后端
cd backend && ../.venv/bin/alembic upgrade head
cd backend && ../.venv/bin/python main.py
cd backend && ../.venv/bin/ruff check . && ../.venv/bin/mypy app
cd backend && ../.venv/bin/pytest

# 前端
cd frontend && pnpm install && pnpm dev
cd frontend && pnpm tsc --noEmit && pnpm lint && pnpm build
cd frontend && pnpm test
cd frontend && pnpm exec playwright test
```
（以上命令在"项目初始化"需求完成后生效。）
