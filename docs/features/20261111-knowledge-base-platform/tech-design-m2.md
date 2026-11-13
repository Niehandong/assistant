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
| （检索性能相关） | | 见 3.10.7 |

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
- 批量转移：同一事务；任一同名冲突 → 整体拒绝 409321，`data={"conflicts":[{"dataset_id":10,"dataset_name":"产品手册"}]}`（元素为**被转移的**知识库）。单个转移（所有者自行转移、管理员转移）冲突时 `data` 结构相同，`conflicts` 只含一个元素。
- 转移与原所有者并发编辑：编辑类接口均在事务内重新校验 ACL；转移提交后原所有者的后续请求因 ACL 失败被拒（404000）。

### 3.9 只读副本同步（kb-worker）

- `kb.user_ref`、`kb.org_ref` 由 `StreamConsumer(stream:iam.events, group=kb-ref-sync)` 维护，按 `updated_at` 只接受更新的数据。
- 启动时副本为空则全量拉取（`/internal/v1/sync/users|orgs`）；之后每 `REF_RECONCILE_INTERVAL_SECONDS` 用游标增量对账（游标存 Redis `kb:ref:cursor:users|orgs`，每次回退 60 秒重叠）。
- 组织 `company_id` 变化（移动）时：`UPDATE kb.dataset SET company_id = :new WHERE dept_id = :org_id`（F-02 规则 6"知识库所属公司随之重新计算"）。

---

### 3.10 检索性能优化（BE-21b：HNSW 索引 + 数据库调优 + 全文候选裁剪 + 混合并行）

> 背景：BE-21 压测（第 13 节）通用库 10 万分段 P95 向量 674 / 全文 1043 / 混合 1418ms，未达 500ms。用户决定采用"建索引 + 调优"（原方案 A+C+D），**不引入新中间件**，验收目标仍为单次 P95 ≤ 500ms（不含模型调用耗时）。

#### 3.10.1 向量检索：按库规模选择"精确 / HNSW"两条路径

**路径选择**（`engine/vector_store.py` 的 `PgVectorStore.search`）：

```
units = 该知识库检索单元数（通用 = dataset.segment_count；父子 = dataset.child_segment_count）
if units <= VECTOR_EXACT_MAX_ROWS（默认 20000）
   or 该 Embedding 模型的 HNSW 索引不存在/无效
   or 模型维度 > 4000（halfvec HNSW 上限）:
       精确路径
else:
       HNSW 路径；若返回条数 < min(limit, units) → 回退精确路径（记 warning 日志与计数 kb:metrics:hnsw_fallback）
```

- **为什么分两条路**：全平台共享一个按模型划分的 HNSW 索引，小知识库在索引中占比极低（如 2,500 / 500 万），HNSW 遍历遇到的几乎都是其他库的数据，过滤后召回不足；而小库精确扫描本身很快（2 万行 ≈ 60~130ms，经 `dataset_id` 索引只读本库行）。大库占比高，HNSW + 过滤效果好。
- **精确路径**：保持现有 SQL（`WHERE dataset_id=:d AND search_enabled ORDER BY embedding <=> :q LIMIT :n`），依赖 `ix_seg_search`/`ix_child_search`（btree `dataset_id` 部分索引）只读本库行。**生产中禁止对向量做全表并行顺序扫描**（压测中并行 seq scan 更快只是因为测试库只有两个知识库）。

**索引设计**（每个 Embedding 模型一组，运行时创建，见 3.10.2）：

```sql
-- 通用分段
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_seg_hnsw_m{model_id}
  ON kb.segment USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE search_enabled AND embedding_model_id = {model_id};
-- 子块
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_child_hnsw_m{model_id}
  ON kb.child_chunk USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE search_enabled AND embedding_model_id = {model_id};
```

- 为什么按**模型**而不是按维度：谓词 `embedding_model_id = X` 让同维度不同模型的向量不混在同一张图里（不同模型的向量空间不可比），且模型删除时可整体删除索引。模型数量预计个位数，索引数量可控。
- 冗余列 `embedding_model_id`：写入向量时同时写入（= 知识库当时的 Embedding 模型；知识库有文档期间不能换模型，因此与 `dataset.embedding_model_id` 恒一致）；向量为空时为 NULL。
- `m=16, ef_construction=64` 为 pgvector 默认值，构建与内存成本最低；若 3.10.6 召回率不达标，先调查询参数 `ef_search`，仍不达标再把 `ef_construction` 提到 128 重建（参数做成配置 `HNSW_M`、`HNSW_EF_CONSTRUCTION`，仅影响新建索引）。

**HNSW 查询**（同一事务内）：

```sql
SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH, 默认 200（见 3.10.7），且 ≥ limit};
SET LOCAL hnsw.iterative_scan = relaxed_order;
SET LOCAL hnsw.max_scan_tuples = {见下};
WITH c AS MATERIALIZED (
  SELECT id, (embedding::halfvec({dim})) <=> :q AS dist
  FROM kb.segment
  WHERE search_enabled AND embedding_model_id = {model_id} AND dataset_id = :d
  ORDER BY (embedding::halfvec({dim})) <=> :q
  LIMIT :n
)
SELECT id, dist FROM c ORDER BY dist, id;   -- relaxed_order 结果可能轻微乱序，外层重排
```

- `{model_id}`、`{dim}` 必须以**整数字面量**写入 SQL（来自服务端模型表，经 `int()` 校验，非用户输入），保证规划器能证明命中部分索引谓词与表达式（与 BE-21 发现的"裸布尔谓词"问题同理）；`:q`、`:d`、`:n` 仍为绑定参数。继续保留 `SET LOCAL plan_cache_mode = force_custom_plan`。
- `hnsw.max_scan_tuples` = `clamp(ceil(2 × n × total_m / units), 20000, 200000)`，其中 `total_m` 为该模型索引的行数估计（`pg_class.reltuples`，进程内缓存 5 分钟）。即按本库在索引中的占比放大扫描上限，避免过滤后不足。
- 单元测试 / 压测中必须用 `EXPLAIN` 断言大库走 `Index Scan using ix_seg_hnsw_m{id}`、小库走 `ix_seg_search`。

**存储**：`embedding` 列改为 `SET STORAGE MAIN`，并对两表设置 `toast_tuple_target = 8160`，使 1024 维 halfvec（约 2KB）不再被移出行外，减少精确路径的 TOAST 读取（BE-21 估算每行 6.5µs 中含 TOAST 读取）。是否保留以 BE-21b 实测为准：精确路径 2 万行 P95 未改善 ≥20% 则在实现说明中记录并回退为默认存储。

#### 3.10.2 索引的运行时创建与维护（kb-worker）

HNSW 索引依赖模型 ID 与维度，迁移无法预知，因此由 **kb-worker 在运行时创建**（这是对"表结构变更必须走 Alembic"的**登记例外**，仅限本节定义的 `ix_seg_hnsw_m*`、`ix_child_hnsw_m*` 两类索引；见总体方案 13.10）。

| 时机 | 动作 |
|---|---|
| Embedding 模型新建为启用、或状态变为启用、或（未被引用时）修改维度 | kb API 在事务提交后 XADD `stream:kb.tasks` `{"type":"vector.ensure_index","payload":{"model_id":5}}` |
| worker 启动时 + 每 10 分钟（`run_periodic` 单实例） | 对账：所有未删除、维度 ≤ 4000 的 Embedding 模型确保两个索引存在且有效（`pg_index.indisvalid`）；无效索引（`CREATE INDEX CONCURRENTLY` 中断留下的）先 `DROP INDEX CONCURRENTLY` 再重建；维度与索引表达式不一致则重建；已删除模型的索引 `DROP INDEX CONCURRENTLY IF EXISTS` |
| `vector.ensure_index` 任务 | 同对账逻辑，只针对该模型 |

- `CREATE/DROP INDEX CONCURRENTLY` 不能在事务中执行：worker 使用**独立的 autocommit 连接**执行，`SET maintenance_work_mem`、`max_parallel_maintenance_workers` 按 3.10.3；同一模型的建索引用 Redis 锁 `kb:vindex:lock:{model_id}`（TTL 2 小时）防止多 worker 并发。
- 检索侧判断索引是否可用：进程内缓存 `valid_index_models`（查询 `pg_index` + `pg_class`，TTL 60 秒）；不可用时走精确路径，因此索引缺失只影响性能、不影响正确性。
- 新建模型时表内尚无该模型的行，建索引瞬间完成；对已有大量数据的模型补建（如升级上线后首次对账）可能耗时数分钟，期间检索走精确路径。
- 生产 DB 账号：kb 服务账号需为 `kb` schema 下表的 owner（才能建索引），在 BE-29 README 的授权 SQL 中体现。

#### 3.10.3 PostgreSQL 参数

通过 compose 的 `command: ["postgres", "-c", "key=value", ...]` 设置。

| 参数 | 本地开发（docker-compose.yml，与他项目共用 15GB 机器） | 生产（deploy/docker-compose.prod.yml，按 16 核 / 64GB 专用 DB 主机给出，按实际按比例调整） | 说明 |
|---|---|---|---|
| shared_buffers | 1GB | 16GB（内存 25%） | |
| effective_cache_size | 4GB | 48GB | 影响规划器选索引 |
| work_mem | 32MB | 64MB | 排序/哈希；注意 × 并发连接数 |
| maintenance_work_mem | 1GB | 8GB | HNSW 构建尽量在内存中完成（图超出时会显著变慢） |
| max_worker_processes | 16 | 32 | |
| max_parallel_workers | 8 | 16 | |
| max_parallel_workers_per_gather | 4 | 4 | 精确路径/统计查询的并行度 |
| max_parallel_maintenance_workers | 4 | 8 | HNSW 并行构建（pgvector ≥0.6） |
| random_page_cost | 1.1 | 1.1 | SSD |
| effective_io_concurrency | 200 | 200 | |
| jit | off | off | 短查询上 JIT 编译开销大于收益 |
| max_connections | 200 | 400 | 各服务连接池之和 + 余量（kb 每实例池 20，见 3.10.5） |

- 内存容量建议：HNSW 索引常驻内存时延迟最好。按 1024 维 halfvec，每行索引约 2.3KB；全平台 500 万检索单元约 12GB。达到满量级时 DB 主机内存建议 ≥ 64GB（索引 + 热数据可缓存）；本期规模下 16GB 已足够。写入总体方案风险表。

#### 3.10.4 全文检索：大库按常见词裁剪候选

瓶颈：`ts_rank_cd` 对全部命中行逐行计算（约 25µs/行），含高频词的 OR 查询命中数万行。

做法（仅对 `units > FULLTEXT_PRUNE_MIN_ROWS`（默认 20000）的知识库生效；小库保持现状）：

1. **常见词表（离线）**：kb-worker 任务 `fts.common_terms`，对大库执行
   `SELECT word, ndoc FROM ts_stat($$SELECT tsv FROM kb.segment WHERE dataset_id = {id} AND search_enabled$$)`（父子库对 `child_chunk`），取 `ndoc / units > FULLTEXT_COMMON_TERM_RATIO`（默认 0.05）的词写入 Redis 集合 `kb:fts:common:{dataset_id}`（TTL 24 小时）。触发：检索时发现缺失（XADD 任务，本次查询按第 4 步兜底执行）；每 6 小时对 `updated_at` 晚于上次计算的大库刷新。10 万行约数秒，在 worker 中执行不影响在线请求。
2. **查询拆分**：查询词（BE-21 现有分词与停用词过滤之后）分为"稀有词"（不在常见词表中）与"常见词"。
3. **候选**：
   - 有稀有词：候选 = 命中**任一稀有词**的行（`tsv @@ to_tsquery('稀有词1 | 稀有词2 …')`，走 GIN），最多 `FULLTEXT_CANDIDATE_CAP`（默认 3000）行；
   - 全是常见词：候选 = 命中**全部常见词**（AND）的行，最多 3000 行；AND 为空时退化为命中"最稀有的那个常见词"的行，最多 3000 行。
4. **打分**：只对候选行用**完整查询**（全部词 OR）计算 `ts_rank_cd(tsv, q_full, 32)`，排序取前 n。候选超过上限时截断（无序截断，记计数 `kb:metrics:fts_cap_hit`，在压测中观察）；常见词表缺失时直接使用"完整 OR 查询 + 上限 3000"兜底。

对排序质量的影响：
- 被排除的只有"只命中常见词、不含任何稀有词"的行。在 `ts_rank_cd`（覆盖密度）下这类行本就得分偏低，与 BM25 中常见词 IDF 接近 0 的效果一致，对前 Top K 影响很小。
- 全常见词查询改为 AND 语义，结果更精确、可能更少；为空时有兜底。
- 得分数值本身不变（仍是同一个 `ts_rank_cd`），阈值语义不变。
- 3.10.6 用"裁剪前后 Top10 重合度"量化影响。

#### 3.10.5 混合检索：两路并行 + 补算并行

- 向量路与全文路使用**两个独立的 `AsyncSession`（两条连接）**通过 `asyncio.gather` 并发执行；补算阶段（为并集中缺另一路得分的 ID 按 ID 计算向量距离 / `ts_rank_cd`，各 ≤ 200 行）同样两路并发。耗时 ≈ max(向量, 全文) + max(两项补算)。
- 两个会话各自只读事务、各自 `SET LOCAL`（HNSW 参数只在向量会话设置）；两次快照可能相差毫秒级，补算时仍带 `search_enabled` 条件；若某行在两次快照之间被禁用，补算查不到它，该路得分按 0 计，与 BE-21 中"缺失得分按 0"的现有规则一致；最终组装结果时再按 `search_enabled` 过滤一次，保证不返回已禁用内容。
- 连接池：kb `DB_POOL_SIZE` 默认由 10 调为 20（`max_overflow` 10）；混合检索每请求最多占 2 条连接。`engine/retriever.py` 新增 `session_factory` 参数用于取第二个会话（`retrieve()` 签名向后兼容：未传时退化为串行，供单测使用）。
- 父子库的混合检索同样适用（子块表）。

#### 3.10.6 压测与验收（沿用 `scripts/perf_seed.py`，扩展 `seed --scenario`）

数据场景：

| 场景 | 内容 |
|---|---|
| S1 单大库 | 通用分段库 10 万 + 父子分段库 10 万子块（与 BE-21 相同，同一模型） |
| S2 多租户 | 在 S1 基础上，同一模型再加 4 个 10 万单元的大库 + 20 个 2,000 单元的小库（模型索引共约 60 万行），另加一个不同模型（不同维度，如 768）的 10 万库 |
| 向量数据 | 除随机向量外，增加"聚类向量"：以 200 个随机中心加高斯噪声生成，查询向量取已有向量加小噪声（更接近真实分布）；随机向量是 HNSW 最坏情况，两种都测 |

验收指标（单连接串行，预热后每组 ≥ 60 次，不含模型调用）：

| 指标 | 门槛 |
|---|---|
| S1、S2 大库：向量 / 全文 / 混合 单次 P95 | ≤ 500ms（三者均须达标，通用与父子均须达标） |
| S2 小库（走精确路径）：三种方式 P95 | ≤ 150ms |
| 4 并发 P95 | 记录（参考值 ≤ 700ms，不作为门槛） |
| HNSW 召回率：与精确检索对比 recall@10（S1、S2 大库，各 100 条查询向量，聚类与随机两组） | 聚类组均值 ≥ 0.95 且单条最低 ≥ 0.80；随机组均值 ≥ 0.90（记录） |
| HNSW 回退精确路径比例（S2） | ≤ 1% |
| 全文裁剪质量：17 条查询裁剪前后 Top10 重合度 | 均值 ≥ 0.80；裁剪后结果条数 ≥ min(Top K, 裁剪前条数) |
| 候选上限命中（`fts_cap_hit`） | 记录 |
| 路径正确性 | EXPLAIN 断言：大库走 `ix_*_hnsw_m{id}`，小库走 `ix_*_search` |
| 建索引 | 记录 10 万 / 60 万行 HNSW 构建耗时与索引大小；有索引时 worker 索引阶段写入 1 万单元的耗时相对无索引的增幅（记录，> 2 倍需在实现说明中提出） |

结果写入第 13 节"BE-21b 实现说明"。任一门槛不达标：先按 3.10.1 调 `HNSW_EF_SEARCH`（100→200）、`ef_construction`（64→128）、`VECTOR_EXACT_MAX_ROWS`、`FULLTEXT_CANDIDATE_CAP` 等参数复测，仍不达标则报告并提方案变更（届时再评估 Qdrant）。

#### 3.10.7 新增配置（kb，`app/core/config.py` 与 `.env.example`）

| 配置项 | 默认 | 说明 |
|---|---|---|
| VECTOR_EXACT_MAX_ROWS | 20000 | ≤ 该值走精确路径 |
| HNSW_EF_SEARCH | 200（BE-21b 压测由 100 调整） | 查询时 `hnsw.ef_search`（实际取 max(该值, limit)，上限 1000） |
| HNSW_MAX_SCAN_TUPLES_MIN / MAX | 20000 / 200000 | iterative scan 扫描上限的夹取范围 |
| HNSW_M / HNSW_EF_CONSTRUCTION | 16 / 128（BE-21b 压测由 64 调整） | 仅影响新建索引 |
| VECTOR_INDEX_RECONCILE_SECONDS | 600 | 索引对账周期 |
| FULLTEXT_PRUNE_MIN_ROWS | 20000 | 超过才裁剪 |
| FULLTEXT_COMMON_TERM_RATIO | 0.15（BE-21b 压测由 0.05 调整） | 常见词判定比例 |
| FULLTEXT_CANDIDATE_CAP | 10000（BE-21b 压测由 3000 调整） | 打分候选上限 |
| FULLTEXT_COMMON_TERMS_REFRESH_SECONDS | 21600 | 常见词表刷新周期 |
| DB_POOL_SIZE | 20（kb 覆盖共享默认 10） | 混合检索双连接 |

#### 3.10.8 迁移 `0002_vector_index_support`

upgrade：
1. `ALTER TABLE kb.segment ADD COLUMN embedding_model_id BIGINT NULL`；`kb.child_chunk` 同样。
2. `ALTER TABLE ... ALTER COLUMN embedding SET STORAGE MAIN`；`ALTER TABLE ... SET (toast_tuple_target = 8160)`（两表）。
3. 回填（分批，每批 5000 行，按 id 区间循环，单批一个事务；使用 Alembic `op.get_context().autocommit_block()`）：
   `UPDATE kb.segment s SET embedding_model_id = d.embedding_model_id, embedding = s.embedding FROM kb.dataset d WHERE s.dataset_id = d.id AND s.embedding IS NOT NULL AND s.embedding_model_id IS NULL AND s.id BETWEEN :a AND :b`
   （`embedding = s.embedding` 让存量行按新存储策略重写；`child_chunk` 同理）。本期仅开发/测试库有数据，回填很快；生产首次部署时表为空。
4. 不在迁移中创建 HNSW 索引（由 worker 对账创建，3.10.2）。
5. 不新增扩展。

downgrade：
1. 查询 `pg_indexes` 中 `schemaname='kb' AND (indexname LIKE 'ix_seg_hnsw_m%' OR indexname LIKE 'ix_child_hnsw_m%')`，逐个 `DROP INDEX CONCURRENTLY IF EXISTS`（autocommit 块）。
2. 两表 `RESET (toast_tuple_target)`；`embedding` 恢复为 halfvec 类型默认存储（迁移中读取 `pg_type.typstorage` 得到默认值，不硬编码）。
3. 删除两表 `embedding_model_id` 列。

代码配套（BE-21b 一并修改）：worker 索引阶段（`tasks_document.py`）与分段重建索引（`tasks_segment.py`）写 `embedding` 时同步写 `embedding_model_id`；`refresh_search_flags` 不变；删除/禁用不涉及该列。

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
| embedding | HALFVEC | NULL | | 仅 general；不定维度；`STORAGE MAIN`（0002） |
| embedding_model_id | BIGINT | NULL | | 写入向量时同步写入的模型 ID（0002，HNSW 部分索引谓词用，3.10.1） |
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
| embedding | HALFVEC | NULL | | `STORAGE MAIN`（0002） |
| embedding_model_id | BIGINT | NULL | | 同 segment（0002） |
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
| 409321 | 接收人已有同名知识库，请先改名 | `data={"conflicts":[{"dataset_id":int,"dataset_name":string}]}`，单个与批量转移结构一致 |
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
- 响应：`DatasetDetail`（最新详情，含新 `version`）
- 操作日志 dataset/retrieval_config

#### 5.2.7 `DELETE /api/v1/kb/datasets/{id}`
- 权限码 `kb:dataset:delete`；ACL 所有者（超管放行）
- body（JSON 请求体，DELETE 带 body）：`confirm_name: string`（≠名称 → 400311）；缺少请求体 → 400001
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
 "assignment_count": 3, "created_at": "...", "updated_at": "2026-11-01T10:00:00+08:00", "version": 7}
```

| 接口 | 权限码 | 数据范围 | 说明 |
|---|---|---|---|
| `GET /api/v1/kb/admin/datasets` | kb:admin:list | 过滤 | query：`page`、`page_size`、`keyword`、`owner_keyword`、`owner_id`、`org_id`(按 dept_id 含下级，org_ref)、`owner_status`(`enabled|disabled|deleted`)、`pending_handover`(bool：所有者停用或删除)；sort updated_at desc；分页 `AdminDatasetItem` |
| `GET /api/v1/kb/admin/datasets/{id}` | kb:admin:view | 过滤 | query：`audit_entry`(bool，默认 false)；data：`AdminDatasetItem`（含 `version`）+ `description`、`embedding_model`、`retrieval_config`、`assignments: AssignmentItem[]`；按 5.8.1 规则写操作日志 dataset/admin_view（target=知识库，summary `{}`） |
| `GET /api/v1/kb/admin/datasets/{id}/documents` | kb:admin:view | 过滤 | query 与 5.5 列表相同；分页 `DocumentItem`；不记日志 |
| `GET /api/v1/kb/admin/datasets/{id}/documents/{document_id}` | kb:admin:view | 过滤 | 与 5.5 文档详情相同（`DocumentItem` + `process_rule`），供只读分段页头部展示；不记日志 |
| `GET /api/v1/kb/admin/datasets/{id}/documents/{document_id}/segments` | kb:admin:view | 过滤 | 同 5.6 列表 + query `audit_entry`(bool，默认 false)；按 5.8.1 规则写操作日志 dataset/admin_view（target=知识库，summary `{"document_id":..,"document_name":".."}`）。**不再以 `page=1` 作为记录条件** |
| `POST /api/v1/kb/admin/datasets/{id}/transfer` | kb:admin:transfer | 过滤 | body：`receiver_user_id`、`version`；规则 3.8；日志 dataset/transfer（摘要：原所有者→新所有者、原组织→新组织） |
| `POST /api/v1/kb/admin/datasets/batch-transfer` | kb:admin:transfer | 过滤 | body：`from_user_id`、`receiver_user_id`、`dataset_ids`(可选；缺省 = from_user 名下且在范围内的全部)；data：`{"transferred": 3}`；错误 409321（`data.conflicts`）；每个知识库一条日志 |
| `GET /api/v1/kb/admin/receivers` | kb:admin:transfer | 过滤（user_ref 的 company_id / org_id / id） | query：`keyword`、`page`、`page_size`；只含启用未删除用户；分页 `{"id","username","name","org_name","company_name"}` |
| `GET /api/v1/kb/admin/owners` | kb:admin:transfer | 过滤 | query：`keyword`；返回范围内知识库的所有者（含停用/删除）`[{"id","username","name","status","dataset_count"}]`，最多 50 条 |

#### 5.8.1 管理视图审计日志记录规则（TQ-05 细化）

记录对象：①进入知识库审计详情（`GET admin/datasets/{id}`）；②打开某文档的分段列表（`GET admin/.../segments`）。文档列表、文档详情、翻页、改搜索条件均不单独记录。

后端判定（满足任一即记 1 条）：
1. 请求带 `audit_entry=true`：前端在**用户主动进入**时带上——进入审计详情页的那次详情请求；点击某文档"查看分段"打开列表的那次请求。翻页、改条件、重新聚焦刷新不带。
2. 兜底去重窗口：同一操作人对同一对象（知识库详情：`dataset_id`；分段列表：`document_id`）在 30 分钟内没有记录过（Redis `SET kb:audit:{user_id}:{ds|doc}:{id} 1 NX EX 1800` 成功）。带 `audit_entry=true` 记录时同样刷新该 key。

这样：用户每次主动进入都留痕；前端重取/翻页不会重复记录；即使请求方不带 `audit_entry`，首次访问也必然留痕（审计不可被客户端绕过）。

管理员转移的并发控制：`AdminDatasetItem` 含 `version`，单个转移必须携带（不一致 409001）；批量转移不带 version，在事务内对所选知识库 `SELECT ... FOR UPDATE` 后统一校验（转移以提交时的状态为准）。

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

### BE-21b（kb + kb-worker）检索性能优化 — F-15、F-16、F-18 非功能
- 文件：`alembic/versions/0002_vector_index_support.py`、`app/models/{segment,child_chunk}.py`、`app/engine/{vector_store,fulltext,retriever}.py`、`app/worker/{vector_index,fts_stats}.py`（新增）、`app/worker/{tasks_document,tasks_segment}.py`（写 `embedding_model_id`）、`app/services/model_service.py`（启用/新建/改维度后发 `vector.ensure_index`）、`worker.py`（注册对账与常见词任务）、`app/core/config.py`、`.env.example`、`scripts/perf_seed.py`（场景 S2、聚类向量、recall 与重合度统计）、`docker-compose.yml`（3.10.3 本地参数）、tests
- 内容：3.10 全部（3.10.1 两路径向量检索与 HNSW 查询、3.10.2 运行时索引维护、3.10.3 本地 PG 参数（生产参数由 BE-29 落地）、3.10.4 全文裁剪、3.10.5 混合并行、3.10.7 配置、3.10.8 迁移）。
- 完成标准：迁移 upgrade/downgrade/upgrade 通过；现有 BE-21 单测全部通过（检索结果结构与语义不变）；新增单测：路径选择（阈值、索引无效、维度 > 4000、HNSW 不足回退）、EXPLAIN 断言索引命中、对账重建无效索引、全文常见词拆分与兜底、混合并行与串行结果一致；**3.10.6 全部门槛达标**，结果写入第 13 节。

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
| 7 | BE-22（依赖 BE-21）、BE-21b（依赖 BE-21；与 BE-22 文件基本不重叠，可并行，`retriever.py` 签名向后兼容） | — |

- 迁移只在 BE-11 产生；后续任务如需改表必须提契约变更，由 BE-11 的负责人追加迁移（避免多分支迁移冲突）。
- `segment_service.py` 由 BE-18（refresh_search_flags、tsv）创建，BE-20 追加编辑相关函数——两者需串行。
- 前端 FE-12 的 `ChunkRuleForm` 是 FE-11 重新分段弹窗的依赖；FE-15 的 `RetrievalConfigForm` 是 FE-14 的依赖；FE-13 的只读模式是 FE-17 的依赖。

## 10. 风险与兼容性
- 无存量数据；回滚 `alembic downgrade base`（kb schema）。
- 精确检索性能见总体方案风险；BE-21 压测未达标，按 3.10 / BE-21b 优化，3.10.6 为强制验收。
- HNSW 为近似检索：以召回率门槛约束；小库与索引不可用时自动走精确路径，正确性不依赖索引。
- 运行时建索引为规范登记例外（总体 13.10）；`CREATE INDEX CONCURRENTLY` 失败会留下无效索引，由对账自动清理重建。
- 全文裁剪对大库的排序有轻微影响（3.10.4），以 Top10 重合度门槛约束。
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
| 2026-11-11 | 5.8 `AdminDatasetItem`/详情增加 `version`（单个管理员转移必须携带；批量转移用行锁）；新增管理视图文档详情接口；409321 `data.conflicts` 定义为 `[{dataset_id, dataset_name}]`（单个/批量一致）；新增 5.8.1 审计日志规则：`audit_entry=true` 或 30 分钟去重窗口内首次访问时记录，不再以 `page=1` 判定 | FE-13/14/17 契约补充 | BE-23、FE-17 |
| 2026-11-12 | 新增 3.10 检索性能优化与任务 BE-21b：按 Embedding 模型的 HNSW 部分索引（运行时由 worker 创建/对账）+ 小库精确路径、PG 参数、全文按常见词裁剪候选、混合两路并行；segment/child_chunk 增加 `embedding_model_id`、embedding `STORAGE MAIN`（迁移 0002）；kb `DB_POOL_SIZE` 20；新增配置见 3.10.7 | BE-21 压测不达标，用户决定采用建索引 + 调优（A+C+D） | BE-21b（新增）、BE-29（生产 PG 参数、DB 账号为表 owner） |
| 2026-11-12 | BE-21b 验收结论：硬门槛全部达标；调参为 `HNSW_EF_SEARCH=200`、`HNSW_EF_CONSTRUCTION=128`、`FULLTEXT_COMMON_TERM_RATIO=0.15`、`FULLTEXT_CANDIDATE_CAP=10000`。均匀随机向量组 recall@10≈0.02 **接受并仅记录**（高维均匀随机向量无稳定近邻，属数据特性；聚类组≈真实 embedding 分布已达标）。有 HNSW 时写入放大约 14.6 倍、混合检索 P95 余量小，列为 BE-29 在 SSD 环境复测项 | 主会话按用户授权自主决策（推荐方案） | BE-21b、BE-29 |
| 2026-11-12 | M2 QA 第 1 轮决策：①BUG-16 向导分段长度默认 `min(1024, Embedding 模型 max_input_tokens)`（子块同理）；②kb-worker 启动校验 `TASK_CLAIM_IDLE_SECONDS` > 文档处理锁 TTL；③公司分配"不含下属"维持现设计（该公司全员含其部门，仅排除子公司）；④解析文本键 `parsed/{upload_file_id}.txt` 仅含自增 ID，重建数据库/备份恢复时须同时清理对象存储桶——记为已知限制，写入部署说明 | 主会话按用户授权自主决策 | BUG-16、kb-worker、BE-29 |
| 2026-11-11 | 0001 迁移 downgrade 改为逐表 DROP、保留空 schema | 与 iam 一致：版本表在本服务 schema 内 | BE-11 |
| 2026-11-11 | 5.2.6 补充响应体为最新 `DatasetDetail`；5.2.7 明确 DELETE 请求体 | BE-14 确认前端契约 | BE-14、FE-15 |

## 13. 实现说明（开发补充）
- 后端：
  - **BE-11 已完成**。文件：`backend/services/kb/{main.py,worker.py,.env.example,alembic.ini,alembic/,app/core/{config,constants}.py,app/models/*,app/storage/s3.py,app/model_clients/{base,embedding,rerank,errors}.py,app/assets/cl100k_base.tiktoken}`、`backend/requirements.txt`。
  - 依赖（固定版本，已装入 .venv）：pgvector 0.5.1、jieba 0.42.1、tiktoken 0.14.0、pypdf 7.0.1、python-docx 1.2.0、openpyxl 3.1.5、xlrd 2.0.2、python-pptx 1.0.2、beautifulsoup4 4.15.0、lxml 6.1.3、charset-normalizer 3.5.2（传递依赖 requests/Pillow/XlsxWriter/regex 等未单独固定）。
  - tiktoken 编码文件：已从官方地址下载，1,681,126 字节，sha256 `223921b7...65b2a7`（与 tiktoken 内置期望哈希一致）；已验证可用 `tiktoken.load.load_tiktoken_bpe(path, expected_hash=...)` + 自建 `tiktoken.Encoding("cl100k_base", pat_str=..., ...)` 离线加载（BE-16 的 `tokenizer.py` 据此实现；pat_str 取 cl100k 官方正则）。`Settings.tiktoken_file` 给出路径。
  - 迁移 `0001_init_kb`：建 schema `kb`、`vector` 扩展与第 4 节全部 11 张表（`alembic_version` 在 kb schema）；`alembic check` 无差异；downgrade 为逐表 DROP（保留空 schema、不删扩展）。已在 `kbp_test` 验证 upgrade → downgrade base → upgrade → downgrade -1 → upgrade；开发库只做了 upgrade。`devctl.py migrate` 依次执行 iam（+seed）→ kb。
  - 模型实现要点：`embedding` / `tsv` 为不定维度 `HALFVEC()` / `TSVECTOR`，asyncpg 下可直接以 Python list 读写、用 `<=>` 查询；`user_ref`/`org_ref` 主键为 iam 的 ID（非自增），含基类时间/审计字段与 `source_updated_at`；`dataset.retrieval_config` 带 JSONB 服务端默认值（与 `constants.DEFAULT_RETRIEVAL_CONFIG` 一致）。
  - 配置：`MODEL_SECRET_KEY` 默认为固定开发 Fernet key；`validate_for_runtime` 在 `APP_ENV` 非 dev/test 时拒绝使用默认值，并且任何环境下都校验其为合法 Fernet key。`.env.example` 已含全部配置项。
  - 模型客户端（`EmbeddingClient.embed`、`RerankClient.rerank`）：超时用 `MODEL_HTTP_TIMEOUT_SECONDS`（调用方传入）；仅超时与 5xx 重试（最多 2 次，退避 0.5s×n），4xx、连接失败不重试；异常 `ModelTimeout` / `ModelHTTPError(status_code|None)` / `ModelBadResponse`；错误简述不含凭据与请求内容。测试连接的 `success=false` 映射由 BE-13 完成。
  - S3（`S3Storage`）：`put_bytes/get_bytes/iter_bytes(流式)/exists/delete(幂等)/ping`；不存在抛 `ObjectNotFound`。注意 aiobotocore 2.25 下 `async with resp["Body"]` 得到的是原始 aiohttp 响应，需直接用 `body.read()/iter_chunks()` 并 `close()`。`/readyz` 仍只检查 DB/Redis（按总体方案），未纳入 S3。
  - `worker.py` 骨架：`register(name, factory)` 供 BE-12/BE-18 注册后台协程；SIGINT/SIGTERM 优雅退出（取消后台任务、关闭 Redis/DB）。`main.py` 已挂 `/api/v1`、`/internal/v1` 空路由。
  - 测试（`services/kb/tests/unit`，38 个，需在 kb 目录内运行 pytest；同一 pytest 会话不能同时收集 iam 与 kb，因为包名 `app` 冲突）：配置校验、客户端（MockTransport）、S3（真实 MinIO 桶 kbp-test）、迁移双向与约束（部分唯一索引、HALFVEC 往返、tsquery）、app 健康检查与 /docs、worker 启停。BE-11 无业务接口，故无 403 用例。
  - **BE-12 已完成**（kb-worker 只读副本同步）。文件：`app/worker/ref_sync.py`、`app/repositories/ref_repo.py`、`app/schemas/ref_sync.py`、`worker.py`（`register_defaults` 注册 `ref-sync-consumer`、`ref-reconcile` 两个后台任务；`run()` 增加 `runtime.configure/shutdown` 以使用 iam 内部客户端）。
    - 写入统一经 `ref_repo.upsert_users/upsert_orgs`：`INSERT ... ON CONFLICT (id) DO UPDATE ... WHERE source_updated_at IS NULL OR source_updated_at < excluded.source_updated_at`，旧事件/乱序/同时间重复事件都不会覆盖；同一批次内同 id 只保留最新一条；事件与拉取共用，返回实际写入的 id。
    - 组织移动回写：每次实际写入组织后，用一条 `UPDATE kb.dataset SET company_id = org_ref.company_id WHERE dept_id = org_ref.id AND company_id <> org_ref.company_id AND NOT is_deleted`（集合式、幂等；旧事件因未写入不会触发回写）。
    - 事件：`StreamConsumer(stream:iam.events, group=kb-ref-sync)`；`user.upserted`/`org.upserted` 载荷即 UserRef/OrgRef；未知类型忽略；载荷不合法抛异常，由消费者重试后进 `stream:dead`。`run_event_consumer` 被取消时先 `stop()` 再等待最多 3 秒（避免遗留阻塞读取任务）。
    - 启动：`initial_sync()` 在副本为空时从头全量拉取（先 orgs 后 users，iam 暂不可用则 5 秒重试直到成功），之后 `run_periodic("kb_ref_reconcile", REF_RECONCILE_INTERVAL_SECONDS)` 增量对账。游标 Redis `kb:ref:cursor:users|orgs` 存已见到的最大 `(updated_at, id)`；增量时 `updated_after = 游标 - 60s, after_id = 0`；游标缺失/损坏则全量。首次不传 `updated_after`，翻页时把上一页 `next` 原样传回；每页应用后推进游标，中途失败可续。
    - 已知限制：iam 为逻辑删除，副本不会因物理删除而清理；iam 侧若物理删除用户，kb 副本会保留旧行。
  - **BE-13 已完成**（模型配置 F-07）。文件：`app/api/v1/models.py`、`app/schemas/model.py`、`app/services/model_service.py`、`app/repositories/model_repo.py`、`app/core/security.py`；`app/model_clients/base.py` 新增 `max_retries` 参数（默认 2，测试连接传 0）。7 个接口与权限码完全按 5.1，`/models/test` 与 `/models/options` 声明在 `/{id}` 之前。
    - **凭据**：Fernet（`MODEL_SECRET_KEY`）加密入库；列表/详情/选项/操作日志均不含明文或密文，只返回 `api_key_hint`（≥12 位显示 `前3位****后4位`，更短只显示 `****`）。`api_key` 语义：创建时空串视为无；更新时不传/null 不改、`""` 清空。操作日志摘要只含字段快照与 `key_changed` 标志（注意共享库脱敏正则会把含 `api_key`/`secret`/`credential` 的键名替换为 `******`，所以不要用这些键名）。
    - **测试连接时限**：单次调用不重试，单次超时 `min(MODEL_HTTP_TIMEOUT_SECONDS, 50)`，外层总时限 `TEST_TOTAL_TIMEOUT_SECONDS = 55` 秒（`asyncio.timeout`），因此 `POST /models/test` 与"启用时的同步测试"都在 60 秒内返回（有单测：挂起的服务在总时限到达后返回 `success=false`）。联网前先 `rollback` 结束读事务，不占用数据库连接；写入前重新加锁并校验 version。
    - **失败语义**：`POST /models/test` 按契约不抛业务错误，失败以 `success=false` + 可展示的 `error_message`（如"模型服务返回错误（HTTP 401：invalid api key）"、"连接模型服务超时"、"无法连接模型服务，请检查服务地址与网络"、"模型服务响应不符合协议：…"）返回。创建/编辑/启用时的同步测试失败才返回 **400301**，`data={"error_message": "<同上原因>"}`；测试得到的维度与填写不一致同样 400301，原因含两个维度值。
    - 其他规则：`PUT /models/{id}` 的 body 含可选 `status`/`is_default`（与前端契约一致）；启用或修改连接信息/密钥且结果为启用时才重测；被停用的默认模型自动取消默认；`is_default=true` 要求启用（400303）并在同事务取消同类型其他默认；embedding 模型被知识库引用时改 `base_url/model_name/dimension` → 409301，删除（含 rerank 被 `retrieval_config.reranking_model_id` 引用）→ 409302，`data={"datasets":[最多10个名称],"total":n}`；名称唯一 409304（含并发下的唯一索引冲突）；version 不符 409001；不存在 404000；`dataset_count` 批量统计无 N+1；删除为逻辑删除并释放名称与默认位。
    - 安全说明：`base_url` 可指向内网地址（部署形态要求如此，如 `http://10.0.0.5:9997/v1`），因此测试连接/保存仅对拥有 `system:model:*` 权限的管理员开放。
  - 测试（kb 目录内运行，共 122 个含 BE-16 的用例）：BE-12 `tests/unit/test_ref_sync.py`（13）、BE-13 `tests/unit/test_models_api.py`（23：权限 401/403、加密与不回显、创建/更新/状态/默认/删除全部规则、引用锁定、分页过滤与 LIKE 转义、测试连接超时/重试/错误文案、操作日志无凭据）；API 测试通过 `tests/unit/helpers.py` 的 ASGI 包装按请求头注入 AuthContext（其余鉴权逻辑真实执行）。
  - 联调验证：iam + kb + kb-worker 在开发库启动，worker 自动全量同步 `kb.org_ref`(8)/`kb.user_ref`(5) 并写入游标，随后对账；用本地假模型服务 curl 验证 test（成功/401/不可达，均 <0.1 秒）、创建（400301 与成功）、列表、选项、删除。
- 前端：
  - **FE-09、FE-10 已完成**（仅对契约开发 + mock 单测，未联调；类型手写在 `src/services/types/kb-contract.ts`，后端 OpenAPI 就绪后以 `pnpm gen:api` 生成为准并核对差异）。
  - 文件：`src/services/kb.ts`（`modelApi`、`datasetApi`，表单类接口 `skipErrorToast` 由页面处理）；`src/pages/system/model/{index.tsx,logic.ts,components/ModelFormModal.tsx}`；`src/pages/kb/list/{index.tsx,logic.ts,components/{DatasetCard,DatasetTable,DatasetActionsMenu,CreateDatasetModal,DeleteDatasetModal}.tsx}`；通用：`src/components/DatasetIcon.tsx` + `datasetIcons.ts`（12 个预置图标，key 存库，未知 key 回退 `book`）。
  - 路由：`/system/models`（`system:model:list`）、`/kb/datasets`（`kb:dataset:list`）；`/kb/datasets/*` 仍为占位，供 FE-11~FE-16 逐步替换（精确路径优先于通配）。
  - 模型配置：连接信息指纹（类型+地址+标识+凭据）变化即作废测试结果，已选“启用”自动退回“停用”；“启用”仅在本次测试通过、或编辑已启用且连接信息未变时可选（服务端保存时仍复测）；测试成功自动回填维度（被引用模型不覆盖）；被引用 embedding 模型地址/标识/维度只读；凭据留空=不传、勾选“清空已保存的凭据”=`""`；409301/409302 用弹窗展示引用知识库名单，400301 在表单内显示原因；409304/400302 落到对应字段。测试请求超时 60s（高于默认 30s）。
  - 知识库列表：筛选/排序/分页由页面统一管理，一次 `useQuery` 同时供卡片与列表视图；视图偏好存 `localStorage('kb.dataset.viewMode')`，卡片 24/页、列表 20/页；处理中/失败为 0 不显示，父子显示“父块 x / 子块 y”，`chunk_mode=null` 显示“首次上传时选择”；向量模型停用显示“向量模型已停用，请联系管理员”标签。“...”菜单：设置（update 且非只读）、分配（assign 且所有者）、删除（delete 且所有者）；设置/分配跳转 `/kb/datasets/:id/settings|assignments`（FE-15/16 落地前为占位）。
  - 删除：`DeleteDatasetModal` 打开时调 `GET /datasets/{id}` 取 `assignment_count` 显示“共有 x 个分配对象将失去访问权限”（列表项不含该字段，故多一次详情请求；失败时降级文案），名称与输入完全一致才可提交，`confirm_name` 随 DELETE 请求体发送（axios `data`）。
  - 创建：Embedding 下拉来自 `/models/options?model_type=embedding`，默认选中 `is_default`；无可用模型时提示并禁用提交；成功后跳 `/kb/datasets/:id/documents`，`location.state.guideUpload=true`（FE-11 据此引导上传）。409311 显示在名称字段。
  - 单测：`logic.test.ts`（模型表单/测试状态/请求体、列表统计与筛选/视图偏好/权限）、`ModelFormModal.test.tsx`、`pages/kb/components/DeleteDatasetModal.test.tsx`、`kb/list/index.test.tsx`。
  - **FE-11、FE-12、FE-15、FE-16 已完成**（对契约开发 + mock 单测，未联调；用 Playwright 路由 mock 渲染自查了模型/列表/文档/设置页）。类型与接口追加在 `kb-contract.ts`、`services/kb.ts`（`uploadApi`、`documentApi`、`assignmentApi`、`datasetApi.update/updateRetrievalConfig/transfer`、`parseFilename`）。
  - 路由：`/kb/datasets/:id/*` 由 `pages/kb/detail/routes.tsx` 内嵌子路由（外层 `kb:dataset:list`）：`documents`、`documents/upload`、`documents/:documentId/segments`（FE-13 占位）、`recall`（FE-14 占位）、`settings`、`assignments`。布局 `detail/Layout.tsx` 加载 `GET /datasets/{id}`（404000 显示“不存在或无权访问”），通过 Outlet context 提供 `useDataset()`；详情缓存键 `['kb-dataset-detail', id]`，保存设置后 `setQueryData`/invalidate。导航规则见 `detail/navItems.ts`：召回测试需 `kb:retrieval:test`；设置需 `kb:dataset:update` 且非只读；分配需 `kb:dataset:list` 且非只读（可编辑用户只读查看）。
  - FE-11 文档页：QueryFilter + ProTable（受控 `dataSource`，筛选/排序/分页由页面状态驱动，不用 ProTable 的 request）；`useProgressPolling` 每 3 秒对非终态文档调 `documents/progress`（≤50 个一批）并局部合并到列表缓存，全部终态后停止，状态变终态时刷新知识库统计；批量启用/禁用/删除（删除二次确认）；重新分段弹窗 `ReprocessModal` 复用 `ChunkRuleForm`（模式锁定、初值取文档 `process_rule` > `last_process_rule` > 默认，确认文案“将丢弃全部现有分段及人工修改”）；下载用 blob + `Content-Disposition` 解析；模型停用时 Layout 顶部提示、隐藏上传；`guideUpload`（创建后跳转带 `location.state`）显示引导条与“上传文档”按钮，关闭时清除 state。
  - FE-12 上传向导：`upload/{index.tsx,chunkRule.ts,fileCheck.ts}`、`components/{FileSelectStep,ChunkSettingStep,ProcessStep,ChunkRuleForm,PreviewPanel}.tsx`。不设 `accept`（否则拖拽的 .exe 会被静默丢弃，无法按 AC-36 标红）；选择即上传，并发 3，预检失败（类型/空/>15MB）标红不上传，后端错误逐文件展示，重复内容显示“与已有文档《x》内容重复”，失败可重试；总数 >20 提示并忽略多出部分。`ChunkRuleForm` 为受控组件，字段校验由纯函数 `validateRule(value, maxInputTokens)` 实现（与 3.5 一致：分隔符 1~10 字符、通用 50~4000/重叠 ≤50%、父块 50~4000、子块 20~父块（全文 4000）且 ≤ 模型 `max_input_tokens`），`maxInputTokens` 取自 `models/options` 中知识库所用模型；规则不合法时预览/提交均禁用；预览失败 400505/400506 将该文件标为不可提交，标记按“规则指纹”失效（改规则后恢复）；提交 409501 按 `data.duplicates` 标红对应文件，400508 标红失效文件。`process_rule.parent.mode`、`separator` 等字段名按 3.5 JSON；全文模式仍会带上父块分隔符/长度的默认值（后端忽略）。
  - FE-15 设置页：基础信息（名称/描述/图标/Embedding 模型）与检索设置**分别保存**（各带 `version`）；模型仅所有者且 `doc_count=0` 可改，否则只读并提示；`RetrievalConfigForm`（`src/components/`，受控，`retrievalConfig.ts` 提供默认值/校验/规范化）：混合检索权重滑块 0~1 步长 0.1 并显示“语义 x / 关键词 y”，无启用 Rerank 模型时开关置灰并提示，Top K / 阈值的输入框不做强制钳位（越界会显示校验错误并禁用保存，对应 AC-48）；提交前 `normalizeRetrievalConfig` 清理不适用字段（混合检索 `reranking_enable=false`、权重模式 `reranking_model_id=null` 等）。危险区仅所有者：转移（`AssignableUserSelect` 搜索 `assignable-users`，成功后跳回列表）、删除（`pages/kb/components/DeleteDatasetModal`，与列表页共用）。
  - FE-16 分配页：所有者信息 + 分配表（对象、类型、含下级、权限、状态“有效/已失效”、添加人、时间）；仅所有者且有 `kb:dataset:assign` 可添加/修改/移除（失效对象只能移除）；添加弹窗：类型 → 用户搜索或组织树（`assignable-orgs`，部门类型只可选 dept 节点，公司类型只可选 company/group 节点，其余置灰）→ 含下级（部门默认是、公司默认否）→ 权限（默认只读）。
  - 契约备注（不影响联调，建议后端确认）：5.2.6 `retrieval-config` 接口未写明响应体，前端保存后重新拉取详情，不依赖响应；5.5 下载接口错误时若返回 JSON，前端因 `responseType=blob` 只能显示通用提示；列表项无 `assignment_count`，删除弹窗额外请求详情（已确认保持）。
  - 单测（新增）：`chunkRule.test.ts`、`fileCheck.test.ts`、`retrievalConfig.test.ts`、`documents/logic.test.ts`、`navItems.test.ts`、`assignments/logic.test.ts`、`settings/logic.test.ts`、`services/kb.test.ts`，以及组件/页面测试 `ChunkRuleForm`、`RetrievalConfigForm`、`documents/index`（轮询局部刷新与停止、只读、失败重试、空/错误态）、`upload/index`（21 个文件、预检标红、重复、全文超长、参数非法、提交与进度、锁定分段方式）、`assignments/index`、`settings/index`。
  - **FE-13、FE-14、FE-17 已完成**（对契约开发 + mock 单测，未联调；Playwright 路由 mock 渲染自查了分段/召回/管理列表/管理详情页）。`kb-contract.ts`、`services/kb.ts` 仅追加：`segmentApi`、`retrievalApi`、`adminDatasetApi`，错误码补充 `KbSegmentErrorCode`（原 `KbErrorCode` 未改）。
  - FE-13 分段页（`pages/kb/detail/segments/`）：`index.tsx` 加载文档详情（缓存键 `['kb-document', datasetId, documentId]`，处理中每 3 秒刷新至终态）后渲染共用面板 `components/SegmentsPanel.tsx`（props：`readonly`、`canEdit`、`fetchSegments`、`scope: normal|admin`），FE-17 以 `readonly` + admin 取数函数复用。权限：`resolveEditAccess`（非只读模式 且 `my_permission != read` 且 `kb:segment:update` 且文档 `available`；文档未就绪时给出原因提示）。列表：序号/字符数/召回次数/“已编辑”/索引状态（`updating` 索引更新中、`failed` 索引更新失败、`pending` 等待索引）/启用开关/内容 3 行可展开/关键词；父块 `Collapse` 展开子块，子块编辑/删除、“新增子块”；存在 `updating|pending` 的分段或子块时每 3 秒轮询（只读模式不轮询）。抽屉编辑：内容 + 通用分段关键词（tags，0~10 个、每个 ≤20 字、去重）；长度上限取文档 `process_rule`（通用 max_tokens / 父块 max_tokens，全文模式 10000 / 子块 max_tokens），前端仅按字符数粗略告警、不拦截，超限以后端 400511 为准；仅内容为空会在前端阻止保存。父块保存前 `modal.confirm`“将按设置重新生成子块，子块的人工修改会丢失”，确认后带 `confirm_regenerate_children=true`。409511：提示“该分段已被他人修改”、关闭编辑、刷新列表（version 随刷新更新）；400511/400512 显示在抽屉内。写操作成功后统一失效分段列表、文档列表/详情、知识库详情缓存。删除分段/子块需二次确认（父块提示连同子块删除）。新增分段仅通用分段显示（父子不显示）。
  - FE-14 召回测试页（`pages/kb/detail/recall/`）：问题 0/500 计数（trim 后 1~500，空或超长禁用测试）；检索设置摘要 + “修改”抽屉（复用 `RetrievalConfigForm`，非法值禁用“应用”）；“应用（仅本次测试）”只改页面内状态，“保存为默认设置”仅 `canSaveAsDefault`（`my_permission != read` 且 `kb:dataset:update`）显示，调用 `PUT retrieval-config` 并带知识库 `version`，成功后刷新详情缓存。请求仅在设置与知识库默认设置不同时才带 `retrieval_config`（均经 `normalizeRetrievalConfig`）。结果按得分降序（2 位小数）+ 文档名 + 分段序号，点击抽屉看详情；父子结果显示父块全文，命中子块按 `indexOf` 定位加 `<mark>`（重叠区间合并，仅相接的区间保持分开），定位不到的子块在下方单独列出；`rerank_skipped` 显示提示；无结果显示“未召回到相关内容，可尝试降低 Score 阈值或调整分段”；`503301/409303/409506` 显示错误卡片而非空结果；无可用文档或向量模型停用时测试按钮置灰并提示；测试记录表（`retrieve-records`，每次测试后刷新）一键重测沿用记录中的检索设置；无 `kb:retrieval:test` 显示 403。召回测试请求超时 60s。
  - FE-17 管理视图（`pages/system/dataset/`）：路由 `/system/datasets`（`kb:admin:list`）、`/system/datasets/:id`（`kb:admin:view`），已替换占位。列表：ProTable 查询（名称、所有者、所属组织 `OrgTreeSelect`、所有者状态）+ 工具栏“待交接”开关（`pending_handover`）；所有者状态标签“已停用/已删除”；操作“查看”（`kb:admin:view`）、“转移”（`kb:admin:transfer`）；“批量转移”（`BatchTransferModal`：`admin/owners` 搜索原所有者 → `list?owner_id=` 列出名下知识库（≤100，默认全选）→ `admin/receivers` 选接收人 → 二次确认；全选但总数超过已加载数时省略 `dataset_ids`，由服务端转移其范围内全部；409321 展示 `data.conflicts` 名单并提示已整体回滚）。详情：顶部“审计查看，操作将被记录”，基本信息、分配名单、文档列表（只读，无下载/启停/删除）；“查看分段”以抽屉复用 `SegmentsPanel` 只读模式，取数走 `GET admin/.../segments`；全页没有编辑、上传、下载、删除、召回测试入口，唯一写入口为 `kb:admin:transfer` 的“转移所有权”。为避免重复写审计日志：`GET admin/datasets/{id}` 用 `staleTime: Infinity`、关闭窗口聚焦/重连重取、不重试；管理视图分段查询关闭窗口聚焦重取且不轮询（`page=1` 的每次请求都会写一条 `admin_view` 日志，翻页回到第 1 页、改搜索条件会再次记录，属预期）。
  - 契约调整已落地（对应 5.8、5.8.1）：①`AdminDatasetItem.version` 必填，单个转移带 `version`，批量转移不带；②409321 的 `data.conflicts` 固定为 `[{dataset_id, dataset_name}]`，已删除兼容多种写法的逻辑；③管理视图只读分段头部改用 `GET admin/datasets/{id}/documents/{document_id}`（`AdminSegmentsView`，含 `process_rule`，不记日志）；④审计：仅两种主动进入带 `audit_entry=true`——审计详情页的详情请求、点击“查看分段”打开分段面板的首次分段请求（`SegmentsPanel` 每次挂载首个成功请求带一次，翻页/搜索/重取不带，且不再依赖 `page=1`）。其余备注：管理视图分段子块无 `enabled`（启停以父块为单位），前端子块不显示启用状态。
  - 单测（FE-13/14/17 新增，均不依赖后端）：`segments/logic.test.ts`（内容/关键词校验、上限取值、编辑权限、保存请求体、409511/400511/400512 分类、轮询判定）、`segments/SegmentsPanel.test.tsx`（通用分段标签与启停、409511 提示并刷新、空内容不可保存、父块展开子块、父块保存确认并带 `confirm_regenerate_children`、新增子块、禁用父块、只读模式与只读用户无写入口、空/错误态）、`recall/logic.test.ts`（问题校验、可用性、保存默认权限、请求构造含 Top K/阈值、得分降序与 2 位小数、父子高亮与未定位子块、错误文案）、`recall/index.test.tsx`（403、置灰、计数、降序结果、父子聚合按父块 1 条且高亮、临时改 Top K/阈值仅本次生效且非法值不可应用、保存默认带 version、只读不显示保存默认、无结果引导与 rerank 提示、503301 不当空结果、记录重测）、`system/dataset/logic.test.ts`、`system/dataset/index.test.tsx`（状态标签、待交接参数、无转移权限无入口、错误态）、`system/dataset/detail/index.test.tsx`（审计提示、详情仅请求一次、无任何编辑/上传/下载/删除/召回入口、分段走 admin 接口、仅首次带 audit_entry 且只读、404/错误态）、`system/dataset/components/BatchTransferModal.test.tsx`（owner_id 过滤、默认全选提交、409321 冲突名单）。
  - 小改动（FE-09 / 文档下载）：①模型配置页 embedding 维度 > 4000（以表单维度为准，测试成功会自动回填；表单为空时取测试得到的维度）时显示警告“该模型维度超过 4000，无法建立向量索引，大知识库检索会变慢”，只提示不拦截（`system/model/logic.ts` 的 `isHighDimension`）；②下载出错：响应拦截器（`api/request.ts` 的 `parseBlobErrorBody`）对 `responseType=blob` 的错误响应，把 `response.data`（Blob）按文本解析为统一 JSON 后再转 `ApiError`，页面提示后端 `message`（如“原文件不存在或已被清理”），非 JSON 时回退“服务异常，请稍后重试”；该处理对所有 blob 请求通用，未改动 `documentApi.download` 的调用方式。
  - **BE-16 已完成**（纯函数库，不访问 DB/Redis）。文件：`app/parsers/{__init__,errors,text,pdf,ooxml,excel,html,registry}.py`、`app/splitters/{__init__,preprocess,tokenizer,general,parent_child}.py`、`app/schemas/process_rule.py`。
  - 调用约定（BE-17/BE-18）：
    - `from app.parsers import validate, parse, parse_with_timeout, ProcessError`
      - `validate(path, ext) -> None`：上传轻量校验，顺序 400501 → 400503 → 400502 → 400504；失败抛 `ProcessError`。
      - `parse(path, ext) -> str`：同步纯函数，解析为纯文本（已去 `\x00`）；无法解析 400504；全文空白 400505。
      - `await parse_with_timeout(path, ext, timeout_seconds=60, pool=None) -> str`：在进程池（spawn，默认 2 进程，`get_pool/shutdown_pool`）中执行 `parse`；超时抛 400504（`reason=TIMEOUT`，message“文件解析超时”）。注意超时后池进程会跑到自然结束，池大小限制并发；应用关闭时调用 `shutdown_pool()`。
    - `ProcessError(code, message, reason, data)`：可 pickle，`.to_biz_error()` 转 `BizError`。`reason` 取值：`UNSUPPORTED_TYPE`(400501)、`TOO_LARGE`(400502)、`EMPTY`(400503)、`ENCRYPTED`/`CORRUPT`/`TIMEOUT`(均 400504)、`NO_TEXT`(400505)、`FULL_DOC_TOO_LONG`(400506)、`INVALID_RULE`(400001，`data={"errors":[{"field","message"}]}`)。
    - `from app.schemas.process_rule import ProcessRule, check_rule`：`ProcessRule.model_validate(dict)` 做静态校验（pydantic `ValidationError`，loc 形如 `("general","chunk_overlap")`，调用方加 `process_rule.` 前缀转 400001）；当前模式缺省子规则自动取 PRD 默认值；`extra=forbid`。需要模型信息或跨字段的校验（`max_tokens ≤ model.max_input_tokens`、子块上限 ≤ 父块 max_tokens/4000）在 `check_rule(rule, model_max_tokens) -> list[RuleFieldError(path, message)]`，`split_document` 内部也会调用并抛 400001。
    - `from app.splitters import split_document, split_general, preprocess, count_tokens`：
      - `split_document(text, rule, model_max_tokens=None) -> list[SegmentDraft]`：预处理 + 分段，预览与正式处理共用；`SegmentDraft(position, content, char_count, token_count, children: list[ChildDraft])`，`ChildDraft(position, content, char_count, token_count)`，position 均从 1 连续；通用分段 `children=[]`。预处理后无内容 → 400505；全文模式 >10000 tokens → 400506。
      - 预览：`drafts[:10]`；`total_segments=len(drafts)`、`total_child_chunks=sum(len(d.children))`；`doc_token_count` 由调用方对预处理后文本或 `parse` 结果 `count_tokens` 得到。
  - 实现要点：解析输出格式严格按 3.5 表；Excel/CSV 空值单元格不输出、全空行跳过、仅表头的工作表不输出；HTML 块级元素换行并压缩空行；OOXML 校验除 `[Content_Types].xml` 外还检查主部件并限制解压总量 300MB；PDF 逐页提取，单页异常跳过、全部页异常判损坏；空密码可解密的加密 PDF 视为可读。`split_general` 超长段落递归后备分隔符，逐字符层按组（≤ max_tokens/4 个字符）切分以保证性能（40 万字无分隔符文本约 1.8s），重叠只出现在同一超长段落的切分块之间且 ≤ 设置值；相邻短段不合并；同输入结果确定。tiktoken 离线加载见 BE-11，`CL100K_SHA256` 校验。
  - 单测：`backend/services/kb/tests/unit/{test_parsers,test_splitters,biff}.py`（`biff.py` 手工构造 BIFF8 .xls 样例，xlrd 无法写入故不依赖 LibreOffice）；不依赖 DB/Redis，BE-11 的 conftest 仅设置环境变量，未改动。
  - **BE-14 已完成**（知识库 CRUD、我的列表、ACL、统计）。文件：`app/api/v1/datasets.py`、`app/schemas/dataset.py`、`app/services/{dataset_service,stats_service}.py`、`app/repositories/{dataset_repo,dataset_acl}.py`；`api/v1/__init__.py` 挂载路由。无新迁移。接口：`GET /datasets`、`GET /datasets/options`（声明在 `/{id}` 之前）、`POST /datasets`、`GET|PUT|DELETE /datasets/{id}`、`PUT /datasets/{id}/retrieval-config`；`transfer` 入口留给 BE-23。
    - **ACL 函数（`app/repositories/dataset_acl.py`，供 BE-15/17/19/20/21/22/23 复用）**：
      - `Level = Literal["owner","edit","read"]`；`Need = Literal["read","edit","owner"]`；`level_satisfies(level, need)`。
      - `async get_permission_level(session, ctx, dataset_id) -> Level | None`：知识库不存在/已删除/无访问权 → `None`。
      - `async require_dataset(session, ctx, dataset_id, need, *, for_update=False, allow_super_admin=False) -> Dataset`：不存在或不可访问 → `BizError(404000)`；可访问但级别不足 → `BizError(403311)`。`resolve_dataset(...)` 同参数，返回 `(Dataset, Level)`（需要知道调用者级别时用，如更换向量模型要求所有者）。写操作务必 `for_update=True`（锁知识库行，与并发转移/删除串行，事务内重新校验）。`allow_super_admin=True` 仅删除接口使用（超管视同所有者），其余接口超管无日常访问（404000）。
      - `accessible_dataset_ids_subquery(ctx) -> Select`（所有者 + 匹配分配，未删除知识库 id，用于 `Dataset.id.in_(...)`）、`edit_dataset_ids_subquery(ctx)`（经"可编辑"分配获得编辑权的知识库 id）、`assignment_match(ctx)`（作用于 `DatasetAssignment` 的命中条件）。
      - 判定规则：所有者（`dataset.owner_id == ctx.user_id`）> 可编辑 > 只读；多途径取最高。个人：`target_id = user_id`；部门：不含下级 `= ctx.org_id`、含下级 `∈ ctx.org_path`；公司：不含下属 `= ctx.company_id`、含下属 `∈ ctx.org_path`（`org_path` 含自身）。只基于实时 AuthContext，调岗后下一次请求（AuthContext 缓存刷新后）立即生效；不依赖 user_ref/org_ref。已逻辑删除的分配不计。
      - 功能权限码与 ACL 同时校验：路由层 `require_perm` 先判功能码（403001），service 再判 ACL。例如上传需 `kb:document:upload` + `require_dataset(..., "edit")`。
      - 级别要求：详情/列表 read；编辑基础信息、检索设置 edit（`embedding_model_id` 变更要求 owner，否则 403311）；删除 owner（超管放行）。
    - **统计（`stats_service`）**：`async recalc_document(session, document_id)`（`char_count`、`segment_count`=未删除分段/父块含禁用、`child_count`=未删除且 `generation = parent.child_generation` 的子块）与 `async recalc_dataset(session, dataset_id)`（`doc_count` 含处理中/失败；`processing_count`=queued/parsing/splitting/indexing；`failed_count`；`available_doc_count`；`segment_count`/`child_segment_count`/`char_count` 仅汇总 `status='available'` 文档的冗余列）。两者只执行 UPDATE、不 commit，调用方在同一事务内先 `flush` 再调用（会话 `autoflush=False`）。AC-25 数值（5/1/1/60、父块 4/子块 25）有单测。注意：`recalc_dataset` 不重置 `chunk_mode`，"文档全部删除后置回 NULL"由 BE-19 完成；`recalc_dataset` 会因 UPDATE 刷新 `updated_at`。
    - **契约确认与补全**：
      - `DELETE /datasets/{id}` 使用 `Annotated[DatasetDeleteBody, Body()]`，OpenAPI 中 `requestBody` 为 required 且引用 `DatasetDeleteBody`（单测验证）；axios `http.delete(url, { data: body })` 可直接使用。名称严格相等比较（区分大小写，不 trim）；无请求体 → 400001。删除单事务：知识库/文档/分段/子块/分配逻辑删除，分段与子块 `search_enabled=false`，文档 `process_attempt+1`；`chunk_mode` 保持；操作日志 summary 含分配对象数。
      - `PUT /datasets/{id}/retrieval-config` 响应补全为最新 `DatasetDetail`（含新 `version`），已写入 5.2.6；前端仍可只重新拉详情。
      - `PUT /datasets/{id}`：只更新请求中出现的字段（`name` 必填；`description`/`icon` 传 `null` 清空、不传保持）；`embedding_model_id` 与当前相同视为未修改。名称唯一按**所有者**名下判定（可编辑者改名撞上所有者已有同名 → 409311）。
      - 检索设置：`retrieval_config` 拒绝多余字段；缺省字段取默认值；`score_threshold` 最多两位小数、`vector_weight` 步长 0.1（否则 400001）；保存前规范化——混合检索 `reranking_enable=false`；非混合检索 `hybrid_mode=weighted`、`vector_weight=0.7`；不需要 Rerank 时 `reranking_model_id=null`；需要 Rerank（向量/全文开启 Rerank，或混合 rerank 模式）而未给模型或模型非"已启用的 rerank 模型" → 400303。创建知识库未传 `embedding_model_id` 且无默认启用模型 → 400303。
      - 列表：`my_permission` 取最高级别（所有者 > 可编辑 > 只读，同一知识库不重复）；`sort_order` 缺省 desc（`name` 缺省 asc），同值按 id 降序；`owner_keyword` 匹配 user_ref 的姓名/账号；`owner` 在 user_ref 缺失时（新用户尚未同步）对当前用户回退 ctx.name，其他回退"未知用户/deleted"。批量取所有者与模型，无 N+1。`/datasets/options` 默认 `page_size=50`。
      - **process_rule 在父子全文模式忽略父块 separator/max_tokens**：属 BE-17（提交/预览）范围，BE-14 不涉及；BE-16 的 `ProcessRule` 已允许 full_doc 模式携带这两个字段（前端会带默认值），`split_document` 忽略它们，BE-17 校验时不得因这两个字段拒绝。
    - 测试：`tests/unit/test_datasets_api.py`（20 个）：权限 401/403001、功能码与 ACL 同时校验、创建默认值/校验/模型规则/同名、ACL 矩阵（个人/部门含不含下级/公司含不含下属/最高级别/调岗/分配与知识库已删除/超管无日常访问）、列表范围（AC-26）与过滤排序分页、AC-25 精确统计、编辑与模型更换（AC-31/32）、只读与可编辑与无关用户（403311/404000，含数据范围内管理员）、检索设置校验与规范化（AC-48）、删除级联（AC-30）、超管删除、OpenAPI 请求体。`tests/unit/helpers.py` 的 `make_ctx/as_user` 新增 `org=(org_id, company_id, org_path)` 参数用于模拟不同组织的用户；`test_app.py` 的"未知路由"用例改用 `/api/v1/kb/no-such-resource`（原路径现已存在）。
    - 联调：iam + kb 在开发库用 admin（超管）curl 验证创建（含 409311、400303）、列表/选项、检索设置（400001、混合检索规范化）、编辑、删除（400311、成功、再访问 404000）、401；测试用的模型与知识库已清理，admin 的 `must_change_password` 已恢复为 true。注意开发库现有模型 `live-emb` 已被逻辑删除、无默认模型，联调创建知识库需先配置并启用一个 embedding 模型。
  - **BE-15 已完成**（知识库分配，F-10）。文件：`app/api/v1/assignments.py`、`app/schemas/assignment.py`、`app/services/assignment_service.py`、`app/repositories/assignment_repo.py`；`api/v1/__init__.py` 挂载。无新迁移。6 个接口权限码与 ACL 级别完全按 5.3：名单 `kb:dataset:list` + 可编辑（不分页，按 created_at 升序）；新增/修改/移除 `kb:dataset:assign` + 所有者（`for_update` 锁知识库行后校验）；`assignable-orgs`/`assignable-users` 任一 `kb:dataset:assign`/`kb:dataset:transfer` + 所有者。
    - **可分配范围**：所有者当前 `ctx.company_id` 对应的 org_ref 节点 C；C 的 `org_type='group'`（集团本部）时为全集团，否则为 C 及其所有下级（`ancestors` 含 C 的节点，SQL 绑定整数拼 LIKE，不含用户输入）。目标为用户时校验其主组织（user_ref.org_id）在范围内，且用户启用未删除；目标为组织时校验在范围内。范围外/不存在/已删除/已停用用户/类型不匹配（公司当部门、部门当公司）→ 400402；所有者本人 → 400401（先于范围校验）；重复 → 409401（含并发下唯一索引冲突）。`company` 类型允许 `company` 与 `group` 节点（后者仅集团本部所有者能通过范围校验）。
    - 规则：`include_children` 用户恒 false；dept 缺省 true；company 缺省 false；修改接口 `include_children` 对用户同样强制 false。修改/移除按 `dataset_id + assignment_id` 查找，其他知识库的分配 id → 404000；失效对象（组织/用户已删除）只能移除，修改 → 400402。成员动态生效：不存成员快照，ACL 每次按 ctx 判定。
    - 响应：`AssignmentItem`（`target_path`：祖级名称 + 自身，不含集团节点，如 `A公司/研发部/测试部`；用户取其主组织路径；对象副本缺失时 `target_name="未知对象"`、`target_valid=false`，`created_by` 缺失时"未知用户"）；批量取用户/组织，无 N+1。`assignable-orgs` 返回范围内未删除组织树（含停用节点，status 展示），根为范围内最顶层节点；`assignable-users` 分页，`org_id` 含下级（范围外 org_id 返回空），排除所有者与停用/删除用户，LIKE 转义。
    - 操作日志：dataset/assign_create、assign_update、assign_delete，target 为知识库，summary 含对象类型/id/名称、权限、含下级（update 含前后值）。
    - 测试：`tests/unit/test_assignments_api.py`（7 个）：权限码 401/403001/仅 transfer 可看候选、AC-33（部门含下级 + 个人可编辑，可编辑者 403311 增改删与候选、只读者 403311、无关者 404000）、AC-34（A 公司所有者对 C 公司/集团/停用用户 400402，集团本部所有者可分配 B/C/集团且 B 员工可见，候选树/用户范围）、默认值与重复/修改/AC-35 移除即时生效/跨知识库 id/重新添加、失效对象展示与仅可移除、候选用户过滤分页、审计字段。测试复用 `test_datasets_api.py` 的 `api` 夹具。
    - 联调：iam + kb 在开发库用 admin（集团本部）curl 验证 6 个接口（开发库组织均已在 iam 逻辑删除，联调临时向 kb.org_ref/user_ref 插入 id 90~92 的数据，已全部清理）；admin 的 `must_change_password` 已恢复为 true，测试知识库与模型已清理，进程已停止。
    - 契约补充（均已落实于实现，无需改前端）：`target_path` 的生成规则、`assignable-orgs` 树根为范围内最顶层节点（非固定集团节点）、失效对象修改 400402。
  - **BE-17 已完成**（上传、预览、提交，F-11）。文件：`app/api/v1/uploads.py`、`app/schemas/upload.py`、`app/services/upload_service.py`、`app/repositories/document_repo.py`（创建部分：计数、哈希查重、有效上传文件查询/加锁）、`app/storage/s3.py`（新增 `get_storage()` 单例）、`main.py`（lifespan 创建/关闭解析进程池）、`app/core/config.py` + `.env.example`。无新迁移、无新依赖。3 个接口（均 `kb:document:upload` + ACL 可编辑）路径/字段/错误码与 5.4 一致。
    - **进程池与超时配置**：`PARSE_PROCESS_WORKERS`（默认 2，池大小，同时是并发校验/解析数上限，池满时请求排队）、`PARSE_TIMEOUT_SECONDS`（默认 60，单次校验/解析的等待上限，含排队时间）。超时返回 400504 "文件解析超时"（`wait_for` 只取消等待，池进程会跑到自然结束，占用一个池位）；池进程崩溃（`BrokenProcessPool`）时重建池并按"已加密或已损坏"400504 处理。上传时的 `validate` 与预览时的 `parse` 都走该池（`upload_service._in_pool`）；分段（`split_document`）在线程中执行，用信号量限制同时 2 个。读事务在进入解析/联网前 `rollback`，不占数据库连接。
    - **上传**（5.4.1）：校验顺序 409303 → 400501（扩展名白名单，大小写不敏感，无扩展名也是 400501）→ 400503/400502（流式写入临时文件并计算 SHA-256，超过 15MB 立即中止；恰好 15MB 允许）→ 400504 → 409501 → 409502；解析/校验完成后会再次校验 ACL 与模型状态（期间权限可能被收回）。409501 的 `data={"existing_document_name"}`，message `与已有文档《{name}》内容重复`。文件名：去路径与控制字符，超 200 字符截断且保留扩展名。成功后写 `kb.upload_file`（`expires_at = now + UPLOAD_FILE_TTL_HOURS`，`created_by` = 上传人）与对象 `uploads/{dataset_id}/{upload_file_id}/{hash}.{ext}`；被拒绝的文件不留记录与对象。**同内容文件在提交前可重复上传**（只与"已有文档"比较），由提交时整体查重兜底。
    - **预览**（5.4.2）：校验顺序 模型 409303 → upload_file（400508：不存在/不属于本库/已过期/已提交/原文件对象缺失）→ 分段方式锁定 409503（message `该知识库的分段方式为通用分段/父子分段，不能切换`）→ 规则 400001。**规则错误统一为 400001**，`data.errors=[{field:"process_rule.xxx", message}]`：静态校验（范围、重叠、分隔符长度等）由请求模型 `ProcessRule` 完成，message 为 pydantic 原文（如 `Input should be greater than or equal to 50`、`Value error, 分段重叠长度不能超过…`），前端以本地校验为主，服务端 message 仅作兜底；依赖模型的跨字段校验（`max_tokens ≤ 模型 max_input_tokens`、子块 ≤ 父块/4000）使用 `check_rule`，message 为中文。**父子全文模式不因父块 `separator`/`max_tokens` 拒绝**（子块上限按 4000 校验，见 `check_rule`）。解析文本缓存到 `parsed/{upload_file_id}.txt` 并写回 `upload_file.parsed_key/doc_token_count`（`doc_token_count` 为**预处理前**全文 token 数）；再次预览直接读缓存。预览返回前 10 个，`total_segments`/`total_child_chunks` 为全量。400505/400506 同契约。
    - **提交**（5.4.3）：单事务，`resolve_dataset(..., "edit", for_update=True)` 锁知识库行（并发提交相同内容只有一个成功，有单测）。校验顺序：模型 409303 → 分段方式 409503 → 规则 400001 → 文档数 409502（`count + 本次 > DATASET_MAX_DOCUMENTS`）→ 上传文件有效性 400508（任一无效整体拒绝，上传文件行同时 `FOR UPDATE`）→ 重复 409501。`upload_file_ids` 在请求模型内去重并保序（1~20）。**409501 提交时的 message**：1 个重复为 `与已有文档《{name}》内容重复`；多个为 `有 N 个文件内容重复，例如与已有文档《{first}》重复`；`data.duplicates=[{upload_file_id, existing_document_name}]` 列出全部；批次内相同内容的后出现者记为重复（`existing_document_name` 为批次内先出现者的文件名）。成功：创建 `document`（`status=queued`、`process_attempt=1`、`enabled=true`、`chunk_mode=rule.mode`、`process_rule` = `model_dump(exclude_none=True)` 即补全默认值后的规则、`parsed_key` 沿用上传文件的缓存、`created_by` = 上传人），`upload_file.consumed_document_id` 回填，`dataset.chunk_mode`（原为空时设置）、`last_process_rule` 更新（**不 bump `version`**），`recalc_dataset`，提交后投递任务。操作日志：成功时每个文档一条 `document/upload`（target = 文档，summary 含 dataset_id/dataset_name/file_ext/file_size/chunk_mode）；失败记一条 `document/upload`（target = 知识库）。
    - **投递消息格式（BE-18 消费）**：`XADD stream:kb.tasks`，单字段 `data` = JSON 信封（`platform_common.events.publisher` 的统一格式）：
      ```json
      {"event_id":"uuid","type":"document.process","occurred_at":"...","payload":{"document_id":101,"attempt":1,"from_stage":"parse"}}
      ```
      提交时 `attempt` 恒为文档当前 `process_attempt`（=1）、`from_stage="parse"`；每个文档一条，保持上传文件顺序。通过 `publish_after_commit` 在事务提交成功后才发布，回滚不发；**发布失败（Redis 抖动）只记日志，文档停留 `queued`**，依赖 BE-18 的 queued 巡检（>30 分钟无待处理消息则重投）兜底。消费方按 3.6 校验 `attempt == document.process_attempt`。
    - 前端无需改动（字段与 `kb-contract.ts` 一致）。补充说明：①multipart 文件由 Starlette 先完整接收（大文件落临时文件）后才进入路由，因此超过 15MB 的文件仍会被接收完毕再返回 400502（前端预检已拦截常见情况）；②预览失败（400505/400506）不影响上传记录，用户可改规则或换文件。
    - 测试：`tests/unit/test_uploads_api.py`（23 个，真实 Postgres/Redis/MinIO 桶 kbp-test）：权限 401/403001、ACL（可编辑/只读 403311/无关 404000/无功能码 403001）、上传成功与存储键、文件名清洗、各类拒绝（exe/无扩展名/空/15MB±1/损坏 docx/坏 pdf/加密 pdf，拒绝不留记录）、模型停用先于其他校验、重复内容（改名、跨库不冲突）与上限、进程池超时 400504、预览（AC-37 与分段器逐段一致、缓存、预处理、AC-63 父子、全文模式忽略父块字段与 400506、无文本、规则 400001 各分支、400508 各分支）、提交（落库字段、统计、投递消息、操作日志、去重、分段方式锁定与清空后重选、批次内/已有重复整体拒绝、并发相同内容只一个成功、文档上限、请求体边界、防跨库 ID 越权）。
    - 联调：devctl 启动 iam+kb，本地假 embedding 服务（`/v1/embeddings`）启用模型 → 创建知识库 → 上传（成功/exe/空/>15MB/损坏 docx/改名重复）→ 预览（通用 12 段、非法规则 400001、父子 12 父块/36 子块）→ 提交（queued，`stream:kb.tasks` 收到 `{"document_id":1,"attempt":1,"from_stage":"parse"}`）→ 重复上传 409501、分段方式锁定 409503、详情 `doc_count=1/processing_count=1/chunk_mode=general`、401；`/docs` 与 OpenAPI 含 3 个接口。测试数据（模型/知识库/文档/上传记录/MinIO 对象/任务消息）已清理，admin `must_change_password` 已恢复为 true。
  - **BE-18 已完成**（kb-worker：文档处理流水线、超时巡检、排队重投、上传清理，F-12）。无新迁移、无新依赖（jieba 已在 BE-11 引入）。文件：`app/worker/{tasks_document,main_loop,sweeper,upload_cleanup}.py`、`app/engine/fulltext.py`、`app/services/segment_service.py`（`refresh_search_flags`）、`app/repositories/{document_repo(处理部分),segment_repo}.py`、`worker.py`（`register_defaults` 注册 `document-tasks`、`sweeper`、`upload-cleanup`，退出时关闭解析池）、`app/core/config.py` + `.env.example`。
    - **新增配置**：`QUEUED_REDELIVER_MINUTES=30`（排队中超过该时长且队列无对应消息才重投）、`SWEEP_INTERVAL_SECONDS=60`、`UPLOAD_CLEANUP_INTERVAL_SECONDS=3600`、`TASK_CLAIM_IDLE_SECONDS=600`（XAUTOCLAIM 接管空闲阈值）、`DOC_LOCK_TTL_SECONDS=90`；沿用 `WORKER_CONCURRENCY`（消费者个数）、`EMBED_BATCH_SIZE`、`PROCESS_TIMEOUT_MINUTES`、`PARSE_PROCESS_WORKERS/PARSE_TIMEOUT_SECONDS`（worker 内解析同样走进程池）。
    - **消费**：`stream:kb.tasks`，消费组 `kb-doc-worker`，`WORKER_CONCURRENCY` 个 `StreamConsumer`（batch=1）；组从 `0` 创建，所以 worker 停止期间提交的任务会在 worker 启动后全部处理（文档期间保持 queued）。`handle_task` 按 `type` 分发，`document.process` 内置；**BE-20 的 `segment.reindex`/`child.reindex`/`parent.regenerate` 在 `tasks_document.TASK_HANDLERS[type] = handler` 注册**，未注册类型告警后忽略（ACK）。
    - **状态机与阶段**：parse（`status=parsing`；`parsed/{upload_file_id}.txt` 存在则复用，否则读原文件→进程池解析→写对象→回填 `document.parsed_key`）→ split（`splitting`；`split_document`（与预览同一函数）+ jieba 分词，**单事务**：锁文档行并校验栅栏→软删该文档旧分段/子块→写新分段/子块→`progress_total` = 检索单元数、`progress_done=0`→`recalc_document`）→ index（`indexing`；只取 embedding 为空的单元按 `EMBED_BATCH_SIZE` 调用，**每批**先过栅栏并更新 `progress_done/progress_updated_at` 再写向量，批间重新读取模型状态）→ finish（单事务：先锁知识库行再锁文档行，`status=available`、`refresh_search_flags`、`recalc_document`、`recalc_dataset`）。父子分段：父块 `segment_type=parent`、`index_status=indexed`、无向量/tsv/不可检索，只向量化子块（`generation=1`）；通用分段 `index_status` 由 pending→indexed。tsv：`setweight(to_tsvector('simple', jieba.cut_for_search 空格连接), 'B')`（关键词权重 A 的表达式由 `engine.fulltext.tsv_expr(tokens, keyword_tokens)` 提供，BE-20 使用）。
    - **失败原因**（`document.failed_stage/error_code/error_message`，与 3.6 一致）：`FILE_MISSING`、`NO_TEXT`（parse 或 split 阶段预处理后为空）、`PARSE_ERROR`（含"文件解析超时/已加密或已损坏"）、`FULL_DOC_TOO_LONG`、`SPLIT_ERROR`、`EMBEDDING_DISABLED`（模型停用/删除，批间检测）、`EMBEDDING_TIMEOUT`、`EMBEDDING_ERROR`（含 `HTTP 状态：简述`；凭据无法解密也归此类）、`DIMENSION_MISMATCH`（返回向量维度 ≠ `model.dimension`）、`TIMEOUT`（巡检）。未预期的业务代码异常按阶段兜底为 `PARSE_ERROR/SPLIT_ERROR/EMBEDDING_ERROR`"…内部错误"。仅基础设施异常（DB/Redis/对象存储）不改状态，抛给消费者重试（5 次后死信，超时巡检兜底）。
    - **栅栏与并发安全**：所有状态写入为 `UPDATE ... WHERE id AND process_attempt=:attempt AND NOT is_deleted AND status IN (queued,parsing,splitting,indexing) RETURNING`，不命中即静默结束（处理中删除、知识库删除、重试/重新分段/超时使 attempt 变化的旧任务都走这里）；每批向量与分段写入与栅栏同事务，被取消的批次整体回滚。同一 `(document_id, attempt)` 由 Redis 锁 `kb:doc:process:{id}:{attempt}`（`SET NX EX` + 心跳续期，Lua 比对释放）串行：重复投递/XAUTOCLAIM 接管时拿不到锁的任务静默 ACK。崩溃后被接管的任务按文档当前状态从所在阶段继续（不早于 `from_stage`），向量化只补空向量。完成/失败/巡检重算 `recalc_dataset` 前先 `lock_dataset_row`（锁序：知识库 → 文档），并发完成的统计不会相互覆盖（有 4 文档并发完成的单测）。**BE-19 约定**：重试/重新分段入队时须在同一事务内 `process_attempt+1`、`status='queued'`、**`progress_updated_at=now()`**（排队重投以它计时）、清空错误信息，并 `refresh_search_flags`（重新分段）；`from_stage` 用 `failed_stage`（重试）或 `split`（重新分段）；处理中删除文档须 `is_deleted=true` 且 `process_attempt+1`，并软删分段/子块、`search_enabled=false`。
    - **巡检**（`sweeper.py`，每 `SWEEP_INTERVAL_SECONDS` 秒，`run_periodic` 单实例锁）：①`parsing/splitting/indexing` 且 `progress_updated_at` 超过 `PROCESS_TIMEOUT_MINUTES` → `failed`、`failed_stage` 为当时阶段、`error_code=TIMEOUT`、"处理超时"、`process_attempt+1`，并 `refresh_search_flags`、`recalc_dataset`；②**排队中（TQ-01）不计入处理超时**：`queued` 超过 `QUEUED_REDELIVER_MINUTES` 时扫描消费组（未投递 + pending，最多 5000 条）里是否仍有该 `(document_id, attempt)` 的任务，没有才重新 XADD（`from_stage = failed_stage 或 parse`）并刷新 `progress_updated_at`；有则继续等待。
    - **上传清理**（`upload_cleanup.py`，每 `UPLOAD_CLEANUP_INTERVAL_SECONDS` 秒）：只处理「过期且 `consumed_document_id IS NULL`」的 `upload_file`（`FOR UPDATE SKIP LOCKED`，与提交互斥），删除其原文件与预览产生的 `parsed_key` 对象并物理删除行；**已被文档消费的上传文件永不清理（其 `parsed/` 解析文本仍被文档使用）**；对象键被任一文档（含已删除）引用时即使上传未消费也不删对象。
    - **契约备注**：`refresh_search_flags` 位于 `app/services/segment_service.py`（签名 `await refresh_search_flags(session, document_id)`，只 UPDATE 不 commit）；`DocumentItem.progress` 取 `progress_done/progress_total`，index 阶段每批刷新；解析阶段文本缓存 `parsed/{upload_file_id}.txt` 在上传 id 不重复的前提下可直接复用（测试库 id 会重置，测试夹具会清理）。
    - 测试：`tests/unit/test_pipeline.py`（17 个，真实 PG/Redis/MinIO，替换 `EmbeddingClient.embed`）：通用/父子/全文模式全流程（与分段器一致 AC-37、统计、tsv 命中、状态序列）、解析失败（NO_TEXT/FILE_MISSING）、全文超长、向量错误码映射与维度不一致、重试只补空向量（AC-41）、模型处理中停用→重启用重试、重新分段替换分段、删除前/处理中删除（栅栏）、重复投递串行、并发完成统计一致、消费者处理积压（停 worker→queued→恢复）、未知任务类型、巡检超时与旧 attempt 失效、排队重投（消息存在不重投/丢失重投）、上传清理（保留被引用/已消费的对象）、`refresh_search_flags` 各条件。kb 全部 189 个单测通过。
    - 联调：devctl 启动 iam、kb、kb-worker（`PROCESS_TIMEOUT_MINUTES=1 SWEEP_INTERVAL_SECONDS=5 QUEUED_REDELIVER_MINUTES=1`）+ 本地假 embedding 服务：worker 停止时提交 → queued，删除队列消息并将排队时间置旧 → worker 启动后巡检重投、处理为 available（14 段、14 向量/tsv、统计正确）；假服务返回 400 → failed(index, EMBEDDING_ERROR "向量模型调用失败：HTTP 400：model overloaded")，恢复后重试（attempt+1，from_stage=index）→ available；把文档置为 indexing 且进度时间置旧 → 巡检 failed(TIMEOUT "处理超时")，重试后 available；父子分段文档 8 父块/24 子块处理完成。测试数据（模型/知识库/文档/分段/上传记录/MinIO 对象/`stream:kb.tasks`）已清理，admin 已恢复，进程已停止。
  - **BE-19 已完成**（kb：文档管理，F-13）。无新迁移、无新依赖。文件：`app/api/v1/documents.py`、`app/schemas/document.py`、`app/services/document_service.py`、`app/repositories/document_repo.py`（追加列表/归属查询/软删内容）、`api/v1/__init__.py`；`upload_service` 的 `require_enabled_model`/`check_mode`/`check_rule_for_model` 由私有改为公开（供重新分段复用，逻辑不变）。8 个接口权限码与 ACL 级别完全按 5.5（列表/进度/详情 `kb:dataset:list`+只读；启停/重试/重新分段 `kb:document:update`+可编辑；批量删除 `kb:document:delete`+可编辑；下载 `kb:document:download`+只读）。固定路径 `/progress`、`/enabled`、`/batch-delete` 声明在 `/{document_id}` 之前。
    - **列表**：`keyword` LIKE 转义；`status=processing` 为前四态；`sort_by` 白名单，同值按 id 降序；`uploaded_by` 经 `user_ref` 左连接一次取出（缺失为 `{id: created_by, name: "未知用户"}`）；`progress` 仅处理中（queued/parsing/splitting/indexing）返回 `{done,total}`，available/failed 为 null；`error_code/error_message` 仅 failed 返回。管理视图文档接口由 BE-23 提供，本任务不涉及。
    - **进度** `GET /documents/progress?ids=`：去重后 >50 个、含非正整数/非数字、缺少 `ids` → 400001（前端每批 50 个正好满额）；空串返回 `[]`；不属于本库/已删除的 id 静默不返回（轮询时文档被他人删除不应整体报错）。
    - **启停** `PUT /documents/enabled`：`document_ids` 在请求模型内去重（1~100）；锁知识库行后按 id 升序锁文档行；有任一 id 不在本库/已删除 → 404000 整体拒绝；仅状态变化的文档 `version+1`；对每个文档 `refresh_search_flags`，再 `recalc_dataset`；`data.updated` = 去重后命中的文档数（含状态未变的）。处理中文档也可启停（标志仍为 false，完成时由 finish 阶段按 enabled 计算）。操作日志 `document/enable|disable`（target=知识库，summary 含 ids）。
    - **删除** `POST /documents/batch-delete`：单事务——软删分段与子块（`search_enabled=false`）、文档 `is_deleted=true` 且 `process_attempt+1`（处理中删除使在途任务被栅栏拦截，已联调验证：删除后分段 0 条、可检索 0 条、统计只含剩余文档）、`recalc_dataset`；**文档全部删除后 `dataset.chunk_mode` 置 NULL**（BE-14 遗留项）。任一 id 不在本库 → 404000 整体拒绝。成功时每文档一条 `document/delete` 日志（summary 含 dataset_id/dataset_name/file_ext/file_size/status），失败记一条（target=知识库）。响应 `data={"deleted": n}`。**对象存储中的原文件/解析文本不物理删除**（上传文件行已被文档消费，按 BE-18 规则不再清理），属已知的存储残留，如需回收由后续运维任务处理。
    - **重试** `POST /documents/{id}/retry`：仅 failed（否则 409505），模型停用 409303（先于入队）；同一事务内 `process_attempt+1`、`status=queued`、`progress_updated_at=now()`、清空 `failed_stage/error_code/error_message`、`version+1`，提交后投递 `{"document_id","attempt"(新值),"from_stage": failed_stage 或 "split"}`；`recalc_dataset`（failed_count/processing_count 随之更新）。日志 `document/retry`。
    - **重新分段** `POST /documents/{id}/reprocess`：校验顺序 文档归属 404000 → 状态（仅 available/failed，否则 409504）→ version（409001）→ 模型 409303 → 分段方式 409503 → 规则 400001（与预览/提交同一份 `check_rule`）。事务内软删该文档全部分段/子块（含人工修改，`search_enabled=false`）、`process_rule`/`chunk_mode` 更新、`progress_done/total` 清零、入队（同重试，`from_stage="split"`；解析文本不存在时 worker 自动从 parse 开始）、`refresh_search_flags`、`recalc_document`（分段/字符/子块数归零）、`recalc_dataset`。日志 `document/reprocess`（summary 含 before/after process_rule）。不更新 `dataset.last_process_rule`。
    - **下载** `GET /documents/{id}/download`：`StreamingResponse` 流式转发（读事务在访问对象存储前结束，不占 DB 连接）；`Content-Type` 按扩展名，`Content-Disposition: attachment; filename="<ASCII 回退>"; filename*=UTF-8''<百分号编码>`，另有 `Content-Length`、`X-Content-Type-Options: nosniff`、`Cache-Control: private, no-store`。**所有错误都在开始输出前抛出，HTTP 状态码即 `BizError.code // 1000`，非 2xx 且响应体为统一 JSON**：文档/知识库不可访问 → 404 + 404000；无功能码 → 403 + 403001；原文件对象缺失 → 404 + 404000（message「原文件不存在或已被清理」）。前端用 blob 请求时可凭 `response.status` 非 2xx 判定出错，再把 blob 当文本解析出统一 JSON 取得 `message`（`error.response.data` 为 Blob）；无需契约变更。
    - 测试：`tests/unit/test_documents_api.py`（13 个，真实 PG/Redis/MinIO，复用 `test_pipeline` 的假 embedding）：全部 8 个接口的 401/403001/只读 403311/无关用户 404000/功能码缺失、列表过滤排序分页与 LIKE 转义、AC-66 父子展示、进度（含 50/51 边界、非法 id、跨库 id）、AC-42（通用与父子标志、整体拒绝）、AC-43（统计精确、chunk_mode 置 NULL 后可重选分段方式、每文档一条日志）、处理中删除（向量化期间删除、排队删除后旧任务被栅栏拦截）、重试（from_stage、attempt、409505、409303）、AC-44（丢弃人工编辑、queued 不参与检索、409001/409503/409504/400001/409303、worker 重新处理后"已编辑"清空）、下载（内容/头/非 2xx 错误）、OpenAPI。kb 全部 202 个单测通过。
    - 联调：devctl 启动 iam、kb、kb-worker + 本地假 embedding 服务，admin 登录：上传提交 2 个文档，`/progress` 观察 parsing→splitting→indexing(done/total)→available；`/documents` 列表与统计（2 文档/20 段）；禁用后该文档分段 `search_enabled` 全 f、启用恢复；含他库 id 的启停 404000；详情含 `process_rule`；下载内容与上传一致、缺失文档 404；重新分段（queued→重新处理，分段数 14→28）与旧 version 409001；失败文档重试 attempt=2 后 available、对可用文档重试 409505；处理中（splitting）删除成功且无残留可检索分段；删除后统计、全部删除后 `chunk_mode=null`；已删除详情 404000、无 token 401；OpenAPI 含 8 条文档路径。测试数据（模型/知识库/文档/分段/上传记录/MinIO 对象/`stream:kb.tasks`）已清理，admin `must_change_password` 已恢复为 true，进程已停止。
  - **BE-20 已完成**（分段管理与增量索引，F-14）。无新迁移、无新依赖。文件：`app/api/v1/segments.py`、`app/schemas/segment.py`、`app/services/segment_service.py`（在 `refresh_search_flags` 之后追加编辑函数，原函数未改）、`app/repositories/segment_repo.py`（追加查询/软删/子块重建）、`app/worker/tasks_segment.py`、`app/worker/main_loop.py`（导入 `tasks_segment` 以注册处理器）、`api/v1/__init__.py`。8 个接口路径/权限码/ACL 与 5.6 一致（读 `kb:dataset:list`+只读；写 `kb:segment:update`+可编辑）。
    - **通用约束**：所有写操作先 `require_dataset(edit, for_update=True)` 锁知识库行，再锁目标分段/子块行（`populate_existing`，以加锁后的最新行为准），所属文档须为 `available`，否则 409504（新增分段先判 400513 再判 409504）；读接口不受文档状态限制。跨库 ID/已删除 → 404000。**所有写入口均不信任客户端版本以外的状态**：分段/子块编辑的 `version` 不符 → 409511（并发保存同一版本只有一个成功，有单测与联调）。
    - **内容与关键词校验**：内容 `strip` 后为空、超过 `max_tokens`（通用=`general.max_tokens`；父块=`parent.max_tokens`，全文模式 10000；子块=`child.max_tokens`）、或超过 20 万字符 → 400511，`data={"max_tokens":n}`；关键词每个 `strip` 后 1~20 字，去重后 ≤10，否则 400512；父块忽略 `keywords`。
    - **编辑流程**：只写 `pending_content`（通用另写 `pending_keywords`，未传 `keywords` 则沿用当前关键词）、`index_status=updating`、`edited=true`、`version+1`，提交后投递 `{"segment_id","version"(新值)}`；索引期间 `content/embedding/tsv/search_enabled` 不变，检索继续用旧内容（单测断言）。响应与列表中 `content/keywords/char_count` 取待索引值（`updating` 与 `failed` 均如此，便于用户看到并重新保存）。`updating` 状态可再次编辑（覆盖 pending，旧版本任务被丢弃）。换入**不 bump version**（避免用户刚看到完成就遇到版本冲突）。
    - **新增分段**：仅通用；`position=max(未删除)+1`，`content` 直接写入、`edited=true`、`index_status=pending`、`search_enabled=false`，立即计入文档/知识库统计；投递 `segment.reindex`（version=1）。**新增子块**：仅父块（通用 → 400513），`generation=父块当前代`，位置追加，投递 `child.reindex`。父块处于 `updating`（正在按新内容重建子块）时，新增/编辑子块 → 409511（会随旧代被替换，直接拒绝）；删除子块不受限。
    - **启停/删除**：启停只改 `segment.enabled` 并 `refresh_search_flags`（父块整体生效，子块标志随之）、不 bump version，响应为最新 `SegmentItem`（含 children）；删除为逻辑删除（父块连同各代子块），`search_enabled=false`，`recalc_document`+`recalc_dataset`；删除后其余分段 `position` 不重排（出现间隔属正常，新增取最大值+1）。
    - **worker 任务**（`TASK_HANDLERS` 注册 `segment.reindex`/`child.reindex`/`parent.regenerate`，与 `document.process` 同一 Stream/消费组，随 `kb-worker` 启动）：
      - 通用：先在事务外调用 Embedding，再在同一事务内「锁知识库行 → 锁分段行」，确认 `version` 未变、未删除、文档仍存活且 `index_status != indexed` 后换入（content←pending、keywords←pending、清 pending、重算 `char_count/token_count`、向量、tsv（关键词权重 A、内容权重 B）、`indexed`），随后 `refresh_search_flags`、`recalc_document`、`recalc_dataset` 同事务提交。版本已变/已删除/重复投递（已 `indexed`）→ 静默丢弃，不调用模型。
      - 子块：同上，另需父块未删除且 `generation == child_generation`（父块已重建换代的旧子块任务丢弃）。
      - `parent.regenerate`：按文档 `process_rule.child` 的分隔符/最大长度切分 `pending_content`（`split_general`，不做预处理），**全部向量化完成后**才在换入事务中写入 `generation+1` 的新子块（含向量/tsv，`edited=false`）、软删旧代子块、更新父块（content、`child_generation+1`、`indexed`）并刷新标志——因此失败/丢弃不会留下半成品子块，旧子块继续参与检索。
      - 失败（模型停用/超时/HTTP 错误/维度不符，文案同 3.6 错误表）：目标行（版本未变时）标记 `index_status=failed` + `index_error`（≤300 字），旧内容继续生效，用户再次保存即重新入队；基础设施异常（DB/Redis/对象存储）抛给消费者重试（5 次后死信）。**已知局限**：基础设施异常超过重试次数时分段会停留在 `updating`，用户再次保存即可恢复（本期未加巡检）。
    - 日志：`segment/create|update|enable|disable|delete|child_create|child_update|child_delete`（失败同样记录），summary 含 dataset_id/document_id/位置/字符数。
    - 契约备注（均已落实，无需改前端）：`PUT /segments/{id}/enabled` 响应为 `SegmentItem`（前端按 `unknown` 处理，兼容）；删除接口响应 `data=null`；子块无启用状态，启停以父块为单位。
    - 测试：`tests/unit/test_segments_api.py`（14 个，真实 PG/Redis/MinIO，假 embedding；在测试中直接调用 `tasks_document.handle_task` 执行已投递的任务）：8 个接口 401/403001/只读 403311/无关 404000/功能码缺失且无副作用（AC-47）、列表（分页、关键词转义、启用筛选、父子带子块、子块命中返回父块）、AC-45（编辑中检索旧内容/tsv 不变 → 换入后新内容、已编辑、关键词权重 A）、校验 400511/400512/400001、版本冲突与并发保存只有一个成功、旧版本/重复/已删除任务丢弃、索引失败保留旧内容与再次保存恢复、模型停用原因、文档非 available 409504、新增分段（统计、pending 不可检索、换入后可检索）、AC-46 启停与删除（统计、跨库 ID 越权）、AC-65（子块编辑、父块确认 409512/重建换代/旧子块软删/新增子块/禁用父块/删除）、全文模式父块上限与重建失败保持旧子块、重新分段使待处理任务失效、处理器注册、OpenAPI。kb 全部 216 个单测通过。
    - 联调：devctl 启动 iam、kb、kb-worker + 本地假 embedding 服务，admin 登录：通用/父子各 1 个文档 → 列表；编辑分段（updating → indexed，内容/关键词/tsv 生效）；并发保存同一版本返回 `[0, 409511]`；超长/空内容 400511；新增分段（pending → indexed 可检索）；禁用分段 `search_enabled=f`；删除分段后文档分段数同步；父块不确认 409512、确认后子块重建（generation 2，新子块内容正确）；新增子块、过期版本 409511、删除子块、禁用父块后其子块 0 条可检索；父子文档新增分段 400513；无 token 401；OpenAPI 含 5 条路径。测试数据（模型/知识库/文档/分段/子块/上传记录/MinIO 对象/`stream:kb.tasks`）已清理，admin `must_change_password` 已恢复为 true，进程已停止。
  - **BE-21 已完成**（检索引擎、召回测试、召回次数、性能验证，F-15/F-16）。无新迁移、无新依赖。文件：`app/engine/{vector_store,fulltext,rerank,retriever}.py`、`app/repositories/{retrieval_repo,record_repo}.py`、`app/services/retrieval_service.py`、`app/api/v1/retrieval.py`、`app/schemas/retrieval.py`、`app/worker/hit_flush.py`、`worker.py`（注册 `hit-flush`）、`app/core/config.py`（新增 `FULLTEXT_DROP_STOPWORDS`，已同步 `.env.example`）、`app/services/dataset_service.py`（仅新增别名 `checked_retrieval_config = _checked_config`）、`scripts/perf_seed.py`。
    - **接口**：`POST /api/v1/kb/datasets/{id}/retrieve-test`、`GET /api/v1/kb/datasets/{id}/retrieve-records`，权限码 `kb:retrieval:test` + ACL 只读（超管无日常访问 → 404000）。响应结构与 5.7 一致（`retrieval_config` 多一个 `reranking_model_name`，模型被删时为 null）。前置顺序：ACL → 409506（`available_doc_count=0`）→ 覆盖设置校验（同 5.2.6，400001/400303）→ 409303 → 检索；检索失败（409303/503301）**不写**测试记录、**不计**召回次数。记录每人每库保留最近 20 条（插入后物理删除第 20 条之后的）。
    - **引擎入口（BE-22 请复用）**：
      - 对外入口是服务层 `retrieval_service.search(session, dataset, query, config, *, settings=None) -> RetrievalResult`（`app.schemas.retrieval.RetrievalResult`，字段 `query/retrieval_config/rerank_skipped/rerank_skipped_reason/records`）。调用方负责：ACL 校验（`require_dataset(..., "read")` 或内部接口的 `load_auth_context` + ACL）、知识库未删除、"无可用文档"的处理（召回测试 409506；内部接口按 5.9.1 返回空 records，**`search` 本身不判断**）。`search` 内部：向量模型非启用 → `BizError(409303)`；查询向量走 Redis 缓存 `kb:qemb:{model_id}:{sha256(query)}`（600s，Redis 故障自动降级为实时调用）；Rerank 模型缺失/停用 → 跳过重排（`rerank_skipped=true`，原因"重排模型不可用，已跳过重排"，混合-Rerank 退化为权重 0.7）；Embedding/Rerank 调用失败或维度与模型配置不一致 → `BizError(503301, "模型服务调用失败：…")`（不会以空结果代替）；成功后调用 `record_hits` 计入召回次数。**注意**：`search` 在调用模型前会 `session.commit()` 结束只读事务以释放连接（会话 `expire_on_commit=False`，已加载的 `Dataset` 属性仍可读）。
      - 生效设置：`retrieval_service.effective_config(dataset, override: RetrievalConfig | None) -> RetrievalConfig`（覆盖时整体替换；召回测试用 `checked_retrieval_config` 先规范化并校验 Rerank 模型）。内部接口的 `overrides`（`search_method/top_k/score_threshold/reranking_enable`）由 BE-22 自行合并到默认设置后构造完整 `RetrievalConfig`（`score_threshold` 传入即 `score_threshold_enabled=true`；知识库默认设置里没保存 `reranking_model_id` 时覆盖 `reranking_enable=true` 会因无模型而跳过重排，`rerank_skipped=true`）。
      - 底层 `engine.retriever.retrieve(session, *, dataset_id, chunk_mode, query, config, embed_query, reranker=None, store=None, candidate_max=100) -> RetrievalOutcome(records, rerank_skipped, rerank_skipped_reason)`：纯引擎，不判 ACL/模型表；`embed_query: Callable[[str], Awaitable[Sequence[float]]]`（压测用它预置查询向量）；`reranker: Callable[[str, list[str]], Awaitable[list[float]]] | None`（`config.needs_rerank_model()` 为真而传 None = 重排不可用）；`store: VectorStore`（Protocol：`search(dataset_id, table, query_vector, limit)`、`score_by_ids(...)`，本期 `PgVectorStore(session)`，将来换 Qdrant 只需新增实现）。`chunk_mode == "parent_child"` 检索子块并按父块聚合，否则检索通用分段。
      - `RecallRecord`：`segment_id/position/segment_type(general|parent)/content/score(4 位小数)/keywords/document{id,name}/child_chunks[{id,position,content,score}]`；排序得分降序、同分 ID 升序；父子聚合：父块得分取命中子块最高分，子块按得分降序附带，Top K 按父块计，阈值按子块得分。
    - **实现细节与偏离**：①候选数、混合加权补算、重排（任一分值越界则整体 sigmoid；服务端少返回的候选按最低分）、阈值均按 3.7；混合-Rerank 模式对两路候选并集（最多 2n 条）整体重排，未再截断。②全文检索 tsquery 作为绑定参数传入 `to_tsquery('simple', :tsq)`，词数上限 50；**新增查询侧停用词过滤**（`FULLTEXT_DROP_STOPWORDS`，默认开，过滤后为空则回退不过滤）：压测发现高频虚词（"有""的"）会让 OR 查询命中大半个知识库，`ts_rank_cd` 开销剧增，属于方案内的查询优化，不改索引/表结构，可随时关闭。③SQL 必须用裸布尔 `where(t.search_enabled)`（不能 `.is_(True)` 渲染成 `IS true`）：否则规划器无法证明蕴含部分索引谓词，`ix_seg_search`/`GIN(tsv) WHERE search_enabled` 都用不上（压测踩坑，已在 `fulltext.py` 注释）。④`retrieve()` 开头执行 `SET LOCAL plan_cache_mode = force_custom_plan`，避免 asyncpg 预编译语句在第 6 次后转通用计划，导致 `to_tsquery(:param)` 按行重复求值/索引选择偏差。⑤jieba 首次初始化放线程（`asyncio.to_thread`）。⑥jieba 词典里没有"年假"，会被切成"年""假"两个单字（索引与查询两侧一致，召回可用但精度差）；建议运维通过 `JIEBA_USER_DICT` 补充业务词。
    - **召回次数**：`retrieval_service.record_hits` 对返回的每个通用分段/父块 `HINCRBY kb:hits:segment <id> 1`，其文档 `HINCRBY kb:hits:document <doc_id> 1`（文档计数 = 其分段被返回的累计次数）；Redis 故障只记日志不影响检索。`worker/hit_flush.py`：每 `HIT_FLUSH_INTERVAL_SECONDS`（默认 60）秒一轮；Redis 锁 `kb:hits:flush:lock`（120s）防多实例并发 → 先处理遗留临时 key（崩溃恢复）→ `RENAME` 当前 key 到 `kb:hits:{kind}:flush:{uuid}`（此后新计数写新 key，不丢）→ 单事务 `UPDATE ... FROM unnest(ids, ns)` 累加 → 提交后删临时 key（提交与删除之间崩溃最多重复累加一批）。已删除的分段 ID 自然无匹配行。
    - **性能验证（强制项，结论：不达标，需你决策）**
      - 环境：本机 docker `pgvector/pgvector:pg16`（pgvector 0.8.7，**默认配置**：`shared_buffers=128MB`、`work_mem=4MB`、`max_parallel_workers_per_gather=2`），8 核/15GB，库 `kbp_test`。工具：`backend/services/kb/scripts/perf_seed.py`（`seed/bench/clean`，仅允许库名含 `test`）。
      - 数据：库内两个知识库——通用分段库 **10 万分段** + 父子分段库 **10 万子块（2.5 万父块）**；1024 维 halfvec 随机向量（服务端 `random()` 生成）；文本为 jieba 词典按真实词频随机抽词拼成（通用每段 120 词、子块 60 词、父块 240 词，tsv 内容权重 B）；`ANALYZE` 后测量；`segment`+`child_chunk` 表含索引共 1017MB（远大于 shared_buffers，依赖 OS 缓存）。
      - 方法：直接调用 `engine.retriever.retrieve`（查询向量预置，**不含**向量/重排模型调用；含 jieba 分词、全部 SQL、结果组装），top_k=5，17 条查询（8 条自然语句 + 8 条按词频抽词的随机查询 + 1 条全高频词最坏情况）轮流，预热 3 次后每组 60 次，单连接串行；并发另测 4 并发（每组 24 次）。
      - 结果（单次延迟，ms，**最终代码**；P95 目标 ≤ 500）：

        | 库 | 检索方式 | P50 | P95 | max | 达标 |
        |---|---|---|---|---|---|
        | 通用 10 万 | 向量 | 646 | 674 | 706 | 否 |
        | 通用 10 万 | 全文 | 793 | 1043 | 1056 | 否 |
        | 通用 10 万 | 混合 | 1174 | 1418 | 1508 | 否 |
        | 父子 10 万子块 | 向量 | 244 | 254 | 270 | 是 |
        | 父子 10 万子块 | 全文 | 103 | 274 | 287 | 是 |
        | 父子 10 万子块 | 混合 | 334 | 525 | 530 | 否（略超）|

        4 并发：通用向量 P50/P95 = 805/946、全文 852/1000、混合 1204/1413；父子向量 332/423、全文 74/290、混合 440/599（8 核机器上基本不退化，说明瓶颈是单查询 CPU）。全高频词全文最坏情况：通用 P50 832（max 846）、父子 P50 181。
      - 原因分析（EXPLAIN）：①**向量**：10 万行 × 1024 维 halfvec 精确距离是 CPU 密集（每行约 6.5µs，含 TOAST 读取）。规划器对通用库选了单进程 `Index Scan using ix_seg_search`（~650ms）；同一语句强制并行顺序扫描（`Parallel Seq Scan` + 2 workers）约 250ms——也就是通用向量检索的结果取决于规划器选哪种计划（父子库向量 ~244ms，与并行计划耗时吻合，推测走了并行计划，未逐条 EXPLAIN 验证）。②**全文**：`ts_rank_cd` 需要对所有 `tsv @@ q` 命中行逐行计算，约 25µs/行；查询词含中高频词（如"员工""公司""标准""管理"，在 10 万段中各命中 20%~60%）时命中数万行即达 0.5~1s，命中几千行的查询只要 30~120ms。去掉虚词/单字后的 P95 仍超标。③**混合** = 向量 + 全文 + 补算，三者串行相加。
      - **可选方案（请决策，本次未擅自更换）**：
        A. **按模型建 HNSW 索引**（推荐）：在测试库对同一份 10 万行数据手工建了 `CREATE INDEX ... USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops) WHERE search_enabled`（构建单线程 2 分 39 秒，索引 260MB），同一向量查询（`hnsw.ef_search=100`、`iterative_scan=relaxed_order`）执行时间 **8~20ms**。该索引要求固定维度的表达式与谓词，需要给 `segment`/`child_chunk` 冗余 `embedding_model_id`（或按模型分区），每新增一种维度的模型建一个索引，查询必须使用相同表达式；属于**表结构/迁移变更**，需契约变更。HNSW 为近似检索，召回率需验证，且索引构建/维护成本随写入增长。
        B. **换 Qdrant**：检索层已有 `VectorStore` 抽象，新增实现即可；需引入中间件、双写一致性与"停用/删除即不可检索"的过滤同步，工作量最大。
        C. **仅调优现有方案**（不改表）：DB 配置 `shared_buffers`/`max_parallel_workers_per_gather`/`random_page_cost`、`ALTER COLUMN embedding SET STORAGE MAIN`（避免 TOAST，未实测）等，可让通用向量稳定走并行计划（~250ms 级），但全文最坏情况与混合仍难稳定到 500ms 内。
        D. **全文侧**：缩小全文候选（例如要求命中词数下限/只对向量候选与关键词候选取并集后再 rank，或改用 `ts_rank` 而非 `ts_rank_cd`，实测仅快 ~30%），或引入 BM25 方案（ParadeDB/ES）；也可只对 5 万分段以下的库承诺 500ms。
        E. 保持现状，调整验收口径：当前数据下，**≤ 3 万分段的库**精确检索可稳定 <200ms；10 万分段需 A 才能满足 500ms。
      - 压测数据已用 `perf_seed.py clean` 清理（并 `VACUUM`），临时 HNSW 索引已删除，`kbp_test` 无遗留。
    - 测试：`tests/unit/test_retrieval.py`（21 个）：tsquery 构造（引号/反斜杠/标点/去重/词数上限）、候选数与 sigmoid、权限 401/403001/404000（含超管）与只读用户可测试（AC-50）、校验 400001/400303/409506/409303（三种方式都拒绝）、向量排序/Top K 边界/阈值（AC-49，0.9/0.8/0.6/0.4/0.3 → 3 条）、知识库间隔离与关键词、全文（两词命中排第一、无命中、注入/特殊字符安全）、混合加权（w=0/0.3/0.7/1 与单路得分一致、缺失一路补算）、可见性（禁用文档/禁用分段/处理中文档不返回；经真实接口停用文档、禁用分段、删除分段后立即不可检索，AC-42/46/60）、父子聚合（AC-64：一个父块多子块合并、得分取最高、子块降序、Top K 按父块计、阈值按子块、禁用父块不返回、全文/混合同样聚合）、Rerank（开启取 relevance_score、sigmoid、阈值作用于重排后得分、关闭不调用；混合-Rerank 模式；父子重排文本为子块；停用/删除模型降级与提示、覆盖设置用停用模型 400303、混合-Rerank 降级等于权重 0.7）、模型异常（embedding 超时/5xx、维度不一致、Rerank 失败均 503301 且不写记录/不计次数；全文不受 embedding 影响）、查询向量缓存、记录保留 20 条且仅本人可见、召回次数累计与落库（锁、遗留临时 key、重复执行不重复累加、并发累计、父块与文档计数）。kb 全部 237 个单测通过。
    - 联调：devctl 启动 iam、kb、kb-worker（`HIT_FLUSH_INTERVAL_SECONDS=5`）+ 本地假 embedding/rerank 服务（16 维字符二元组哈希向量；词重叠重排；查询含 `BOOM` 时 embedding 返回 500、含 `RRFAIL` 时 rerank 返回 500），admin 登录：通用库（4 分段）与父子库（4 父块/8 子块）经真实流水线入库后，三种检索方式、Top K=1/3/20、阈值 0.5/0.99、无关词无命中、权重 0/1、Rerank 开关（向量/全文/混合-Rerank）、父子聚合（父块得分=最高子块分、子块降序）、校验（Top K 0/21、空问题、501 字 → 400001；Rerank 无模型 → 400303）、401、不存在的库 404000、409506；embedding 500 → 503301"向量模型返回错误（HTTP 500：boom）"、rerank 500 → 503301"重排模型返回错误"、全文不受 embedding 故障影响；保存默认设置时 Rerank 模型已停用 → 400303，启用后保存成功，停用后召回测试返回 `rerank_skipped=true` 与提示并按向量结果返回；向量模型停用后三种方式都 409303、恢复后正常；记录与召回次数落库（segment/document `hit_count` 正确累加、Redis 计数清空）；OpenAPI 含两条新路径。测试数据（模型/知识库/文档/分段/子块/上传记录/MinIO 对象/Redis 计数与缓存）已清理，admin `must_change_password` 已恢复为 true，进程（含假模型服务）已停止。
  - **BE-23 已完成**（管理视图与所有权转移，F-20）。无新迁移、无新依赖、无新配置项。
    - 文件：`app/api/v1/admin.py`（`/kb/admin/...` 共 9 条）、`app/api/v1/datasets.py`（追加 `POST /datasets/{id}/transfer`，`kb:dataset:transfer`）、`app/schemas/admin.py`、`app/repositories/admin_repo.py`、`app/services/{admin_service,transfer_service,audit_log}.py`；`api/v1/__init__.py` 挂载。为复用做了小重构：`document_service.list_documents_unchecked/get_detail_unchecked`、`segment_service.list_segments_unchecked`（不校验 ACL，仅由管理视图在自己的可见性校验后调用）、`assignment_service.list_for_dataset`、`dataset_service.build_detail`、`assignment_repo.descendant_cond`、`dataset_repo.taken_names`。
    - 管理视图可见性：`admin_repo.visible_cond` = 未删除 ∧ `data_scope_filter(company_id, dept_id, owner_id)`，独立于日常 ACL；SELF 仅指所有者为本人，不套用 iam 的组织树/用户 SELF 特例（F-05 规则 8）；不可见/不存在统一 404000。管理视图没有任何写、下载、召回测试路由；用日常接口访问他人知识库仍被 ACL 拒绝（404000），管理员的“我的知识库”不受影响。
    - 审计（5.8.1）：`admin_service.should_audit`——`audit_entry=true` 必记并刷新 key；否则 `SET kb:audit:{uid}:{ds|doc}:{id} NX EX 1800` 成功才记；Redis 不可用时按“记录”处理。仅在可见性与文档归属校验通过之后记录，日志直接用 `emit_oplog`（dataset/admin_view，target=知识库；分段 summary 含 `document_id`、`document_name`）。文档列表/详情不记录。
    - 转移（3.8）：`transfer_service.transfer` 为共用内核（400322、409321、更新 owner/company/dept、version+1）。接收人用 `load_auth_context` 判定（不存在/停用/删除/组织链停用 → 400321）；管理员转移用 `in_data_scope(接收人 company_id/org_id/user_id)`，所有者自行转移用 `assignment_repo.org_in_scope`（所属公司及下属；集团节点不限）。判定顺序：404000 → 409001（仅单个）→ 400321 → 400322 → 409321。单个转移 `FOR UPDATE` + version；批量不带 version，`from_user` 名下范围内知识库按 id 升序行锁，同名检查一次查询完成，任一冲突整体回滚并返回 `data.conflicts`（被转移的知识库）。`dataset_ids` 中含范围外/非 from_user 名下/已删除 id → 404000（不泄露存在性）；缺省 = from_user 名下范围内全部，无可转移时返回 `transferred: 0`；`dataset_ids` 限 1~500 个。并发下唯一索引冲突兜底映射 409321。日志 dataset/transfer，摘要 `{before:{owner_*,company_*,dept_*}, after:{…}}`；批量每个知识库一条成功日志，失败只记一条 failure。
    - 响应：管理员单个转移返回转移后的 `AdminDatasetItem`；自行转移返回 `DatasetDetail`（调用者已无访问权时 `my_permission` 按 `read` 填充，仅为占位）。`receivers` 与 `owners` 按 5.8（owners 按知识库数降序、副本缺失的所有者显示“未知用户/deleted”）。
    - 测试：`tests/unit/test_admin_api.py`（22 个，另扩展 `helpers.py` 的 `X-Test-Scope` 头）：权限码 401/403001 互不替代；AC-17 七种范围 + AC-18 并集 + 直访不可见 404000 + AC-26 我的知识库只含 K1；AC-19；列表字段与全部筛选（含 LIKE 转义、副本缺失、待交接）；详情内容；文档/分段只读与归属校验；审计规则（首次、翻页不记、audit_entry、窗口过期、不同操作人、失败不记、Redis 故障仍记）；AC-67（日常写/召回/下载全部 404000，管理路由无写入口）；AC-68/69（范围外/停用/删除/不存在接收人、400322、409321 data、409001、分配保持、原所有者 404000、批量冲突整体回滚、缺省范围、逐条日志）；receivers/owners；自行转移（403311/404000/下属公司/集团本部不限/冲突）。kb 全量 259 个通过。
    - 联调：devctl 启动 iam、kb、kb-worker，通过 iam 接口创建临时组织（A 公司/A1 子公司/B 公司/研发/测试/产品/前端组）、角色、用户后 curl 验证：7 种数据范围可见性与直访、我的知识库不含管理视图可见项、日常写接口/召回/下载被拒、审计规则（含 Redis key TTL ≤1800）、单个/批量转移全部分支、所有者自行转移，全部符合。验证后已清理：临时知识库（逻辑删除）、用户/角色/组织（逻辑删除）、临时模型；admin 恢复 `Admin12345` + `must_change_password=true`；未执行 downgrade；开发 Redis 清除 `kb:audit:*`、`authz:ctx:*` 并 `INCR authz:epoch`（开发会话需重新登录）；`stream:oplog` 留有验证产生的 dataset 事件（测试数据）。开发库 kb 原本没有默认 embedding 模型，联调时临时建过一个并已删除。
  - **BE-22 已完成**（kb 内部接口，F-17/F-18 支撑）。无新迁移、无新依赖、无新配置项。
    - 文件：`app/api/internal/{retrieval,access,stats}.py`（汇总路由 `__init__.py` 已 include，统一 `require_internal`，缺失/错误令牌 401901，用户 JWT 不能替代）、`app/schemas/internal.py`、`app/services/internal_service.py`、`app/repositories/internal_repo.py`。
    - 检索 `POST /internal/v1/datasets/{id}/retrieve`：`load_auth_context(user_id)` 不存在/停用/删除/组织链停用 → 404000；`require_dataset(read)` 实时 ACL（不可访问/已删除 → 404000，移除分配或调岗立即生效）；`overrides` 合并到知识库默认设置（不修改知识库）：`score_threshold` 传入即开启阈值（按 2 位小数四舍五入），`top_k` 1~20、`search_method` 取值非法 → 400001，合并后 `normalized()`；顺序：向量模型非启用 → 409303（先于“无可用文档”）→ `available_doc_count<=0` 返回空 `records`（不报错）→ 仅调用 `retrieval_service.search`（计入召回次数，模型失败 503301）。响应 = `RetrievalResult` + `dataset:{id,name}`；`source`（open_api/chat）仅校验。
    - `POST /internal/v1/access/accessible-datasets`：每个用户实时 `load_auth_context`（并发 20），不可用 → `[]`；`accessible_dataset_ids_subquery` 计算，可与 `dataset_ids` 取交集（≤500）；`user_ids` 去重、≤100；key 为字符串用户 id。`POST /internal/v1/datasets/brief`：ids ≤500，含已删除（`is_deleted`），不存在的 id 不返回。
    - `GET /internal/v1/stats/datasets`：`dept_id` 或 `owner_id` 二选一（否则 400001）；owner 为未删除知识库数；**dept 为该节点及其全部下级节点（org_ref 子树）下未删除知识库数**（知识库 `dept_id` = 所有者主组织；副本缺该节点时按直属计数），与 iam `downstream.kb_dataset_count_by_dept/by_owner`（`params={"dept_id"|"owner_id"}`，读取 `data.count`）一致。
    - 测试：`tests/unit/test_internal_api.py`（7 个）：令牌缺失/错误/用户 JWT → 401901；检索成功、overrides、不改默认设置、召回计数；实时 ACL（无分配、分配、移除即时失效、部门分配与调岗、停用/删除/不存在用户、不存在/已删除知识库）；409303、空库空 records、400001 校验、503301；accessible（交集、停用用户为空、去重、上限）；brief、stats。
    - 联调：devctl 启动 iam（`KB_STATS_ENABLED=true`）+ kb + kb-worker，以 `X-Internal-Token` curl 验证上述接口；iam 侧：用户影响提示 `owned_dataset_count=1`（`degraded=true` 仅因 open 未部署，api_key_count 为空）；用户停用后其 accessible 为空、检索 404000，而被分配用户不受影响；组织删除在所有者已删除、仅剩知识库时被 `存在知识库` 拦截，删除知识库后可删除。已清理：临时知识库/用户/角色/组织（逻辑删除）、临时模型；admin 恢复 `Admin12345` + `must_change_password=true`；未 downgrade；开发 Redis 清除 `authz:ctx:*`、`kb:audit:*` 并 `INCR authz:epoch`。

  - **BE-21b 已完成**（检索性能优化，F-15/F-16/F-18 非功能；kb + kb-worker）。迁移 `0002_vector_index_support`；无新依赖。**3.10.6 验收：除"随机向量 recall"（原文标注"记录"）外全部达标，见下文数据；随机向量 recall 极低，请决策是否接受。**
    - **文件**：迁移 `alembic/versions/0002_vector_index_support.py`、`alembic/env.py`（`transaction_per_migration=True` 并在建 schema 后 `commit()`，否则迁移里的 `autocommit_block` 断言失败）；`app/models/{segment,child_chunk}.py`（`embedding_model_id`）；`app/engine/{vector_store,fulltext,retriever}.py`；新增 `app/worker/{vector_index,fts_stats}.py`；`app/worker/{tasks_document,tasks_segment,main_loop}.py`、`app/repositories/segment_repo.py`（写向量同时写 `embedding_model_id`；`write_embeddings`/`insert_children` 新增必填关键字参数 `model_id`）；`app/services/{model_service,retrieval_service}.py`；`worker.py`；`app/core/config.py`、`.env.example`；`scripts/perf_seed.py`（重写：`seed --scenario s1|s2`、`index`、`fts`、`explain`、`bench [--only big|small] [--concurrency]`、`recall [--kind]`、`overlap`、`writebench --label`、`clean`）；`docker-compose.yml`（3.10.3 本地参数 + `shm_size: 2gb`）；`deploy/prod/postgres-params.example.conf`（生产参数样例，BE-29 据此落地）；测试 `tests/unit/test_vector_perf.py`。
    - **向量检索**：`PgVectorStore(session, model_id=, dimension=, units=, settings=)`；路径选择、回退、`kb:metrics:hnsw_fallback`（进程内 `vector_store.METRICS` 同时累计，压测读取）、索引有效性缓存（60 秒，`valid_indexes` 同时解析索引定义里的 `halfvec(dim)`，与模型维度不符视为无效）均按 3.10.1。与方案的差异：①HNSW 查询不再用 `MATERIALIZED` CTE 做外层排序，而是在 Python 中按（距离，ID）重排（等价，少一层 SQL）；②三个 `SET LOCAL hnsw.*` 合并为一条 `SELECT set_config(..., true)`（一次往返）；③`units` 取 `dataset.segment_count`（父子库取 `child_segment_count`，含已禁用单元，近似值），`retrieve()` 新增的可选参数 `embedding_model_id/dimension/units/session_factory/settings` 均有默认值，旧调用方式（含 BE-22 的 `retrieval_service.search`）语义不变，`search` 内部自行传入；④新增 `Explain` 语句与 `PgVectorStore.explain(...)`，供测试/压测断言索引命中。
    - **索引维护（kb-worker）**：`vector_index.reconcile(model_id=None)`：独立 autocommit 连接 + `kb:vindex:lock:{model_id}`（TTL 2 小时，拿不到锁则跳过该模型，因此不会误删其他 worker 正在 CONCURRENTLY 构建的索引）；无效/维度不符先 `DROP INDEX CONCURRENTLY` 再建；已删除、非 Embedding、维度 > 4000 的模型的索引删除。任务 `vector.ensure_index`（`model_service` 在新建启用、变为启用、改维度、**删除**后提交时发布）；worker 启动时立即对账一次，之后每 `VECTOR_INDEX_RECONCILE_SECONDS`（`run_periodic` 单实例）。与方案的差异：未在连接上 `SET maintenance_work_mem / max_parallel_maintenance_workers`，沿用服务端参数（3.10.3 已给出同样的值，少一处重复配置）。
    - **全文裁剪**：`fts_stats.compute_common_terms`（`ts_stat` + Redis 哈希 `kb:fts:common:{id}`，词 → 文档频率，TTL 24 小时，`""` 字段为"已计算"哨兵）、任务 `fts.common_terms`、每 `FULLTEXT_COMMON_TERMS_REFRESH_SECONDS` 刷新（词表缺失或知识库 `updated_at` 晚于上次计算的大库）；检索侧缺失词表时去重触发任务（5 分钟），本次按"完整 OR + 候选上限"兜底；`fulltext_search_pruned`：有稀有词用 OR 候选；全常见词用 AND，为空退化为最稀有的常见词；只对候选用完整查询 `ts_rank_cd` 打分；候选达上限记 `kb:metrics:fts_cap_hit`。
    - **混合并行**：`retrieve(..., session_factory=...)` 时向量路与全文路各用独立会话并发（含 embedding 调用与 jieba 分词并行），补算阶段两路也并发；任一路失败取消另一路并抛出原异常；未传 `session_factory` 退化为串行（结果一致，单测已验证）。kb `DB_POOL_SIZE` 默认 20。
    - **存储**：`embedding SET STORAGE MAIN` + `toast_tuple_target=8160`，实测保留：2 万行精确扫描（本机测试库，1024 维 halfvec，20 条查询 × 60 次）默认存储 P50/P95 = 83.5/86.2ms（另一轮 89.2/96.8），MAIN 18.7/21.9ms（另一轮 19.5/22.2），改善约 75%（门槛 20%）。
    - **压测环境（务必注意）**：本机 8 核 / 15GB，PostgreSQL 容器按 3.10.3 本地列配置（`shared_buffers=1GB` 等）；**数据盘为机械盘（`lsblk` ROTA=1，冷读约 12ms/页）**，且内存与其他项目共用（压测期间 swap 已使用 4GB）。因此：①冷缓存时单次检索可达 20 秒以上（第一次读 HNSW 索引页），下表为**预热后**数据（每条查询先完整执行一遍，再测 60 次；建索引后用 `pg_prewarm` 读入 OS 缓存）；②缓存被其他负载挤出时会出现个别 1~4 秒的离群值，**生产必须按 3.10.3 配置内存并使用 SSD**。数据：S2（按 `perf_seed.py seed --scenario s2`）= 1024 维模型 3：通用分段表 32 万行（s1 随机向量 10 万、2 个聚类大库各 10 万、10 个 2,000 的小库）+ 子块表 32 万行（s1 随机 10 万、2 个聚类大库、10 个小库）；768 维模型 4：通用 10 万聚类库；表含索引共 4.3GB。
    - **压测结果（最终参数：`HNSW_EF_SEARCH=200`、`HNSW_EF_CONSTRUCTION=128`、`FULLTEXT_COMMON_TERM_RATIO=0.15`、`FULLTEXT_CANDIDATE_CAP=10000`；top_k=5，17 条查询，预热后每组 60 次，单连接串行，单次延迟 P50/P95 ms，门槛 P95 ≤ 500）**：

      | 库（均 10 万单元） | 向量 | 全文 | 混合 | 达标 |
      |---|---|---|---|---|
      | 通用，随机向量（s1） | 14 / 19 | 206 / 298 | 226 / 325 | 是 |
      | 通用，聚类 big1 | 10 / 14 | 247 / 386 | 264 / 410 | 是 |
      | 通用，聚类 big3 | 14 / 18 | 248 / 386 | 265 / 414 | 是 |
      | 通用，768 维模型（m2，独立索引） | 9 / 15 | 245 / 320 | 246 / 335 | 是 |
      | 父子，随机向量（s1） | 21 / 28 | 80 / 168 | 118 / 215 | 是 |
      | 父子，聚类 big2 | 13 / 18 | 84 / 203 | 104 / 222 | 是 |
      | 父子，聚类 big4 | 12 / 17 | 82 / 203 | 131 / 285 | 是 |
      | 小库（2,000，精确路径，20 个库汇总）通用 | 12 / 17 | 17 / 23 | 25 / 33 | 是（≤150） |
      | 小库父子 | 12 / 16 | 13 / 20 | 23 / 32 | 是（≤150） |

      4 并发（每组 24 次，参考值 ≤700）：通用大库混合 P95 336~423、全文 315~400、向量 19~72；父子混合 227~236、全文 187~223、向量 25~36。HNSW 路径 1078 次检索回退 0 次（回退比例 0% ≤ 1%）。`fts_cap_hit`：1078 次中约 340 次（候选达到 10000 上限，多为全文/混合的通用大库）。**通用库混合 P95 最高 414ms，余量不大**（全文候选 10000 行 × ts_rank_cd ≈ 250ms）；若现场更慢，可把 `FULLTEXT_CANDIDATE_CAP` 降到 6000（重合度会下降，见下）。
    - **HNSW 召回率（recall@10，与精确检索对比，每库 100 条查询向量）**：聚类组（5 个大库共 500 条）**均值 0.998、单条最低 0.90（达标：≥0.95 / ≥0.80）**，各库均值 0.995~0.999；调参过程：`ef_search=100, ef_construction=64` 均值 0.908、最低 0.0（个别查询落入错误的簇，真实最近邻相似度 0.99 而 HNSW 返回 0.12）；`ef_search=200` 均值 0.957、最低 0.0；`ef_search=400` 均值 0.977、最低 0.7；**`ef_construction=128` 重建 + `ef_search=200`** 达标。**随机组（2 个库共 200 条）均值 0.02（ef_search=100：0.02；200：0.02；1000：0.08），未达到 ≥0.90 的期望（原文标注"记录"）**：10 万条 1024 维均匀随机向量的两两余弦几乎相同（距离集中），"最近邻"本身不稳定，任何 HNSW 参数都无法逼近精确结果；这是向量索引的已知最坏情况，不代表真实 embedding（真实向量有结构，聚类组接近真实）。请决策：接受（随机向量只用于压测最坏延迟，延迟已达标）还是要求其他方案。
    - **全文裁剪质量（17 条查询，Top10 与未裁剪的重合度；结果条数 ≥ min(TopK, 裁剪前条数) 全部满足，违例 0）**：最终参数下 7 个大库均值 **0.911**（通用 0.86~0.90，父子 0.94~0.96；门槛 ≥ 0.80，达标）。调参过程（7 库平均重合度）：ratio 0.05 / cap 3000 = 0.716（不达标）；ratio 0.02 / cap 3000 = 0.486（更差：常见词越多被裁掉的越多）；ratio 0.15 / cap 3000 = 0.729；ratio 0.05 / cap 10000 = 0.782；**ratio 0.15 / cap 10000 = 0.911**。代价：全文/混合 P95 由 cap 3000 时的 150~160ms（通用）升到 380~410ms。语义变化：只命中常见词、不含任何稀有词的行不再进入候选（3.10.4 已声明）。压测文本是按词频随机抽词拼成的合成数据，`ts_rank_cd` 平分较多，真实文本的重合度可能更好，但未验证。
    - **EXPLAIN（默认规划器设置，S2 数据）**：7 个大库向量查询均为 `Index Scan using ix_seg_hnsw_m3 / ix_child_hnsw_m3 / ix_seg_hnsw_m4`（`Order By: (embedding)::halfvec(1024) <=> ...`，无 Seq Scan）；小库精确路径为 `Index Scan using ix_seg_search / ix_child_search` + Sort。单测中同样断言（`enable_seqscan=off`，3000 行）。
    - **建索引与写入开销**：HNSW 构建（`CREATE INDEX CONCURRENTLY`，maintenance_work_mem=1GB，并行 4）：`ef_construction=64`：32 万行 101s / 113s（索引 833MB），10 万行（768 维）31s（195MB）；`ef_construction=128`：32 万行 151s / 167s，10 万行 47s。**索引阶段写入 1 万单元（模拟 worker：分批写向量与 `embedding_model_id`，再置 `search_enabled`）：无索引 6.0s（写向量 2.7s + 置可见 3.3s），有索引（64 万行的图）87.6s（置可见阶段 84.9s，插入 HNSW 约 8.5ms/行），增幅约 14.6 倍，超过 2 倍的提示线**：HNSW 插入发生在 `search_enabled` 置 true 时（`refresh_search_flags`），一个文档的分段通常几十到几百个，增加约 0.3~3 秒；批量导入大文档时索引阶段会明显变慢（本机机械盘与内存紧张也放大了该值）。建议 BE-29 压测时在 SSD 环境复测。
    - **单测**：`tests/unit/test_vector_perf.py`（16 个）：写向量同时写 `embedding_model_id`；路径选择（小库精确、维度 > 4000 精确、无索引精确、大库 HNSW 并与精确 recall@10 ≥ 0.9、HNSW 不足回退精确并计数）；无效索引走精确且对账后重建；EXPLAIN 断言（通用/子块 HNSW 与精确各命中对应索引）；扫描上限夹取；对账（创建、幂等、删除模型删索引、改维度重建、维度 > 4000 与 Rerank 模型不建、锁被占用跳过并释放）；建索引 SQL 与检索表达式一致；任务处理器；全文裁剪（稀有词/全常见词 AND/AND 为空退化/词表缺失兜底/上限命中计数，得分与未裁剪一致）；常见词表计算与 Redis 读取、刷新、缺失时去重触发任务；混合并行与串行结果一致（权重 0/0.5/1）、并行一路失败异常传播；模型新建/启用/删除触发 `vector.ensure_index`（停用的 Embedding、Rerank 不触发）。kb 全部 282 个单测通过（原 266 个全部保持通过）。
    - **联调**：迁移 0002 在测试库 upgrade → downgrade -1 → upgrade 通过（downgrade 先 `DROP INDEX CONCURRENTLY` 全部 HNSW 索引、恢复存储策略为 halfvec 类型默认值 EXTERNAL，再删列），开发库仅 upgrade。devctl 启动 iam、kb、kb-worker + 本地假 embedding/rerank 服务（16 维；`BOOM`/`RRFAIL` 触发 500）：创建启用的 Embedding 模型后 worker 数秒内自动建出 `ix_seg_hnsw_m{id}`、`ix_child_hnsw_m{id}`，删除模型后自动删除；通用库与父子库经真实流水线入库后，向量/全文/混合、Top K=1/20、阈值 1.0 与 0、父子聚合、混合-Rerank 与向量+Rerank、Rerank 模型停用（400303）、embedding 500 → 503301（全文不受影响）、Embedding 模型停用 → 409303（三种方式都拒绝）及恢复，全部符合；OpenAPI 47 条路径正常。（小库走精确路径，联调数据量不触发 HNSW 路径，HNSW 路径由压测与单测覆盖。）
    - **清理**：压测数据、压测模型、HNSW 索引、辅助表（`public.perf_center_*`）与 `pg_prewarm` 扩展已清理，`kbp_test` 无遗留；开发库联调产生的知识库/模型已逻辑删除、HNSW 索引已删除，admin 已恢复 `must_change_password=true`，开发 Redis 清除 `kb:qemb:*`、`authz:ctx:*` 并 `INCR authz:epoch`；进程均已停止；kbp-postgres 容器已按 3.10.3 重建（数据卷保留）。
    - **遗留与风险**：①随机向量 recall 极低（见上，请决策）；②混合 P95 最高 414ms，余量小，且依赖预热与足够内存/SSD；③有索引时写入成本显著增加（14.6 倍）；④`units` 近似值含禁用单元，不影响正确性（HNSW 条数不足会回退精确）；⑤生产 DB 账号需为 `kb` schema 表的 owner 才能建索引（BE-29 授权 SQL）；⑥docker 容器 `shm_size` 必须 ≥ `maintenance_work_mem`（本地 2gb，生产样例已注明）；⑦`env.py` 改为每个迁移一个事务（`transaction_per_migration`），对 0001 无影响。

  - 缺陷修复（M2 QA）：①BUG-15 根因是 `antd/locale/zh_CN` 为 CJS，经 Vite 预构建后被包成 `{ default }`，ConfigProvider 拿不到 locale（所有 antd 内置文案含确认框取消按钮回退英文）；改为从 ESM 入口 `antd/es/locale/zh_CN` 引入（统一封装在 `src/locale.ts`），不逐处手写 `cancelText`。②BUG-16 口径：上传向导/重新分段中，通用分段“最大长度”与父子分段“子块最大长度”默认值取 `min(默认值 1024/512, 所用 Embedding 模型 max_input_tokens)`，父块不受约束、保持 1024；拿不到模型上限时回退默认值；“恢复默认”同口径；用户手动改过（或已有上次设置）的值不会被覆盖。③路由页面改为 `React.lazy` + `Suspense` 按路由拆分。
