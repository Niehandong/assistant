# M2 QA 第一轮缺陷修复（后端 kb）

## BUG-14 并发创建同名模型返回 500（应为 409304）

- 现象：并发 POST `/api/v1/kb/models` 同名，部分请求返回 500。
- 根因：`model_service.create_model` 先 `name_exists` 预检（并发下都通过），随后 `session.flush()` 触发 INSERT，唯一索引 `uq_ai_model_name` 冲突抛出的 `IntegrityError` 发生在 `_commit` 的 try 之外，未映射成业务码。
- 修改点（`backend/services/kb/app/services/model_service.py`）：
  - 新增 `_flush()`，捕获 `IntegrityError` 并回滚后经 `_raise_mapped` 映射（`uq_ai_model_name` → 409304，`uq_ai_model_default` → 409001）；`_commit` 复用同一映射。
  - `create_model` 的 flush 改用 `_flush`。
  - `update_model` 在 `clear_default`（其查询会触发 autoflush，可能让改名冲突在 try 外抛出）之前显式 `_flush`，消除同类隐患。
- 同类排查：dataset（创建 `_flush_commit` / 更新 / 转移 `_commit`）、assignment `_commit`、upload（文档 hash flush）均已捕获并映射，无需修改；其余唯一索引仅上述表。
- 测试：`tests/unit/test_models_api.py` 新增并发创建同名、并发改成同名两例（修复前并发创建用例失败）。QA 集成用例 `test_08_extra.py::test_concurrent_model_create_same_name_no_500` 转绿。
- 影响范围：仅 kb 模型创建/更新错误映射；正常路径不变。

## worker 接管配置校验

- 现象：`TASK_CLAIM_IDLE_SECONDS <= DOC_LOCK_TTL_SECONDS` 时，接管任务时旧 worker 的文档锁尚未过期，接管方把任务当重复投递丢弃，文档卡在“索引中”。
- 根因：两个配置项缺少相互约束。
- 修改点：`app/core/config.py::Settings.validate_for_runtime` 校验 `TASK_CLAIM_IDLE_SECONDS > DOC_LOCK_TTL_SECONDS`，不满足抛 `RuntimeError`（worker 启动时调用，拒绝启动并给出明确提示）；`.env.example` 注明约束；`tests/unit/test_config.py` 新增用例。
- 影响范围：仅配置不合规时 worker/服务启动失败；默认值（600 > 90）不受影响。

---

## M3 第 1 轮（QA 报告第 9 节）

### BUG-17 开放检索把模型上游失败报成 503001

- 现象：kb 的 Embedding/Rerank 上游调用失败时返回 HTTP 503 / code 503301，open 开放检索却返回 503001，应为 503601 MODEL_UNAVAILABLE。
- 根因：共享库 `InternalClient._request` 遇到 5xx 一律抛 503001，不解析响应体，`retrieve_service._map_kb_error` 的 503301 分支永远走不到。
- 修改点：不改共享库（避免影响其他调用方）。在 `backend/services/open/app/services/kb_client.py` 新增 `_RetrieveInternalClient`（仅 retrieve 通道使用），5xx 时解析统一响应体，业务码在白名单 `{503301}` 内则原样抛出，其余 5xx（含 kb 500000）、非统一格式、连接失败/超时仍为 503001。新增单测 `backend/services/open/tests/unit/test_kb_client_http.py`（真实 uvicorn 线程模拟 kb，修复前 503301 用例红、修复后绿）。
- 影响范围：仅 open 的检索转发错误映射；`accessible-datasets` / `brief` 通道与共享库行为不变。

### BUG-18 直连服务时 X-Forwarded-For 可被伪造

- 现象：uvicorn 的 `proxy_headers` 默认信任 127.0.0.1 并先用 XFF 改写 `request.client`，应用层 `TRUSTED_PROXIES` 失效；即便配置不含回环，直连仍可伪造 XFF 绕过 IP 白名单。
- 根因：两层信任列表并存，uvicorn 层默认值更宽。
- 修改点：iam / kb / open 的 `main.py` 中 `uvicorn.run(..., proxy_headers=False)`；客户端 IP 只由 `platform_common.client_ip.get_client_ip` 按 `TRUSTED_PROXIES` 解析（该函数基于 `request.client.host`，即真实 TCP 对端）。生产镜像 `CMD ["python", "main.py"]`、compose 中无其他 uvicorn 命令行，无需改动；`deploy/README.md` 安全基线补充说明。
- 影响范围：开发默认值（`TRUSTED_PROXIES` 含回环）下，经 vite 代理/本机 nginx 访问时对端为 127.0.0.1，仍被应用层信任并解析 XFF，行为不变；直连且对端不在可信列表时不再采信 XFF。

### BUG-19 devctl 停止进程时可能误杀

- 现象：`down` 仅校验 pid 文件中的 PID 存活；PID 回绕后可能指向其他项目的进程。
- 根因：缺少身份校验；另外 dev 与 `--env test` 共用 `.run/<服务>.pid`，一套环境会误停/误判另一套。
- 修改点：`backend/scripts/devctl.py`：新增 `is_our_process`（`/proc/<pid>/cwd` 必须位于 `backend/services/<服务目录>` 下且 cmdline 含该服务入口 `main.py`/`worker.py`），`read_pid` 校验失败视为陈旧 pid 文件，删除文件、打印提示、不终止进程；pid 文件按环境区分（dev：`.run/`，test：`.run/test/`），`up/down/status` 均传入环境。单测 `backend/scripts/tests/test_devctl.py`（不进 git）。
- 影响范围：仅 devctl。升级后遗留的 dev pid 文件位置不变；此前用 `--env test` 启动、pid 在 `.run/` 下的进程需手工处理（本机当前无）。

### BUG-20 kb-worker 被 SIGKILL 后进程池子进程成为孤儿

- 现象：`kill -9` kb-worker 主进程后，`ProcessPoolExecutor`（spawn）的工作进程与 resource_tracker 变成 ppid=1 的孤儿，每次约 2 个进程、120MB，长期驻留；SIGTERM 正常停止无此问题。
- 根因：池子进程阻塞在跨进程任务队列上，各子进程共享队列管道，父进程死后读端不会 EOF，没有任何机制让子进程感知父进程已死；resource_tracker 又被这些子进程持有的管道保活。
- 修改点：
  - 新增 `backend/services/kb/app/parsers/orphan_guard.py`：子进程 initializer 起守护线程，每 2 秒检查 `os.getppid()` 是否等于创建池时记录的父 PID，不等则 `os._exit(1)`；启动时父进程已死也直接退出。
  - `backend/services/kb/app/parsers/registry.py` 的 `get_pool` 传入 `initializer=init_worker_process, initargs=(os.getpid(),)`。
  - 选型：只用轮询线程，不用 `prctl(PR_SET_PDEATHSIG)`。PDEATHSIG 绑定的是“创建子进程的线程”，而 `ProcessPoolExecutor` 在其管理线程中按需拉起子进程，该线程退出会误杀仍在工作的子进程；且仅 Linux 有效。轮询跨平台、无副作用。子进程退出后 resource_tracker 因管道全部关闭随之退出。
- 影响范围：仅 kb 文档处理进程池（`get_pool`）；SIGTERM 流程（`shutdown_pool`）不变，主进程存活时守护线程不触发。
- 验证：
  - 单测 `tests/unit/test_orphan_guard.py`：子进程跑真实 `get_pool`，拉起池工作进程后 SIGKILL 父进程，断言工作进程在 10 秒内消失。还原 registry 改动时该测试红（孤儿残留），修复后绿（约 2.7 秒）。
  - 手工：`devctl --env test up -d kb-worker` 与 `down kb-worker`（SIGTERM）正常停止，无残留进程。池为懒创建，未经文档处理不会拉起，故真实 worker 的 kill -9 场景由上述单测以同一代码路径覆盖，未另造文档。
