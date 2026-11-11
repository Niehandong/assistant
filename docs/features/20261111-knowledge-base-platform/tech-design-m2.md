# M2 知识库 技术方案（kb 服务 + kb-worker）

- 关联：`./prd.md`（v0.2）F-07 ~ F-16、F-20，AC-22 ~ AC-51、AC-63 ~ AC-69；总体方案 `./tech-design.md`；共享库契约 `./tech-design-m1.md` 3.2
- 状态：草稿
- 本分册覆盖：BE-11 ~ BE-23、FE-09 ~ FE-17
- 前置：M1 的 BE-01 ~ BE-06 完成（共享库、iam 认证与权限上下文、事件发布）

## 1. 范围

| 功能点 | 覆盖 | 说明 |
|---|---|---|
| F-07 | ✅ | 模型配置、测试连接、凭据加密 |
| F-08 | ✅ | 我的知识库（ACL 查询 + 统计冗余） |
| F-09 | ✅ | 创建/编辑/删除 |
| F-10 | ✅ | 分配、可分配范围、动态成员 |
| F-11 | ✅ | 上传、校验、预览、提交 |
| F-12 | ✅ | worker 流水线、进度、重试、超时巡检 |
| F-13 | ✅ | 文档列表、启停、重新分段、下载、删除 |
| F-14 | ✅ | 分段编辑（异步重建索引）、父子分段 |
| F-15 | ✅ | 检索设置 |
| F-16 | ✅ | 召回测试、测试记录 |
| F-20 | ✅ | 管理视图、审计查看、转移/批量转移、所有者自行转移 |

---

## 2. kb 服务内部结构

```
backend/services/kb/
  main.py                    # API 进程 :8302
  worker.py                  # 处理进程：任务消费 + 定时任务 + iam 事件同步
  .env.example  alembic.ini  alembic/versions/0001_init_kb.py
  app/
    core/config.py  core/constants.py
    assets/cl100k_base.tiktoken            # tiktoken 编码文件随代码提交，运行时不联网
    models/  ai_model.py dataset.py assignment.py upload_file.py document.py segment.py child_chunk.py retrieval_record.py ref.py
    schemas/ model.py dataset.py assignment.py upload.py document.py segment.py retrieval.py admin.py internal.py process_rule.py
    repositories/ model_repo.py dataset_repo.py dataset_acl.py assignment_repo.py document_repo.py segment_repo.py ref_repo.py record_repo.py
    services/ model_service.py dataset_service.py assignment_service.py upload_service.py document_service.py
              segment_service.py retrieval_service.py admin_service.py transfer_service.py stats_service.py internal_service.py
    engine/   vector_store.py(VectorStore 抽象 + PgVectorStore)  fulltext.py(jieba + tsquery)  retriever.py  rerank.py
    parsers/  base.py txt.py markdown.py pdf.py docx.py excel.py csv.py html.py pptx.py registry.py
    splitters/ preprocess.py tokenizer.py general.py parent_child.py
    storage/  s3.py
    model_clients/ embedding.py rerank.py errors.py
    worker/   main_loop.py tasks_document.py tasks_segment.py sweeper.py ref_sync.py hit_flush.py upload_cleanup.py
    api/v1/   models.py datasets.py assignments.py uploads.py documents.py segments.py retrieval.py admin.py
    api/internal/ retrieval.py access.py stats.py
  tests/unit/
```

配置（`app/core/config.py`，均有本地默认值）：

| 配置项 | 默认 | 说明 |
|---|---|---|
| PORT | 8302 | |
| S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET / S3_REGION | `http://127.0.0.1:19000` / `minioadmin` / `minioadmin` / `kbp-files` / `us-east-1` | |
| MODEL_SECRET_KEY | 固定的开发用 Fernet key | 模型凭据加密；生产必须覆盖 |
| UPLOAD_MAX_BYTES | 15728640 | 15 MB |
| DATASET_MAX_DOCUMENTS | 10000 | |
| UPLOAD_FILE_TTL_HOURS | 24 | 未提交的上传文件过期清理 |
| PARSE_PROCESS_WORKERS | 2 | API 进程内解析/校验用进程池大小 |
| WORKER_CONCURRENCY | 4 | worker 同时处理的任务数 |
| EMBED_BATCH_SIZE | 16 | |
| MODEL_HTTP_TIMEOUT_SECONDS | 30 | |
| PROCESS_TIMEOUT_MINUTES | 30 | 处理超时判定 |
| REF_RECONCILE_INTERVAL_SECONDS | 600 | 只读副本对账 |
| HIT_FLUSH_INTERVAL_SECONDS | 60 | |
| QUERY_EMBED_CACHE_SECONDS | 600 | 查询向量缓存 |
| RETRIEVAL_CANDIDATE_MAX | 100 | 候选上限 |
| JIEBA_USER_DICT | 空 | 自定义词典路径 |

新增依赖（追加到 `backend/requirements.txt`，固定版本）：`pgvector`、`jieba`（`aioboto3` 已在 M1 BE-01 加入）、`tiktoken`、`pypdf`、`python-docx`、`openpyxl`、`xlrd`、`python-pptx`、`beautifulsoup4`、`lxml`、`charset-normalizer`。

---

## 3. 关键设计

### 3.1 资源 ACL（知识库日常访问）

`dataset_acl.py` 提供（全部基于 AuthContext，不依赖只读副本）：

```python
def accessible_dataset_ids_subquery(ctx: AuthContext) -> Select   # 所有者 + 匹配分配
async def get_permission_level(session, ctx, dataset_id) -> Literal["owner","edit","read"] | None
async def require_dataset(session, ctx, dataset_id, need: Literal["read","edit","owner"]) -> Dataset
    # 不可访问 → 404000；可访问但级别不足 → 403311
```

分配匹配条件（`dataset_assignment` 未删除）：

```
(target_type='user'    AND target_id = :user_id)
OR (target_type='dept'    AND ((NOT include_children AND target_id = :org_id)     OR (include_children AND target_id = ANY(:org_path))))
OR (target_type='company' AND ((NOT include_children AND target_id = :company_id) OR (include_children AND target_id = ANY(:org_path))))
```

- 多途径取最高级别：owner > edit > read。
- 超级管理员**不**因身份获得日常访问（PRD 7.2、AC-73）；但 PRD F-09 规则 7 允许超管删除任意知识库 → 仅 `DELETE /datasets/{id}` 对超管放行（并需在管理视图中操作，见 3.8）。
- 功能权限码与 ACL 同时校验：例如上传需 `kb:document:upload` + ACL≥edit。

### 3.2 统计冗余

- `document` 上维护 `char_count`、`segment_count`、`child_count`（由 `stats_service.recalc_document(doc_id)` 聚合本文档分段得出）。
- `dataset` 上维护 `doc_count`（未删除文档）、`processing_count`、`failed_count`、`available_doc_count`、`segment_count`（可用文档的通用分段或父块，含禁用）、`child_segment_count`、`char_count`（可用文档分段字符和）。`stats_service.recalc_dataset(dataset_id)` 对单个知识库聚合 `document` 表（≤1 万行）重算，**在同一事务内**于以下时机调用：文档创建/删除/状态变化/启停、分段新增/删除/内容替换、重新分段。
- 列表排序"按文档数"直接用冗余列。

### 3.3 检索可见标志 `search_enabled`

检索只扫描 `search_enabled = true` 的行，该列由 `segment_service.refresh_search_flags(document_id)` 在同一事务中统一重算：

- 通用分段：`doc.enabled AND doc.status='available' AND seg.enabled AND NOT seg.is_deleted AND seg.embedding IS NOT NULL`
- 子块：`doc.enabled AND doc.status='available' AND parent.enabled AND NOT parent.is_deleted AND NOT child.is_deleted AND child.embedding IS NOT NULL AND child.generation = parent.child_generation`

调用时机：文档启停、文档状态变为可用/离开可用、重新分段、分段启停/删除、分段编辑完成换入、父块子块重建换入、知识库删除。这样"禁用/删除后立即不可检索"与业务数据同事务一致（AC-42、AC-46、AC-60）。

### 3.4 文件存储

- 桶 `S3_BUCKET`；对象键：原文件 `uploads/{dataset_id}/{upload_file_id}/{file_hash}.{ext}`；解析文本 `parsed/{upload_file_id}.txt`（UTF-8）。
- 下载由 kb 服务流式转发（不暴露 MinIO 地址），响应头 `Content-Disposition: attachment; filename*=UTF-8''<urlencoded 原文件名>`。

### 3.5 解析与分段（预览与处理共用同一份代码，保证 AC-37/AC-63 一致）

**解析**（`parsers/`，纯函数，进程池执行）输出纯文本：

| 类型 | 规则 |
|---|---|
| TXT / Markdown / CSV | 先尝试 UTF-8（含 BOM），失败用 charset-normalizer 识别；Markdown 保留原文 |
| PDF（pypdf） | 加密且空密码无法解密 → `ENCRYPTED`；逐页提取文本，页之间用 `\n\n` 连接；全文去空白后为空 → `NO_TEXT` |
| DOCX（python-docx） | 段落之间 `\n\n`；表格每行 `单元格1 \| 单元格2`，行之间 `\n`，表格整体前后 `\n\n` |
| XLSX（openpyxl，read_only）/ XLS（xlrd） | 每个工作表：首行为表头，之后每行输出 `表头1: 值1; 表头2: 值2`，**行之间 `\n\n`**；工作表之间 `\n\n`，工作表开头一行 `# 工作表名` |
| CSV | 同 Excel 的行格式 |
| HTML（bs4 + lxml） | 移除 script/style；块级元素换行；连续空行压缩为 `\n\n` |
| PPTX（python-pptx） | 每页文本框按顺序 `\n` 连接，页之间 `\n\n` |

上传时的**轻量校验**（`parsers/registry.validate(path, ext)`）：扩展名白名单 `txt,md,markdown,pdf,docx,xlsx,xls,csv,html,htm,pptx`；大小 0 / >15MB；PDF 可打开且非加密；OOXML（docx/xlsx/pptx）必须是合法 zip 且含 `[Content_Types].xml`（加密的 OOXML 是 OLE 文件，会被判为"已加密或已损坏"）；XLS 可被 xlrd 打开；文本类可解码。

**预处理**（`splitters/preprocess.py`）：
- `normalize_whitespace=true`：`\r\n`/`\r` → `\n`；`[ \t\f\v 　]+` → 单个空格；`\n{3,}` → `\n\n`；每行首尾空格去除。
- `remove_urls_emails=true`：删除 `[\w.+-]+@[\w-]+\.[\w.-]+` 与 `https?://\S+|www\.\S+`。

**token 计数**：tiktoken `cl100k_base`（从 `app/assets/cl100k_base.tiktoken` 加载），`count_tokens(text)`。字符数 = Python `len(str)`。

**通用分段** `split_general(text, separator, max_tokens, overlap)`：
1. 分隔符反转义（`\n`、`\t`、`\\`），按分隔符切分，每段 strip，丢弃空段。
2. 每段 token ≤ max_tokens 直接输出；否则递归切分：依次尝试后备分隔符 `["\n", "。", "！", "？", "；", ".", "!", "?", ";", "，", ",", " ", ""]`（分隔符附着在前一单元末尾），将单元按顺序贪心合并为 ≤ max_tokens 的块；新块开头携带上一块末尾累计 ≤ overlap tokens 的单元作为重叠。
3. 不合并相邻的短段（遵循 PRD"先按分隔符切分"）。position 从 1 连续编号。

**父子分段** `split_parent_child(text, rule)`：
- 段落模式：父块 = `split_general(text, parent.separator, parent.max_tokens, 0)`；全文模式：整篇（预处理后）为一个父块，token > 10000 → `FULL_DOC_TOO_LONG`。
- 子块 = 对每个父块 `split_general(parent, child.separator, child.max_tokens, 0)`。

**分段规则 JSON（`process_rule`）**：

```json
{"mode": "general",
 "pre_processing": {"normalize_whitespace": true, "remove_urls_emails": false},
 "general": {"separator": "\\n\\n", "max_tokens": 1024, "chunk_overlap": 50}}

{"mode": "parent_child",
 "pre_processing": {"normalize_whitespace": true, "remove_urls_emails": false},
 "parent": {"mode": "paragraph", "separator": "\\n\\n", "max_tokens": 1024},
 "child": {"separator": "\\n", "max_tokens": 512}}
```

- `separator` 为用户输入的**转义写法字符串**（JSON 中 `"\\n\\n"` 即用户输入的 4 个字符 `\n\n`），长度 1~10。
- 校验：general.max_tokens 50~4000 且 ≤ 模型 `max_input_tokens`；chunk_overlap 0~floor(max_tokens×0.5)；parent.max_tokens 50~4000（paragraph 模式必填，full_doc 模式忽略 separator/max_tokens）；child.max_tokens 20~(paragraph 时 parent.max_tokens，full_doc 时 4000) 且 ≤ 模型 `max_input_tokens`。不合法 → 400001（`data.errors` 字段路径如 `process_rule.general.chunk_overlap`）。

### 3.6 文档处理流水线（kb-worker）

状态：`queued → parsing → splitting → indexing → available`，任一步失败 → `failed`（记录 `failed_stage`、`error_code`、`error_message`）。

```
提交/重试/重新分段：document.process_attempt += 1；status=queued；XADD stream:kb.tasks
  {"type":"document.process","payload":{"document_id":1,"attempt":3,"from_stage":"parse|split|index"}}

worker 处理（每阶段开始前重新读取 document，若 is_deleted、知识库已删除或 attempt 不一致 → 静默结束并 ACK）：
 parse : status=parsing；若 parsed/{upload_file_id}.txt 存在直接复用，否则解析并写入（进程池）
 split : status=splitting；同一事务：软删除该文档旧分段/子块 → 插入新分段（embedding 为空、search_enabled=false）
         同时为每个检索单元计算 tsv（jieba cut_for_search 后以空格连接，to_tsvector('simple', ...)）；
         progress_total = 检索单元数（通用=分段数，父子=子块数），progress_done=0
 index : status=indexing；取 embedding 为空的检索单元，按 EMBED_BATCH_SIZE 批量调用 Embedding；
         每批写回 embedding 并更新 progress_done、progress_updated_at；调用前检查模型仍为启用
 finish: 同一事务：status=available、refresh_search_flags、recalc_document、recalc_dataset
```

- **断点续做**：`from_stage` = 失败阶段；split 失败重试从 split 开始（解析文本已在 MinIO）；index 失败只补齐 embedding 为空的单元。
- **崩溃恢复**：消息未 ACK 时，消费组 `XAUTOCLAIM`（idle 10 分钟）转给其他 worker；各阶段幂等（split 先删后插，index 只处理空向量）。
- **超时巡检**（`worker/sweeper.py`，每分钟，单实例锁）：
  - `parsing/splitting/indexing` 且 `progress_updated_at` 超过 `PROCESS_TIMEOUT_MINUTES` → `failed`，`error_code=TIMEOUT`，"处理超时"，`process_attempt += 1`（使在途旧任务失效）。
  - `queued` 超过 30 分钟：按 TQ-01 推荐，检查消费组中是否仍有该文档的待处理消息；没有则重新投递，有则继续等待（若 TQ-01 被否决，则同样置为失败"处理超时"）。
- **错误码与可读原因**：

| error_code | 阶段 | error_message |
|---|---|---|
| FILE_MISSING | parse | 原文件不存在，请重新上传 |
| NO_TEXT | parse | 文件无可提取文本 |
| PARSE_ERROR | parse | 文件解析失败：{简述} |
| FULL_DOC_TOO_LONG | split | 文档超过 10,000 tokens，请使用段落模式 |
| SPLIT_ERROR | split | 分段失败：{简述} |
| EMBEDDING_DISABLED | index | 向量模型已停用 |
| EMBEDDING_TIMEOUT | index | 向量模型调用超时 |
| EMBEDDING_ERROR | index | 向量模型调用失败：{HTTP 状态或简述} |
| DIMENSION_MISMATCH | index | 向量维度与模型配置不一致 |
| TIMEOUT | 任意 | 处理超时 |

- 其他任务类型（同一 Stream）：

| type | payload | 处理 |
|---|---|---|
| `segment.reindex` | `{"segment_id", "version"}` | 通用分段：对 `pending_content` 计算向量与 tsv；同一事务内若 `segment.version` 未变则换入（content←pending_content、keywords←pending_keywords、清空 pending、index_status=indexed、refresh_search_flags、recalc）；版本已变则丢弃（新任务会再来） |
| `child.reindex` | `{"child_id", "version"}` | 子块同上 |
| `parent.regenerate` | `{"segment_id", "version"}` | 父块：按文档子块规则切分 `pending_content` → 插入 generation+1 的新子块（search_enabled=false）→ 向量化 → 同一事务换入（父块 content、`child_generation+1`、软删旧子块、refresh_search_flags、recalc） |

  失败时 `index_status=failed`、`index_error`，检索继续使用旧内容；用户再次保存即重新入队。

### 3.7 检索引擎（`engine/retriever.py`）

输入：知识库、查询文本、生效检索设置（默认设置被本次覆盖项合并）。

1. 知识库 Embedding 模型非启用 → 409303（**任何检索方式都拒绝**，与 F-07 规则 7 一致）。
2. 检索单元表：通用 → `kb.segment`；父子 → `kb.child_chunk`。
3. 候选数 `n`：不重排的向量/全文检索：通用 = top_k，父子 = min(top_k×5, 100)；混合或开启 Rerank：min(max(top_k×4, 20), 100)。
4. 向量检索：查询向量（Redis 缓存 `kb:qemb:{model_id}:{sha256(query)}`，600s）→ `ORDER BY embedding <=> :qv LIMIT n`，`WHERE dataset_id=:d AND search_enabled`；`score = clamp(1 - cosine_distance, 0, 1)`。
5. 全文检索：`jieba.cut_for_search(query)` → 去掉空白与纯标点 → 去重；为空则无结果；构造 tsquery 字符串 `'词1' | '词2'`（词内单引号转义为 `''`、去掉反斜杠，整体作为**绑定参数**传入 `to_tsquery('simple', :q)`）；`WHERE tsv @@ q`，`score = ts_rank_cd(tsv, q, 32)`（归一化到 0~1），取前 n。
6. 混合-权重：两路候选取并集，对并集内缺失的另一路得分按 ID 补算；`score = w×向量分 + (1−w)×关键词分`。
7. 重排（混合-Rerank 模式，或向量/全文开启 Rerank）：候选文本（通用=分段内容，父子=子块内容）调用 Rerank → `score = relevance_score`（若任一分值不在 [0,1]，对全部做 sigmoid）。Rerank 模型不存在或停用 → **跳过重排**（混合模式退化为权重 0.7），`rerank_skipped=true`，`rerank_skipped_reason="重排模型不可用，已跳过重排"`；Rerank 服务调用失败 → 503301。
8. 阈值：开启时过滤 `score < threshold`（父子按子块得分）。
9. 父子聚合：按父块分组，父块得分 = 命中子块最高分，子块按得分降序附带；按父块得分降序取 top_k。通用直接取 top_k。同分按 ID 升序。
10. 组装结果（通用分段/父块内容、序号、关键词、文档 ID 与名称）。
11. 召回次数：对返回的通用分段/父块及其文档 `HINCRBY kb:hits:segment / kb:hits:document`，worker 每 60 秒落库。

`VectorStore` 抽象：`search(dataset_id, table, query_vector, limit) -> list[(id, score)]`、`score_by_ids(...)`；本期实现 `PgVectorStore`。

### 3.8 管理视图与转移

- 管理视图数据范围：`data_scope_filter(ctx, company_col=dataset.company_id, dept_col=dataset.dept_id, owner_col=dataset.owner_id)`。
- 管理视图只读接口独立于日常接口（`/api/v1/kb/admin/...`），**不复用**日常接口的 ACL，避免把"管理可见"泄露为"日常可访问"。
- 超级管理员删除他人知识库（F-09 规则 7）：通过日常删除接口时，若调用者为超管则放行 ACL（仍需 `confirm_name`）。前端不在管理视图提供删除按钮（PRD 管理视图不能删除），超管如需删除可先转移给自己。
- 转移（管理员与所有者自行转移共用 `transfer_service.transfer(dataset, receiver, operator)`，单事务，`SELECT ... FOR UPDATE` 锁知识库行）：
  - 接收人：存在、启用、未删除（以 AuthContext 判定，强一致）；不能是当前所有者（400322）。
  - 管理员转移：知识库与接收人均在操作人数据范围内（接收人按 `user_ref.company_id / org_id / id` 判定）。
  - 所有者自行转移：接收人所属公司在所有者所属公司及其下属内（集团本部所有者不限）。
  - 接收人名下同名 → 409321。
  - 更新 `owner_id`、`company_id`、`dept_id`（接收人当时的组织）、`version+1`；分配不变；原所有者若有个人分配记录不受影响（PRD 规则：原所有者失去所有者身份，不保留访问权，除非已存在其他分配途径）。
- 批量转移：同一事务；任一同名冲突 → 整体拒绝 409321，`data={"conflicts":["产品手册"]}`。
- 转移与原所有者并发编辑：编辑类接口均在事务内重新校验 ACL；转移提交后原所有者的后续请求因 ACL 失败被拒（404000）。

### 3.9 只读副本同步（kb-worker）

- `kb.user_ref`、`kb.org_ref` 由 `StreamConsumer(stream:iam.events, group=kb-ref-sync)` 维护，按 `updated_at` 只接受更新的数据。
- 启动时副本为空则全量拉取（`/internal/v1/sync/users|orgs`）；之后每 `REF_RECONCILE_INTERVAL_SECONDS` 用游标增量对账（游标存 Redis `kb:ref:cursor:users|orgs`，每次回退 60 秒重叠）。
- 组织 `company_id` 变化（移动）时：`UPDATE kb.dataset SET company_id = :new WHERE dept_id = :org_id`（F-02 规则 6"知识库所属公司随之重新计算"）。

---

## 4. 数据模型（schema `kb`）

> 基类字段见总体方案 4.3。首个迁移 `0001_init_kb`：`CREATE SCHEMA IF NOT EXISTS kb`、`CREATE EXTENSION IF NOT EXISTS vector`、全部表与索引；downgrade：逐表 `DROP TABLE`，保留空的 `kb` schema（`alembic_version` 位于该 schema 内，与 iam 一致）；不删 `vector` 扩展。

### 4.1 `kb.ai_model`（受数据权限控制：否，全局资源）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| name | VARCHAR(50) | NOT NULL | | `uq (name) WHERE is_deleted=false` |
| model_type | VARCHAR(16) | NOT NULL | | `embedding` / `rerank` |
| base_url | VARCHAR(500) | NOT NULL | | http/https，去掉末尾 `/` |
| model_name | VARCHAR(100) | NOT NULL | | |
| api_key_encrypted | TEXT | NULL | | Fernet 加密 |
| api_key_hint | VARCHAR(16) | NULL | | 掩码展示用，如 `sk-****abcd` |
| dimension | INT | NULL | | embedding 必填 |
| max_input_tokens | INT | NOT NULL | 512 | |
| status | VARCHAR(16) | NOT NULL | 'disabled' | |
| is_default | BOOLEAN | NOT NULL | false | `uq (model_type) WHERE is_default AND is_deleted=false` |
| last_test_at | TIMESTAMPTZ | NULL | | |
| last_test_ok | BOOLEAN | NULL | | |
| version | INT | NOT NULL | 1 | |

### 4.2 `kb.dataset`（受数据权限控制：**是**（管理视图/管理员转移）；本人列 `owner_id`）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| name | VARCHAR(50) | NOT NULL | | `uq (owner_id, name) WHERE is_deleted=false` |
| description | VARCHAR(400) | NULL | | |
| icon | VARCHAR(50) | NULL | | 预置图标 key |
| owner_id | BIGINT | NOT NULL, INDEX | | |
| company_id | BIGINT | NOT NULL, INDEX | | 所有者所在公司（创建/转移时） |
| dept_id | BIGINT | NOT NULL, INDEX | | 所有者所在组织节点（创建/转移时） |
| embedding_model_id | BIGINT | NOT NULL, INDEX | | |
| chunk_mode | VARCHAR(16) | NULL | | `general` / `parent_child`；首次提交文档时确定；文档全部删除后置回 NULL |
| indexing_technique | VARCHAR(16) | NOT NULL | 'high_quality' | |
| retrieval_config | JSONB | NOT NULL | 默认值见 5.3 | |
| last_process_rule | JSONB | NULL | | "使用上次设置" |
| doc_count / processing_count / failed_count / available_doc_count | INT | NOT NULL | 0 | 冗余统计 |
| segment_count / child_segment_count | INT | NOT NULL | 0 | |
| char_count | BIGINT | NOT NULL | 0 | |
| version | INT | NOT NULL | 1 | |

`created_by` = 创建人（不随转移变化）。索引：`ix_dataset_updated (updated_at DESC)`。

### 4.3 `kb.dataset_assignment`（否，随知识库）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| dataset_id | BIGINT | NOT NULL, INDEX | | |
| target_type | VARCHAR(16) | NOT NULL | | `user` / `dept` / `company` |
| target_id | BIGINT | NOT NULL | | 用户 ID 或组织 ID |
| include_children | BOOLEAN | NOT NULL | | 部门默认 true，公司默认 false，用户恒 false |
| permission | VARCHAR(8) | NOT NULL | 'read' | `read` / `edit` |

- `uq (dataset_id, target_type, target_id) WHERE is_deleted=false`；`ix (target_type, target_id) WHERE is_deleted=false`。逻辑删除。

### 4.4 `kb.upload_file`（否，临时数据，过期物理删除）
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| dataset_id | BIGINT | NOT NULL, INDEX | |
| name | VARCHAR(200) | NOT NULL | 原始文件名（超长截断保留扩展名） |
| file_ext | VARCHAR(10) | NOT NULL | 小写 |
| file_size | BIGINT | NOT NULL | |
| file_hash | CHAR(64) | NOT NULL | SHA-256 |
| storage_key | VARCHAR(300) | NOT NULL | |
| parsed_key | VARCHAR(300) | NULL | 解析文本对象键 |
| doc_token_count | INT | NULL | 预处理前全文 token 数（预览时写入） |
| consumed_document_id | BIGINT | NULL | 已提交为文档 |
| expires_at | TIMESTAMPTZ | NOT NULL | 创建 + 24h |

### 4.5 `kb.document`（否，随知识库）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| dataset_id | BIGINT | NOT NULL | | |
| upload_file_id | BIGINT | NOT NULL, UNIQUE | | |
| name | VARCHAR(200) | NOT NULL | | |
| file_ext / file_size / file_hash / storage_key / parsed_key | | | | 来自 upload_file |
| chunk_mode | VARCHAR(16) | NOT NULL | | |
| process_rule | JSONB | NOT NULL | | |
| status | VARCHAR(16) | NOT NULL | 'queued' | |
| failed_stage | VARCHAR(8) | NULL | | parse / split / index |
| error_code | VARCHAR(32) | NULL | | |
| error_message | VARCHAR(500) | NULL | | |
| progress_done / progress_total | INT | NOT NULL | 0 | |
| progress_updated_at | TIMESTAMPTZ | NOT NULL | now() | 超时判定 |
| process_attempt | INT | NOT NULL | 1 | 任务栅栏 |
| enabled | BOOLEAN | NOT NULL | true | |
| char_count / segment_count / child_count | INT | NOT NULL | 0 | |
| hit_count | BIGINT | NOT NULL | 0 | |
| version | INT | NOT NULL | 1 | |

- `uq (dataset_id, file_hash) WHERE is_deleted=false`（AC-38）；`ix (dataset_id, status)`；`ix (dataset_id, created_at DESC)`。`created_by` = 上传人。

### 4.6 `kb.segment`（否，随知识库）—— 通用分段 / 父块
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| dataset_id | BIGINT | NOT NULL | | |
| document_id | BIGINT | NOT NULL | | |
| position | INT | NOT NULL | | 文档内序号，从 1 开始 |
| segment_type | VARCHAR(8) | NOT NULL | | `general` / `parent` |
| content | TEXT | NOT NULL | | 当前生效（参与检索）的内容 |
| pending_content | TEXT | NULL | | 编辑后等待索引的内容 |
| keywords | TEXT[] | NOT NULL | '{}' | 仅 general |
| pending_keywords | TEXT[] | NULL | | |
| char_count / token_count | INT | NOT NULL | | 按 content |
| enabled | BOOLEAN | NOT NULL | true | |
| edited | BOOLEAN | NOT NULL | false | |
| hit_count | BIGINT | NOT NULL | 0 | |
| index_status | VARCHAR(16) | NOT NULL | 'pending' | `pending` / `indexed` / `updating` / `failed` |
| index_error | VARCHAR(300) | NULL | | |
| child_generation | INT | NOT NULL | 1 | 仅 parent |
| embedding | HALFVEC | NULL | | 仅 general；不定维度 |
| tsv | TSVECTOR | NULL | | 仅 general；关键词权重 A、内容权重 B |
| search_enabled | BOOLEAN | NOT NULL | false | 见 3.3 |
| version | INT | NOT NULL | 1 | |

- 索引：`ix (document_id, position)`；`ix_seg_search (dataset_id) WHERE search_enabled`；`GIN (tsv) WHERE search_enabled`。

### 4.7 `kb.child_chunk`（否，随知识库）
| 字段 | 类型 | 约束 | 默认 | 说明 |
|---|---|---|---|---|
| dataset_id / document_id / segment_id | BIGINT | NOT NULL | | segment_id = 父块 |
| generation | INT | NOT NULL | 1 | 与父块 child_generation 一致才生效 |
| position | INT | NOT NULL | | 父块内序号 |
| content / pending_content | TEXT | | | |
| char_count / token_count | INT | NOT NULL | | |
| edited | BOOLEAN | NOT NULL | false | |
| index_status / index_error | | | | 同 segment |
| embedding | HALFVEC | NULL | | |
| tsv | TSVECTOR | NULL | | 内容权重 B |
| search_enabled | BOOLEAN | NOT NULL | false | |
| version | INT | NOT NULL | 1 | |

- 索引：`ix (segment_id, generation, position)`；`ix_child_search (dataset_id) WHERE search_enabled`；`GIN (tsv) WHERE search_enabled`。

### 4.8 `kb.retrieval_record`（否；仅本人可见）
| 字段 | 类型 | 说明 |
|---|---|---|
| dataset_id | BIGINT NOT NULL | |
| query | VARCHAR(500) NOT NULL | |
| retrieval_config | JSONB NOT NULL | 本次生效设置 |
| result_count | INT NOT NULL | |
- `ix (dataset_id, created_by, created_at DESC)`；插入后删除该用户在该库第 20 条之后的记录（物理删除，保留期策略）。

### 4.9 `kb.user_ref` / `kb.org_ref`（否；iam 只读副本，主键 = iam 中的 ID，不使用自增）
- `user_ref`：`id`、`username`、`name`、`status`、`is_deleted`、`org_id`、`company_id`、`source_updated_at` + 基类时间字段。索引 `org_id`、`company_id`、`name`。
- `org_ref`：`id`、`parent_id`、`ancestors`、`org_type`、`name`、`code`、`status`、`is_deleted`、`company_id`、`sort_order`、`source_updated_at`。

---

## 5. 接口契约（kb）

> 统一约定见总体方案第 4 节。下文"ACL 只读/可编辑/所有者"指 3.1 的资源级别；不可访问 → 404000，级别不足 → 403311。

### 5.0 kb 专属错误码

| code | message | 说明 |
|---|---|---|
| 400301 | 模型连接测试未通过，不能启用 | `data={"error_message":"..."}` |
| 400302 | Embedding 模型必须填写向量维度 | |
| 400303 | 请选择已启用的模型 | |
| 409301 | 模型已被知识库使用，不能修改服务地址、模型标识或维度 | `data={"datasets":["名称",...最多10个],"total":n}` |
| 409302 | 模型已被知识库使用，不能删除 | 同上 |
| 409303 | 向量模型已停用，请联系管理员 | 上传、预览、提交、重试、检索 |
| 409304 | 模型名称已存在 | |
| 503301 | 模型服务调用失败：{原因} | 检索、测试外的在线调用 |
| 403311 | 您对该知识库没有此操作权限 | 有 ACL 但级别不足 |
| 400311 | 输入的名称与知识库名称不一致 | 删除确认 |
| 409311 | 您已有同名知识库 | |
| 409312 | 已有文档，暂不支持更换向量模型 | |
| 400321 | 接收人不在可转移范围内或账号不可用 | |
| 400322 | 接收人已是该知识库的所有者 | |
| 409321 | 接收人已有同名知识库，请先改名 | 批量时 `data.conflicts` |
| 400401 | 不能分配给所有者本人 | |
| 400402 | 分配对象不在可分配范围内 | |
| 409401 | 该对象已在分配名单中 | |
| 400501 | 不支持的文件类型 | |
| 400502 | 文件超过 15 MB | |
| 400503 | 文件为空 | |
| 400504 | 文件已加密或已损坏 | |
| 400505 | 未能从文件中提取到文本 | |
| 400506 | 文档超过 10,000 tokens，请使用段落模式 | |
| 400508 | 上传文件已失效，请重新上传 | upload_file 不存在/过期/已提交/不属于该库 |
| 409501 | 与已有文档《{name}》内容重复 | 提交时 `data={"duplicates":[{"upload_file_id":1,"existing_document_name":"手册.pdf"}]}` |
| 409502 | 知识库文档数已达上限 | |
| 409503 | 该知识库的分段方式为{通用分段/父子分段}，不能切换 | |
| 409504 | 文档处理中，暂不能执行该操作 | |
| 409505 | 只有处理失败的文档可以重试 | |
| 409506 | 知识库没有可用文档 | |
| 400511 | 分段内容长度超出范围 | `data={"max_tokens":1024}` |
| 400512 | 关键词不合法（最多 10 个，每个不超过 20 字） | |
| 400513 | 当前分段方式不支持该操作 | 如通用分段新增子块 |
| 409511 | 该分段已被他人修改 | 分段/子块 version 冲突（替代 409001） |
| 409512 | 编辑父块将重新生成子块，请确认 | 未带 `confirm_regenerate_children=true` |

### 5.1 模型配置

`ModelItem`：
```json
{"id": 1, "name": "BGE-M3", "model_type": "embedding", "base_url": "http://10.0.0.5:9997/v1",
 "model_name": "bge-m3", "api_key_hint": "sk-****abcd", "dimension": 1024, "max_input_tokens": 8192,
 "status": "enabled", "is_default": true, "dataset_count": 3, "last_test_at": "2026-11-11T10:00:00+08:00",
 "last_test_ok": true, "version": 2, "created_at": "...", "updated_at": "..."}
```

| 接口 | 权限码 | 说明 |
|---|---|---|
| `GET /api/v1/kb/models` | system:model:list | query：`page`、`page_size`、`model_type`、`status`、`keyword`；分页 `ModelItem`；`dataset_count` = 未删除知识库引用数（rerank 模型统计 retrieval_config 中引用的知识库数） |
| `POST /api/v1/kb/models` | system:model:create | body：`name`(1~50)、`model_type`、`base_url`(http/https，≤500)、`model_name`(1~100)、`api_key`(可选，≤500)、`dimension`(embedding 必填，1~16000)、`max_input_tokens`(默认 512，1~131072)、`status`(默认 disabled)、`is_default`(默认 false)。`status=enabled` 时服务端同步执行测试，失败 → 400301；测试得到的维度与填写不一致 → 400301。`is_default=true` 要求 enabled，且取消同类型其他默认 |
| `PUT /api/v1/kb/models/{id}` | system:model:update | body 同上（不含 model_type）+ `version`；`api_key`：不传或 null = 不修改，`""` = 清空；被引用的 embedding 模型修改 base_url/model_name/dimension → 409301 |
| `PUT /api/v1/kb/models/{id}/status` | system:model:update | body：`status`、`version`；启用前服务端测试（400301）；停用默认模型时同时取消默认 |
| `PUT /api/v1/kb/models/{id}/default` | system:model:update | body：`version`；须为启用状态（400303） |
| `DELETE /api/v1/kb/models/{id}` | system:model:delete | 被引用 → 409302 |
| `POST /api/v1/kb/models/test` | 任一 system:model:create / system:model:update | body：`model_id`(可选；带上时未提供的字段取已保存值，含凭据)、`model_type`、`base_url`、`model_name`、`api_key`；data：`{"success":true,"dimension":1024,"latency_ms":120,"error_message":null}`；**不抛 503**，失败通过 `success=false` 返回 |
| `GET /api/v1/kb/models/options` | 任一 kb:dataset:list / kb:dataset:create | query：`model_type`(必填)；data：`[{"id":1,"name":"BGE-M3","model_type":"embedding","dimension":1024,"max_input_tokens":8192,"is_default":true}]`，仅启用模型，不含地址与凭据 |

测试连接：Embedding `POST {base_url}/embeddings`，body `{"model": model_name, "input": ["连接测试"]}`，取 `data[0].embedding` 长度为维度；Rerank `POST {base_url}/rerank`，body `{"model","query":"连接测试","documents":["连接测试"],"top_n":1,"return_documents":false}`，响应须含 `results[].index` 与 `results[].relevance_score`。均带 `Authorization: Bearer {api_key}`（有凭据时），超时 `MODEL_HTTP_TIMEOUT_SECONDS`。

操作日志：model/create|update|status|set_default|delete，摘要不含凭据。

### 5.2 知识库

`DatasetItem`（列表）：
```json
{"id": 10, "name": "集团制度", "description": "...", "icon": "book",
 "owner": {"id": 12, "name": "张三", "status": "enabled"},
 "my_permission": "owner", "chunk_mode": "general", "indexing_technique": "high_quality",
 "search_method": "hybrid", "doc_count": 128, "processing_count": 2, "failed_count": 0,
 "available_doc_count": 126, "segment_count": 3450, "child_segment_count": 0, "char_count": 2100000,
 "embedding_model": {"id": 1, "name": "BGE-M3", "status": "enabled"},
 "created_at": "...", "updated_at": "2026-11-10T18:00:00+08:00"}
```
`owner.status`：`enabled` / `disabled` / `deleted`（来自 user_ref）。

`DatasetDetail` = `DatasetItem` + `retrieval_config`、`last_process_rule`、`owner_org`（`{"company_id":3,"company_name":"A公司","dept_id":5,"dept_name":"研发部"}`）、`assignment_count`、`version`。

#### 5.2.1 `GET /api/v1/kb/datasets` — 我的知识库
- 权限码 `kb:dataset:list`；ACL：所有者 + 被分配（不按 data_scope）
- query：`page`、`page_size`(1~100)、`keyword`(名称模糊)、`my_permission`(`owner|edit|read`)、`owner_keyword`(所有者姓名/账号模糊，user_ref)、`chunk_mode`(`general|parent_child|unset`)、`only_owned`(bool)、`sort_by`(`updated_at|name|doc_count`，默认 updated_at)、`sort_order`(默认 desc；name 默认 asc)
- 响应：分页 `DatasetItem`

#### 5.2.2 `GET /api/v1/kb/datasets/options` — 可访问知识库选项
- 权限码：任一 `kb:dataset:list`、`openapi:apikey:manage`；ACL 同上
- query：`keyword`、`page`、`page_size`(默认 50)
- 响应：分页 `{"id":10,"name":"集团制度","my_permission":"read"}`（用于 API 密钥"指定知识库"选择）

#### 5.2.3 `POST /api/v1/kb/datasets`
- 权限码 `kb:dataset:create`
- body：`name`(1~50，trim)、`description`(≤400)、`icon`(≤50)、`embedding_model_id`(可选，默认默认模型；须启用的 embedding 模型，否则 400303；无默认模型且未传 → 400303)、`retrieval_config`(可选，缺省用默认值)
- 处理：owner_id=created_by=当前用户；company_id/dept_id 取 ctx；`chunk_mode=null`
- 响应：`DatasetDetail`；错误：409311、400303
- 操作日志 dataset/create

#### 5.2.4 `GET /api/v1/kb/datasets/{id}` — 权限码 `kb:dataset:list`；ACL 只读；响应 `DatasetDetail`

#### 5.2.5 `PUT /api/v1/kb/datasets/{id}` — 编辑基础信息
- 权限码 `kb:dataset:update`；ACL 可编辑
- body：`name`、`description`、`icon`、`embedding_model_id`(可选；与当前不同时要求 ACL=所有者（403311）且 `doc_count=0`（409312），模型须启用 embedding)、`version`
- 响应 `DatasetDetail`；操作日志 dataset/update（摘要前后值）

#### 5.2.6 `PUT /api/v1/kb/datasets/{id}/retrieval-config`
- 权限码 `kb:dataset:update`；ACL 可编辑
- body：`retrieval_config`、`version`
- `retrieval_config` 结构与校验：
  | 字段 | 类型 | 规则 | 默认 |
  |---|---|---|---|
  | search_method | string | `vector` / `full_text` / `hybrid` | vector |
  | top_k | int | 1~20 | 3 |
  | score_threshold_enabled | bool | | false |
  | score_threshold | number | 0~1，两位小数 | 0.5 |
  | reranking_enable | bool | 仅 vector/full_text 有效 | false |
  | reranking_model_id | int \| null | reranking_enable 或 hybrid_mode=rerank 时必填，须为启用的 rerank 模型（400303） | null |
  | hybrid_mode | string | `weighted` / `rerank`（仅 hybrid） | weighted |
  | vector_weight | number | 0~1，步长 0.1（关键词权重 = 1 − 该值，后端不存） | 0.7 |
- 操作日志 dataset/retrieval_config

#### 5.2.7 `DELETE /api/v1/kb/datasets/{id}`
- 权限码 `kb:dataset:delete`；ACL 所有者（超管放行）
- body：`confirm_name: string`（≠名称 → 400311）
- 处理（单事务）：知识库、文档、分段、子块、分配逻辑删除；分段/子块 `search_enabled=false`；文档 `process_attempt+1`（在途任务失效）；`chunk_mode` 保持。
- 响应 `null`；操作日志 dataset/delete（摘要含分配对象数）

#### 5.2.8 `POST /api/v1/kb/datasets/{id}/transfer` — 所有者自行转移
- 权限码 `kb:dataset:transfer`；ACL 所有者
- body：`receiver_user_id`、`version`；规则见 3.8；错误 400321、400322、409321
- 响应 `DatasetDetail`（调用者此后通常已无访问权，前端跳回列表）；操作日志 dataset/transfer

### 5.3 分配

`AssignmentItem`：
```json
{"id": 3, "target_type": "dept", "target_id": 8, "target_name": "测试部", "target_path": "A公司/测试部",
 "target_valid": true, "include_children": true, "permission": "read",
 "created_by": {"id": 12, "name": "张三"}, "created_at": "..."}
```
`target_valid=false`：对象已删除（分配自动失效，仅展示）。

| 接口 | 权限码 | ACL | 说明 |
|---|---|---|---|
| `GET /api/v1/kb/datasets/{id}/assignments` | kb:dataset:list | 可编辑 | 不分页（单库分配数预计 <500），按 created_at 升序 |
| `POST /api/v1/kb/datasets/{id}/assignments` | kb:dataset:assign | 所有者 | body：`target_type`、`target_id`、`include_children`(user 时忽略；dept 默认 true；company 默认 false)、`permission`(默认 read)。错误 400401、400402、409401。日志 dataset/assign_create |
| `PUT /api/v1/kb/datasets/{id}/assignments/{assignment_id}` | kb:dataset:assign | 所有者 | body：`permission`、`include_children`。日志 dataset/assign_update |
| `DELETE /api/v1/kb/datasets/{id}/assignments/{assignment_id}` | kb:dataset:assign | 所有者 | 日志 dataset/assign_delete |
| `GET /api/v1/kb/datasets/{id}/assignable-orgs` | 任一 kb:dataset:assign / kb:dataset:transfer | 所有者 | 返回可分配范围内的组织树（org_ref，未删除），节点 `{"id","parent_id","name","org_type","status","children"}` |
| `GET /api/v1/kb/datasets/{id}/assignable-users` | 任一 kb:dataset:assign / kb:dataset:transfer | 所有者 | query：`keyword`(姓名/账号)、`org_id`(含下级)、`page`、`page_size`；分页 `{"id","username","name","org_name","company_name"}`，只含启用未删除用户，排除所有者本人 |

可分配范围：所有者当前所属公司 C（`ctx.company_id`）及其下属所有组织；C 为集团节点时为全集团。目标为组织时要求该组织在范围内；目标为用户时要求其主组织在范围内。转移接收人选择复用 `assignable-users`。

### 5.4 上传与预览

#### 5.4.1 `POST /api/v1/kb/datasets/{id}/upload-files` — 上传单个文件
- 权限码 `kb:document:upload`；ACL 可编辑
- 请求：`multipart/form-data`，字段 `file`（单文件；前端并发上传多个，每个单独请求，便于逐个进度与重试）
- 校验顺序：Embedding 模型启用（409303）→ 扩展名（400501）→ 大小 0（400503）/ >15MB（400502）→ 轻量校验（400504）→ 内容哈希与本库未删除文档重复（409501，`data={"existing_document_name":"手册.pdf"}`）→ 文档数上限（409502）
- 响应 data：`{"upload_file_id": 55, "name": "员工手册.pdf", "file_ext": "pdf", "file_size": 5242880, "file_hash": "ab12..."}`
- 一次最多 20 个文件由前端限制（PRD 交互约束）；后端不感知批次。

#### 5.4.2 `POST /api/v1/kb/datasets/{id}/documents/preview` — 分段预览
- 权限码 `kb:document:upload`；ACL 可编辑
- body：`upload_file_id`、`process_rule`（3.5）
- 校验：upload_file 属于本库且未过期未提交（400508）；知识库已定分段方式时 `process_rule.mode` 必须一致（409503）；规则参数（400001）
- 处理：解析（有缓存直接用；进程池；超时 60s）→ 预处理 → 分段（全量）→ 返回前 10 个
- 响应 data：
  ```json
  {"mode": "parent_child", "total_segments": 42, "total_child_chunks": 300, "doc_token_count": 3012,
   "segments": [{"position": 1, "content": "...", "char_count": 980, "token_count": 512,
                 "children": [{"position": 1, "content": "...", "char_count": 300, "token_count": 160}]}]}
  ```
  通用分段时 `children` 为空数组、`total_child_chunks=0`。
- 错误：400505、400506、400508、409503、409303

#### 5.4.3 `POST /api/v1/kb/datasets/{id}/documents` — 提交处理
- 权限码 `kb:document:upload`；ACL 可编辑
- body：`upload_file_ids: int[]`（1~20，去重）、`process_rule`
- 处理（单事务，`SELECT dataset FOR UPDATE`）：知识库未删除；模型启用（409303）；`chunk_mode` 为空则设为 `process_rule.mode`，否则须一致（409503）；文档数 + 本次 ≤ 上限（409502）；每个 upload_file 有效（400508）；与已有文档或本次其他文件内容重复 → 409501（整体拒绝，`data.duplicates`）；创建 document（status=queued），标记 upload_file 已消费；`last_process_rule = process_rule`；recalc_dataset；提交后 XADD 任务。
- 响应 data：`{"documents": [{"id": 101, "name": "员工手册.pdf", "status": "queued"}]}`
- 操作日志：每个文档一条 document/upload

### 5.5 文档

`DocumentItem`：
```json
{"id": 101, "name": "员工手册.pdf", "file_ext": "pdf", "file_size": 5242880, "chunk_mode": "general",
 "char_count": 52301, "segment_count": 120, "child_count": 0, "hit_count": 35,
 "uploaded_by": {"id": 12, "name": "张三"}, "created_at": "...",
 "status": "indexing", "progress": {"done": 60, "total": 120},
 "error_code": null, "error_message": null, "enabled": true, "version": 3}
```

| 接口 | 权限码 | ACL | 说明 |
|---|---|---|---|
| `GET /api/v1/kb/datasets/{id}/documents` | kb:dataset:list | 只读 | query：`page`、`page_size`、`keyword`、`status`(`queued|parsing|splitting|indexing|available|failed|processing`；processing=前四者)、`enabled`、`sort_by`(`created_at|char_count|hit_count`)、`sort_order`；分页 `DocumentItem` |
| `GET /api/v1/kb/datasets/{id}/documents/progress` | kb:dataset:list | 只读 | query：`ids`（逗号分隔，≤50）；data：`[{"id","status","progress","error_code","error_message","segment_count","child_count","char_count"}]`，供上传第 3 步和列表轮询 |
| `GET /api/v1/kb/datasets/{id}/documents/{document_id}` | kb:dataset:list | 只读 | `DocumentItem` + `process_rule` |
| `PUT /api/v1/kb/datasets/{id}/documents/enabled` | kb:document:update | 可编辑 | body：`document_ids`(1~100)、`enabled`；不在本库的 ID → 404000（整体拒绝）；refresh_search_flags + recalc；data：`{"updated": 3}` |
| `POST /api/v1/kb/datasets/{id}/documents/batch-delete` | kb:document:delete | 可编辑 | body：`document_ids`(1~100)；处理中也可删除（attempt+1 取消处理）；分段一并逻辑删除；全部文档删除后 `chunk_mode` 置 NULL；日志每文档 document/delete |
| `POST /api/v1/kb/datasets/{id}/documents/{document_id}/reprocess` | kb:document:update | 可编辑 | body：`process_rule`(mode 须与知识库一致 409503)、`version`；仅 available/failed（否则 409504）；立即 status=queued、search_enabled 全部 false、edited 标记随新分段清空；from_stage=split（解析文本存在时）；日志 document/reprocess |
| `POST /api/v1/kb/datasets/{id}/documents/{document_id}/retry` | kb:document:update | 可编辑 | 仅 failed（409505）；模型停用 → 409303；from_stage=failed_stage |
| `GET /api/v1/kb/datasets/{id}/documents/{document_id}/download` | kb:document:download | 只读 | 流式返回原文件（非统一 JSON 响应；错误时返回统一 JSON）。管理视图无此能力 |

### 5.6 分段

`SegmentItem`：
```json
{"id": 5001, "position": 1, "segment_type": "general", "content": "第一章 总则 ...",
 "keywords": ["总则", "适用范围"], "char_count": 356, "token_count": 210, "enabled": true,
 "edited": true, "hit_count": 5, "index_status": "indexed", "index_error": null, "version": 4,
 "children": []}
```
- `content`：`index_status=updating` 时返回 `pending_content`（用户看到的是自己编辑后的内容），检索仍用旧内容。
- 父块的 `children`：`[{"id","position","content","char_count","token_count","edited","index_status","index_error","version"}]`（当前 generation）。

| 接口 | 权限码 | ACL | 说明 |
|---|---|---|---|
| `GET /api/v1/kb/datasets/{id}/documents/{document_id}/segments` | kb:dataset:list | 只读 | query：`page`、`page_size`(默认 20，≤100)、`keyword`(内容模糊；父子时匹配父块或子块)、`enabled`；按 position 升序；分页 `SegmentItem`；响应额外顶层字段不加，文档上下文用 5.5 详情接口获取 |
| `POST /api/v1/kb/datasets/{id}/documents/{document_id}/segments` | kb:segment:update | 可编辑 | 仅通用分段（父子 → 400513）；文档须 available（409504）；body：`content`(1~该文档 general.max_tokens tokens，400511)、`keywords`(0~10，每个 1~20 字，去重，400512)；追加 position=max+1，`edited=true`，入队 `segment.reindex`（新分段 index_status=pending，索引完成前不参与检索）；返回 `SegmentItem` |
| `PUT /api/v1/kb/datasets/{id}/segments/{segment_id}` | kb:segment:update | 可编辑 | body：`content`、`keywords`(通用)、`version`、`confirm_regenerate_children`(父块必须 true，否则 409512)；文档须 available；`index_status=updating` 时也允许再次编辑（覆盖 pending）；长度上限：通用=general.max_tokens，父块=parent.max_tokens（全文模式 10000）；写入 pending_*、`edited=true`、`version+1`，入队 `segment.reindex` 或 `parent.regenerate`；version 冲突 → 409511 |
| `PUT /api/v1/kb/datasets/{id}/segments/{segment_id}/enabled` | kb:segment:update | 可编辑 | body：`enabled`；父块整体生效；refresh_search_flags |
| `DELETE /api/v1/kb/datasets/{id}/segments/{segment_id}` | kb:segment:update | 可编辑 | 逻辑删除（父块连同子块）；refresh + recalc |
| `POST /api/v1/kb/datasets/{id}/segments/{segment_id}/children` | kb:segment:update | 可编辑 | 仅父块（否则 400513）；body：`content`(1~child.max_tokens)；追加到父块末尾，入队 `child.reindex`；返回子块对象 |
| `PUT /api/v1/kb/datasets/{id}/child-chunks/{child_id}` | kb:segment:update | 可编辑 | body：`content`、`version`；入队 `child.reindex`；409511 |
| `DELETE /api/v1/kb/datasets/{id}/child-chunks/{child_id}` | kb:segment:update | 可编辑 | 逻辑删除；refresh + recalc |

### 5.7 召回测试

#### 5.7.1 `POST /api/v1/kb/datasets/{id}/retrieve-test`
- 权限码 `kb:retrieval:test`；ACL 只读（管理视图无此能力）
- body：`query`(1~500 字，trim 后非空)、`retrieval_config`(可选，完整结构，覆盖默认；校验同 5.2.6)
- 前置：`available_doc_count=0` → 409506；模型停用 → 409303
- 响应 data（`RetrievalResult`，与内部检索接口、开放 API 的 records 结构一致）：
  ```json
  {"query": "年假几天", "retrieval_config": {"search_method": "hybrid", "top_k": 3, "score_threshold_enabled": false,
     "score_threshold": 0.5, "reranking_enable": false, "reranking_model_id": null, "reranking_model_name": null,
     "hybrid_mode": "weighted", "vector_weight": 0.7},
   "rerank_skipped": false, "rerank_skipped_reason": null,
   "records": [
     {"segment_id": 5001, "position": 12, "segment_type": "parent", "content": "父块全文...", "score": 0.82,
      "keywords": [], "document": {"id": 101, "name": "员工手册.pdf"},
      "child_chunks": [{"id": 9001, "position": 2, "content": "子块...", "score": 0.82},
                       {"id": 9002, "position": 3, "content": "子块...", "score": 0.75}]}
   ]}
  ```
  `score` 保留 4 位小数（前端显示 2 位）；通用分段 `child_chunks=[]`。
- 处理：写 `retrieval_record`（保留最近 20 条）；计入召回次数。
- 错误：409303、409506、503301

#### 5.7.2 `GET /api/v1/kb/datasets/{id}/retrieve-records`
- 权限码 `kb:retrieval:test`；ACL 只读；仅返回本人记录，最多 20 条，created_at desc
- 响应 data：`[{"id": 1, "query": "年假几天", "search_method": "hybrid", "retrieval_config": {...}, "result_count": 3, "created_at": "..."}]`

### 5.8 管理视图

`AdminDatasetItem`：
```json
{"id": 10, "name": "产品手册", "owner": {"id": 21, "name": "李四", "username": "lisi", "status": "disabled"},
 "company": {"id": 3, "name": "A公司"}, "dept": {"id": 5, "name": "研发部"},
 "chunk_mode": "general", "doc_count": 35, "segment_count": 800, "child_segment_count": 0,
 "assignment_count": 3, "created_at": "...", "updated_at": "2026-11-01T10:00:00+08:00"}
```

| 接口 | 权限码 | 数据范围 | 说明 |
|---|---|---|---|
| `GET /api/v1/kb/admin/datasets` | kb:admin:list | 过滤 | query：`page`、`page_size`、`keyword`、`owner_keyword`、`owner_id`、`org_id`(按 dept_id 含下级，org_ref)、`owner_status`(`enabled|disabled|deleted`)、`pending_handover`(bool：所有者停用或删除)；sort updated_at desc；分页 `AdminDatasetItem` |
| `GET /api/v1/kb/admin/datasets/{id}` | kb:admin:view | 过滤 | data：`AdminDatasetItem` + `description`、`embedding_model`、`retrieval_config`、`assignments: AssignmentItem[]`；**写操作日志 dataset/admin_view**（target=知识库） |
| `GET /api/v1/kb/admin/datasets/{id}/documents` | kb:admin:view | 过滤 | query 与 5.5 列表相同；分页 `DocumentItem` |
| `GET /api/v1/kb/admin/datasets/{id}/documents/{document_id}/segments` | kb:admin:view | 过滤 | 同 5.6 列表；`page=1` 时写操作日志 dataset/admin_view（摘要含文档名，TQ-05） |
| `POST /api/v1/kb/admin/datasets/{id}/transfer` | kb:admin:transfer | 过滤 | body：`receiver_user_id`、`version`；规则 3.8；日志 dataset/transfer（摘要：原所有者→新所有者、原组织→新组织） |
| `POST /api/v1/kb/admin/datasets/batch-transfer` | kb:admin:transfer | 过滤 | body：`from_user_id`、`receiver_user_id`、`dataset_ids`(可选；缺省 = from_user 名下且在范围内的全部)；data：`{"transferred": 3}`；错误 409321（`data.conflicts`）；每个知识库一条日志 |
| `GET /api/v1/kb/admin/receivers` | kb:admin:transfer | 过滤（user_ref 的 company_id / org_id / id） | query：`keyword`、`page`、`page_size`；只含启用未删除用户；分页 `{"id","username","name","org_name","company_name"}` |
| `GET /api/v1/kb/admin/owners` | kb:admin:transfer | 过滤 | query：`keyword`；返回范围内知识库的所有者（含停用/删除）`[{"id","username","name","status","dataset_count"}]`，最多 50 条 |

### 5.9 内部接口（`require_internal`）

#### 5.9.1 `POST /internal/v1/datasets/{id}/retrieve`
- body：
  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | user_id | int | 是 | 以该用户身份判定 ACL（只读即可） |
  | query | string | 是 | 1~1000（调用方已校验，此处再校验） |
  | overrides | object | 否 | `search_method`、`top_k`、`score_threshold`(传入即视为开启阈值)、`reranking_enable`；未传项用知识库默认 |
  | source | string | 是 | `open_api` / `chat` |
- 处理：`load_auth_context(user_id)`，不可用 → 404000；ACL 无 → 404000；知识库删除 → 404000；模型停用 → 409303；无可用文档 → 返回空 records（不报错）；检索 → 计入召回次数。
- 响应 data：`RetrievalResult` + `"dataset": {"id": 10, "name": "集团制度"}`
- 错误：404000、409303、503301、400001

#### 5.9.2 `POST /internal/v1/access/accessible-datasets`
- body：`{"user_ids": [12, 13], "dataset_ids": [10, 11]}`（user_ids ≤100；dataset_ids 可选，传入时只返回交集）
- data：`{"items": {"12": [10, 11], "13": []}}`（用户不可用 → 空数组）

#### 5.9.3 `POST /internal/v1/datasets/brief`
- body：`{"ids": [10, 11]}`（≤500）；data：`[{"id": 10, "name": "集团制度", "is_deleted": false}]`

#### 5.9.4 `GET /internal/v1/stats/datasets`
- query：`dept_id` 或 `owner_id`（二选一）；data：`{"count": 2}`（未删除知识库）

---

## 6. 权限设计

M2 使用的权限码已在 M1 seed 写入（总体方案第 7 节）。M2 不新增权限点。

- 模型配置：只有拥有 `system:model:*` 的用户（默认超管、集团管理员）；其他人通过 `/models/options` 只看到名称与维度。
- 子公司管理员：管理视图与转移按其数据范围；不能分配他人知识库（分配仅所有者）；不能删除他人知识库。

## 7. 后端任务清单（服务：kb）

### BE-11（kb）服务骨架、迁移、基础客户端 — F-07~F-16 前置
- 文件：`services/kb/main.py`、`worker.py`（空循环骨架）、`.env.example`、`alembic.ini`、`alembic/env.py`、`alembic/versions/0001_init_kb.py`、`app/core/config.py`、`app/models/*.py`、`app/storage/s3.py`、`app/model_clients/{embedding,rerank,errors}.py`、`app/assets/cl100k_base.tiktoken`、`backend/requirements.txt`（追加依赖）
- 内容：第 4 节全部表（pgvector `HALFVEC` 用 `pgvector.sqlalchemy`）；S3 客户端（put/get 流/exists/delete）；Embedding/Rerank 客户端（5.1 协议，超时/重试 2 次（仅超时与 5xx）/错误分类 `ModelTimeout`/`ModelHTTPError`/`ModelBadResponse`）；devctl 识别 kb 与 kb-worker。
- 完成标准：迁移 upgrade/downgrade/upgrade 通过；`python main.py`、`python worker.py` 均可启动与优雅退出；客户端单测（httpx MockTransport）。

### BE-12（kb-worker）只读副本同步 — F-08/F-10/F-20 前置
- 文件：`app/worker/ref_sync.py`、`app/repositories/ref_repo.py`、`worker.py`（注册消费者与对账定时任务）、tests
- 内容：3.9 全部；组织 company_id 变化回写 dataset.company_id。
- 完成标准：单测覆盖乱序事件（旧 updated_at 不覆盖新数据）、对账游标、组织移动回写。

### BE-13（kb）模型配置 — F-07
- 文件：`app/api/v1/models.py`、`app/schemas/model.py`、`app/services/model_service.py`、`app/repositories/model_repo.py`、tests
- 内容：5.1 全部；Fernet 加密凭据，`api_key_hint` 生成；引用检查（embedding：dataset.embedding_model_id；rerank：retrieval_config->>'reranking_model_id'）。
- 完成标准：AC-22~AC-24 单测（测试失败只能存停用、被引用不可删改、选项接口不含地址凭据、无权限 403001）。

### BE-14（kb）知识库 CRUD、我的列表、ACL、统计 — F-08、F-09、F-15
- 文件：`app/api/v1/datasets.py`、`app/schemas/dataset.py`、`app/services/{dataset_service,stats_service}.py`、`app/repositories/{dataset_repo,dataset_acl}.py`、tests
- 内容：3.1 ACL 函数（供其他任务复用）、3.2 统计函数、5.2 全部（含 retrieval-config、删除；自行转移的 HTTP 入口在 BE-23 实现，转移服务函数在 BE-23）。
- 完成标准：AC-25~AC-32、AC-48 单测；ACL 三种分配方式 × 含/不含下级；越权直访 404000，级别不足 403311。

### BE-15（kb）分配 — F-10
- 文件：`app/api/v1/assignments.py`、`app/schemas/assignment.py`、`app/services/assignment_service.py`、`app/repositories/assignment_repo.py`、tests
- 内容：5.3 全部；可分配范围计算（org_ref 子树）。
- 完成标准：AC-33~AC-35 单测；集团本部所有者可分配全集团；新入职成员动态生效（基于 ctx，不落成员快照）。

### BE-16（kb）解析器与分段器（纯函数库） — F-11
- 文件：`app/parsers/*.py`、`app/splitters/{preprocess,tokenizer,general,parent_child}.py`、`app/schemas/process_rule.py`（规则模型与校验）、tests（含样例文件 fixtures）
- 内容：3.5 全部；`validate(path, ext)`、`parse(path, ext) -> str`、`split_document(text, rule, model_max_tokens) -> list[SegmentDraft]`。
- 完成标准：每种格式至少一个样例；加密 PDF、损坏 docx、扫描版 PDF（无文本）判定正确；通用分段每段 ≤ max_tokens、重叠符合设置；父子分段子块 ≤ 子块上限；同输入多次结果完全一致。

### BE-17（kb）上传、预览、提交 — F-11
- 文件：`app/api/v1/uploads.py`、`app/schemas/upload.py`、`app/services/upload_service.py`、`app/repositories/document_repo.py`（创建部分）、tests
- 内容：5.4 全部；进程池执行校验与解析（`concurrent.futures.ProcessPoolExecutor`，在 lifespan 中创建/关闭）；解析文本写 MinIO；提交后 XADD `document.process`。
- 完成标准：AC-36~AC-39、AC-63（预览部分）单测；并发提交两个相同内容文件只有一个成功。

### BE-18（kb-worker）文档处理流水线、超时巡检、上传清理 — F-12
- 文件：`app/worker/{main_loop,tasks_document,sweeper,upload_cleanup}.py`、`app/services/segment_service.py`（`refresh_search_flags`、tsv 生成）、`worker.py`、tests
- 内容：3.6 全部（document.process）；`WORKER_CONCURRENCY` 并发；`upload_cleanup` 每小时删除过期未提交文件（对象 + 行）。
- 完成标准：AC-40、AC-41 单测/集成（mock 模型服务）：状态流转、进度、失败原因、从失败阶段重试、栅栏（删除/重新分段后旧任务不写入）、重复投递不产生重复分段、超时巡检；10MB 文本型 PDF 在 mock 模型下 10 分钟内完成（记录耗时）。

### BE-19（kb）文档管理 — F-13
- 文件：`app/api/v1/documents.py`、`app/schemas/document.py`、`app/services/document_service.py`、`app/repositories/document_repo.py`（查询部分）、tests
- 内容：5.5 全部。
- 完成标准：AC-42~AC-44、AC-66 单测；删除后统计同步；重新分段期间不参与检索；下载对只读用户可用、对管理视图不可用。

### BE-20（kb + kb-worker）分段管理与增量索引 — F-14
- 文件：`app/api/v1/segments.py`、`app/schemas/segment.py`、`app/services/segment_service.py`（编辑部分）、`app/repositories/segment_repo.py`、`app/worker/tasks_segment.py`、tests
- 内容：5.6 全部；3.6 中 `segment.reindex`、`child.reindex`、`parent.regenerate`。
- 完成标准：AC-45~AC-47、AC-65 单测；编辑后索引完成前检索返回旧内容、完成后返回新内容；并发编辑 409511。

### BE-21（kb）检索引擎、召回测试、召回次数、性能验证 — F-15、F-16
- 文件：`app/engine/{vector_store,fulltext,retriever,rerank}.py`、`app/api/v1/retrieval.py`、`app/schemas/retrieval.py`、`app/services/retrieval_service.py`、`app/repositories/record_repo.py`、`app/worker/hit_flush.py`、`tests/unit/...`、`backend/services/kb/scripts/perf_seed.py`（压测数据生成脚本）
- 内容：3.7 全部；5.7 全部；召回次数 Redis 累计 + worker 落库（`RENAME` 到临时 key 后处理，避免丢计数）。
- 完成标准：AC-49~AC-51、AC-64 单测；Rerank 停用降级提示；模型异常返回 503301 而非空结果；**性能**：用 `perf_seed.py` 生成单库 10 万子块/分段（1024 维随机向量）后，向量检索与混合检索（不含模型调用耗时，查询向量预置）单次 P95 ≤ 500ms，结果记录在"实现说明"。不达标须在实现说明中报告并提契约/方案变更。

### BE-22（kb）内部接口 — F-17/F-18 支撑
- 文件：`app/api/internal/{retrieval,access,stats}.py`、`app/schemas/internal.py`、`app/services/internal_service.py`、tests
- 内容：5.9 全部；iam 的 `KB_STATS_ENABLED` 打开后 5.2.8/5.3.9（M1）可联通。
- 完成标准：内部令牌缺失 → 401901；以停用用户/无权限用户检索 → 404000；AC-70 中"移除分配后立即不可检索"。

### BE-23（kb）管理视图与转移 — F-20
- 文件：`app/api/v1/admin.py`（含 5.2.8 自行转移路由放在 `datasets.py`）、`app/schemas/admin.py`、`app/services/{admin_service,transfer_service}.py`、tests
- 内容：3.8、5.8 全部、5.2.8。
- 完成标准：AC-17（管理视图 7 种范围）、AC-18、AC-19、AC-67~AC-69 单测；管理视图访问写日志；管理员的"我的知识库"不受影响。

## 8. 前端任务清单

> 服务文件：`src/services/kb.ts`（全部 kb 接口与类型）。通用组件：`src/components/RetrievalConfigForm.tsx`（FE-15 产出，FE-14 复用）、`src/components/DatasetIcon.tsx`（预置图标）。

### FE-09 模型配置页 — F-07
- 路由 `/system/models`；文件 `src/pages/system/model/index.tsx`、`components/ModelFormModal.tsx`
- 接口：5.1 全部；权限码 `system:model:list|create|update|delete`
- 内容：列表列（名称、类型、模型标识、服务地址、维度、默认、状态、被引用知识库数、操作）；表单内"测试连接"按钮调用 `/models/test`，成功自动回填维度；测试未通过时"状态"只能选停用；模型标识占位提示 `如：bge-m3 / bge-reranker-v2-m3`；凭据输入框编辑时显示 `api_key_hint` 占位、留空表示不修改；被引用模型的地址/标识/维度只读并提示；409301/409302 展示引用知识库名单。
- 完成标准：AC-22~AC-24 前端行为。

### FE-10 我的知识库列表与创建 — F-08、F-09
- 路由 `/kb/datasets`（首页）；文件 `src/pages/kb/list/index.tsx`、`components/{DatasetCard,DatasetTable,CreateDatasetModal}.tsx`
- 接口：5.2.1、5.2.3、5.1 options、5.2.7（列表"..."菜单中的删除）
- 权限码：`kb:dataset:list`、`kb:dataset:create`、`kb:dataset:delete`、`kb:dataset:update`、`kb:dataset:assign`
- 内容：查询栏（名称、我的权限、所有者、分段方式、仅看我拥有的）；卡片（24/页）/列表（20/页）切换（偏好存 localStorage）；卡片展示规则按 F-08（处理中/失败为 0 不显示、父子显示"父块 x / 子块 y"、`chunk_mode=null` 显示"首次上传时选择"）；排序切换；空状态（有新建权限才显示按钮）；创建弹窗（名称、描述、图标、Embedding 模型下拉默认选中默认模型），成功后跳详情并引导上传。
- 完成标准：AC-25~AC-29、AC-66 前端行为。

### FE-11 知识库详情布局与文档页 — F-12、F-13
- 路由 `/kb/datasets/:id/documents`；文件 `src/pages/kb/detail/Layout.tsx`（左侧信息与导航：文档/召回测试/设置/分配，按 my_permission 与权限码显示）、`src/pages/kb/detail/documents/index.tsx`、`components/{ReprocessModal,StatusTag}.tsx`
- 接口：5.2.4、5.5 全部
- 权限码：`kb:document:upload|update|delete|download`、`kb:segment:update`
- 内容：文档 ProTable（列与查询条件按 F-13；分段数列父子显示"父块/子块"；状态列含进度"索引中 60/120"与失败原因 + 重试）；存在非终态文档时每 3 秒调用 `documents/progress` 局部刷新（终态后停止）；批量启用/禁用/删除（二次确认）；重新分段弹窗复用 FE-12 的分段设置表单组件（模式锁定），确认文案"将丢弃全部现有分段及人工修改"；模型停用时页面顶部提示"向量模型已停用，请联系管理员"并隐藏上传。只读用户不显示上传与批量操作。
- 完成标准：AC-40~AC-44 前端行为。

### FE-12 上传文档向导 — F-11
- 路由 `/kb/datasets/:id/documents/upload`；文件 `src/pages/kb/detail/upload/index.tsx`、`components/{FileSelectStep,ChunkSettingStep,ProcessStep,ChunkRuleForm,PreviewPanel}.tsx`
- 接口：5.4 全部、5.5 progress、5.2.4、5.1 options（获取模型 max_input_tokens）
- 权限码：`kb:document:upload`
- 内容：步骤一：多选（>20 提示上限），前端预检扩展名/大小/空文件并标红，其余逐个调用 upload-files（并发 3，显示进度，失败可重试，后端错误逐文件标红）；步骤二：分段方式（知识库已定则锁定）、`ChunkRuleForm`（通用/父子字段、校验规则与 3.5 一致、"使用上次设置"取 `last_process_rule`、"恢复默认"）、预处理开关、预览文件选择 + 预览面板（前 10 段，父子可展开子块；400505/400506 提示且该文件不可提交）；步骤三：提交后逐个显示状态（轮询 progress），"返回文档列表"按钮。`ChunkRuleForm` 导出供 FE-11 复用。
- 完成标准：AC-36~AC-39、AC-63 前端行为。

### FE-13 文档分段页 — F-14
- 路由 `/kb/datasets/:id/documents/:documentId/segments`；文件 `src/pages/kb/detail/segments/index.tsx`、`components/{SegmentList,ParentSegmentItem,SegmentDrawer,ChildChunkEditor}.tsx`；同组件支持 `readonly` 模式供 FE-17 复用
- 接口：5.5 详情、5.6 全部
- 权限码：`kb:segment:update`
- 内容：头部（文件名、分段方式、段数、字符数、新增分段）；列表（序号、字符数、召回次数、已编辑标记、索引状态"索引更新中/索引更新失败"、启用开关、内容默认 3 行可展开、关键词）；父子：父块可展开子块，子块编辑/删除、父块下"新增子块"；抽屉编辑（字数/上限，按 token 上限以后端 400511 为准，前端按字符粗略提示）；父块保存前确认"将按设置重新生成子块，子块的人工修改会丢失"后带 `confirm_regenerate_children=true`；409511 提示"该分段已被他人修改"并刷新；只读模式抽屉只读。
- 完成标准：AC-45~AC-47、AC-65 前端行为。

### FE-14 召回测试页 — F-16
- 路由 `/kb/datasets/:id/recall`；文件 `src/pages/kb/detail/recall/index.tsx`、`components/{RecallResultList,RecallRecordTable}.tsx`
- 接口：5.7 全部、5.2.6（保存为默认）、5.2.4
- 权限码：`kb:retrieval:test`、`kb:dataset:update`（保存为默认，且 my_permission ∈ owner/edit）
- 内容：问题输入（0/500 计数）；检索设置摘要 + "修改"抽屉（复用 `RetrievalConfigForm`，"保存为默认设置"按权限显示）；结果按得分降序（2 位小数）、文档名、序号，点击看详情；父子结果显示父块全文并高亮命中子块（子块内容在父块中 `indexOf` 定位加 `<mark>`，找不到时在下方单独列出）；`rerank_skipped` 时显示提示；无结果引导文案；409303/503301 显示错误而非空结果；无可用文档时测试按钮置灰并提示；测试记录表（点击一键重测）。
- 完成标准：AC-49~AC-51、AC-64 前端行为。

### FE-15 知识库设置页（含转移、删除） — F-09、F-15、F-20
- 路由 `/kb/datasets/:id/settings`；文件 `src/pages/kb/detail/settings/index.tsx`、`src/components/RetrievalConfigForm.tsx`、`components/{TransferModal,DeleteDatasetModal}.tsx`
- 接口：5.2.4、5.2.5、5.2.6、5.2.7、5.2.8、5.3 assignable-users、5.1 options
- 权限码：`kb:dataset:update`、`kb:dataset:delete`、`kb:dataset:transfer`
- 内容：基础信息表单；Embedding 模型（有文档时只读并提示"已有文档，暂不支持更换向量模型"，非所有者只读）；分段方式只读；检索设置（`RetrievalConfigForm`：三种方式、混合模式权重滑块 0~1 步长 0.1 并联动显示关键词权重、Top K、阈值开关+值、Rerank 开关与模型选择，无启用 Rerank 模型时置灰并提示）；危险区仅所有者：转移所有权（接收人搜索 `assignable-users`，提示"原所有者将失去访问权限"）、删除（显示"共有 x 个分配对象将失去访问权限"，输入名称一致才可提交）。只读用户不显示设置导航。
- 完成标准：AC-28、AC-30~AC-32、AC-48 前端行为。

### FE-16 知识库分配页 — F-10
- 路由 `/kb/datasets/:id/assignments`；文件 `src/pages/kb/detail/assignments/index.tsx`、`components/AddAssignmentModal.tsx`
- 接口：5.3 全部、5.2.4
- 权限码：`kb:dataset:assign`
- 内容：所有者信息；分配表（对象、类型、含下级、权限、添加人、时间、失效标记、操作）；所有者可添加/修改/移除，可编辑用户只读查看；添加弹窗：对象类型 → 用户搜索（assignable-users）或组织树（assignable-orgs，类型为部门时只可选部门节点、公司时只可选公司/集团节点）→ 含下级（部门默认是、公司默认否）→ 权限级别（默认只读）。
- 完成标准：AC-33~AC-35 前端行为。

### FE-17 知识库管理（管理视图） — F-20
- 路由 `/system/datasets`、`/system/datasets/:id`；文件 `src/pages/system/dataset/index.tsx`、`detail/index.tsx`、`components/{AdminTransferModal,BatchTransferModal}.tsx`
- 接口：5.8 全部、M1 5.2.2（组织筛选树）
- 权限码：`kb:admin:list`、`kb:admin:view`、`kb:admin:transfer`
- 内容：查询（名称、所有者、所属组织树、所有者状态、待交接快捷开关）；列表列按 PRD；所有者状态标签"已停用/已删除"；单个转移（接收人 `admin/receivers`）；批量转移（选择原所有者 `admin/owners` → 列出其名下知识库（`owner_id` 过滤）→ 选接收人 → 确认，409321 展示冲突名单）；详情页顶部提示"审计查看，操作将被记录"，展示基本信息、分配名单、文档列表、分段（复用 FE-13 只读模式，接口换为 admin 系列），无召回测试、无下载、无任何编辑按钮。
- 完成标准：AC-17、AC-67~AC-69 前端行为。

## 9. 任务依赖与并行

| 阶段 | 后端（kb） | 前端 |
|---|---|---|
| 1 | BE-11 | FE-09、FE-10（对契约开发） |
| 2 | BE-12、BE-13、BE-16（三者文件不重叠，可并行） | FE-11、FE-12、FE-15、FE-16 |
| 3 | BE-14（依赖 BE-11；ACL/统计函数是后续前置） | FE-13、FE-14、FE-17 |
| 4 | BE-15、BE-17、BE-19（依赖 BE-14；BE-17 依赖 BE-16） | 联调 FE-09、FE-10 |
| 5 | BE-18（依赖 BE-16、BE-17）、BE-23（依赖 BE-12、BE-14） | 联调 FE-11、FE-12、FE-15、FE-16、FE-17 |
| 6 | BE-20、BE-21（依赖 BE-18） | 联调 FE-13、FE-14 |
| 7 | BE-22（依赖 BE-21） | — |

- 迁移只在 BE-11 产生；后续任务如需改表必须提契约变更，由 BE-11 的负责人追加迁移（避免多分支迁移冲突）。
- `segment_service.py` 由 BE-18（refresh_search_flags、tsv）创建，BE-20 追加编辑相关函数——两者需串行。
- 前端 FE-12 的 `ChunkRuleForm` 是 FE-11 重新分段弹窗的依赖；FE-15 的 `RetrievalConfigForm` 是 FE-14 的依赖；FE-13 的只读模式是 FE-17 的依赖。

## 10. 风险与兼容性
- 无存量数据；回滚 `alembic downgrade base`（kb schema）。
- 精确检索性能见总体方案风险；BE-21 压测为强制项。
- 进程池解析大文件阻塞预览：单文件 15MB 上限 + 60s 超时 + 池大小限制并发；超时返回 400504"文件解析超时"（复用该码，message 不同）。
- tiktoken 编码文件需提交进仓库（约 1.7MB），首次由开发从官方地址下载后提交。

## 11. 测试要点（M2）
- ACL：所有者/可编辑/只读/未分配 × 每个知识库接口；"可编辑"不能分配/删除/改模型（AC-31）；角色收回 `kb:document:upload` 后被分配"可编辑"仍不能上传（F-10 规则 4）；部门含下级/不含下级、公司含下属/不含下属的成员判定；调岗后立即生效。
- 管理视图：7 种数据范围（AC-17）、并集（AC-18）、超管（AC-19）；管理视图可见不进入我的知识库（AC-26）；管理视图所有写接口、召回测试、下载均被拒（AC-67）。
- 转移：数据范围外接收人、停用接收人、同名冲突、批量冲突整体回滚、转移后原所有者 404000、分配保持（AC-68、AC-69）。
- 上传：21 个文件、类型/大小/空/加密/损坏、重复内容（改名）、并发提交相同内容、文档上限、分段方式锁定、全部删除后可重选分段方式。
- 处理：停止 worker 后提交 → 排队；恢复后继续；处理中删除文档；处理中停用模型 → 失败原因；重试从失败阶段；超时巡检（可将 `PROCESS_TIMEOUT_MINUTES` 调小测试）。
- 检索：三种方式、阈值（AC-49）、Top K 边界、父子聚合与 Top K 按父块计（AC-64）、禁用文档/分段/处理中文档不返回（AC-42、AC-46、AC-60 的召回测试部分）、Rerank 停用降级、模型异常 503301。
- 分段编辑：索引更新中检索旧内容；并发编辑 409511；父块编辑重建子块。
- 统计：AC-25 精确数值；删除文档后统计（AC-43）。
- 回归：M1 登录、菜单（kb 菜单出现）、删除组织时"存在知识库"检查（开启 `KB_STATS_ENABLED`）、用户停用影响提示中的知识库数。

## 12. 变更记录
| 日期 | 变更内容 | 原因 | 影响任务 |
|---|---|---|---|
| 2026-11-11 | 初稿 | 新需求 | 全部 |
| 2026-11-11 | 端口改为专属：kb `PORT=8302`，`S3_ENDPOINT` 默认 `http://127.0.0.1:19000`；`aioboto3` 已在 M1 加入，不再重复追加 | 用户确认：本机多项目共用；BE-01 反馈 | BE-11 |
| 2026-11-11 | 0001 迁移 downgrade 改为逐表 DROP、保留空 schema | 与 iam 一致：版本表在本服务 schema 内 | BE-11 |

## 13. 实现说明（开发补充）
- 后端：
- 前端：
