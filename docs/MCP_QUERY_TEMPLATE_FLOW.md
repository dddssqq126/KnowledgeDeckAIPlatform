# MCP Query Template Flow

這份文件說明 KnowledgeDeck 目前的 MCP Query Template 流程怎麼用，以及使用者問問題時，系統如何判斷要不要呼叫 MCP tool 取得資料。

目前 V1 的重點是安全地把固定 SQL template 包成可控工具，而不是讓 LLM 自由產生 SQL。實作核心在：

- `backend/schemas/query_card.py`
- `backend/sql_templates/registry.py`
- `backend/agents/query_planner.py`
- `backend/agents/query_validator.py`
- `backend/mcp_servers/business_query_server.py`
- `backend/agents/result_verifier.py`
- `backend/agents/synthesizer.py`
- `backend/services/query_pipeline.py`

## 核心原則

1. LLM 不產生 SQL。
2. Route 不直接處理 Planner / Validator / Executor 細節。
3. SQL 只能來自 `SQL_TEMPLATE_REGISTRY`。
4. MCP tool 不接受 `raw_sql`，也不接受任意 SQL。
5. 查詢前必須通過 QueryPlan validator。
6. 查詢後必須通過 result verifier。
7. API / SQL 查詢結果優先於文件中的舊資料。
8. 文件只作為流程、定義、背景依據。

## 元件分工

### Query Card

Query Card 描述一個可被選用的商業查詢能力，例如 `query_bom_cost`。

它包含：

- `query_name`
- `title`
- `description`
- `required_args`
- `optional_args`
- `output_schema`
- `empty_result_policy`

Query Card 是給 Planner 選工具用的 metadata，不包含 SQL raw text。

### SQL Template Registry

`backend/sql_templates/registry.py` 管理所有固定 SQL template。

每個 template 包含：

- `template_id`
- `query_name`
- `version`
- `sql`
- `allowed_params`
- `row_limit`
- `timeout_sec`

Registry 會檢查：

- 只能是 SELECT
- 只能使用 named parameters，例如 `:part_no`
- SQL 裡的參數必須都在 `allowed_params`
- `allowed_params` 不可包含 `raw_sql`
- 不允許明顯多語句 SQL

### Query Planner

`query_planner` 負責產生 `QueryPlan`。

可能 decision：

- `answer_from_docs`
- `call_query_template`
- `ask_clarification`

Planner 只能從候選 Query Cards 裡選 `query_name`。它不產生 SQL，也不輸出 `raw_sql`。

### Query Validator

`query_validator` 負責在執行前擋掉不安全或不完整的 QueryPlan。

它會檢查：

- `query_name` 是否在 registry
- `query_name` 是否在候選 Query Cards
- required args 是否完整
- arguments 是否符合 Pydantic schema
- confidence 是否通過門檻
- 是否沒有 `raw_sql`
- SQL template 是否有效

Validator 輸出 action：

- `execute`
- `ask_clarification`
- `reject`

### MCP Business Query Server

`backend/mcp_servers/business_query_server.py` 把固定 query template 包成工具。

目前 V1 已完整實作：

- `query_bom_cost`

並保留清楚 schema 的 stub：

- `query_project_spec`
- `query_vendor_quote`

每個 tool 都只接收 Pydantic args，從 registry 取得 SQL template，透過 `DatabaseClient.execute_prepared(...)` 執行 prepared statement。

回傳格式固定：

```json
{
  "query_name": "query_bom_cost",
  "status": "success",
  "input": {
    "part_no": "A123",
    "project_id": "P01"
  },
  "row_count": 1,
  "columns": ["part_no", "unit_price", "currency", "vendor", "updated_at"],
  "data": [],
  "source": {
    "database": "mock",
    "template_id": "query_bom_cost:v1",
    "executed_at": "2026-07-01T00:00:00Z"
  },
  "warnings": [],
  "error": null
}
```

### Result Verifier

`result_verifier` 在 MCP tool 回傳後做檢查。

它會確認：

- status 是否成功
- row_count 是否為 0
- row_count 是否超過上限
- 必要欄位是否存在
- data type 是否符合 `output_schema`
- 查無資料時保留 `empty_result_policy.answer`

### Synthesizer

`synthesizer` 把 query plan、query result、result verification 轉成穩定回答。

V1 是 deterministic template，不需要真的呼叫 LLM。它會遵守：

- query result 有資料時，以 API / SQL 結果為準
- query result 查無資料時，明確說查無資料，不用文件補答案
- API error 時，明確說查詢失敗原因
- `ask_clarification` 時直接問澄清問題
- `answer_from_docs` 時只根據 evidence pack 回答

### Query Pipeline

`backend/services/query_pipeline.py` 串接整個流程。

流程：

1. 用 `rag_query` 或 `user_message` 搜尋 candidate query cards。
2. 沒有候選 query cards 時回 `not_applicable`。
3. 呼叫 query planner 產生 QueryPlan。
4. 呼叫 query validator。
5. 如果 action 是 `ask_clarification`，不執行 MCP tool。
6. 如果 action 是 `reject`，不執行 MCP tool。
7. 如果 action 是 `execute`，呼叫 MCP Query Executor。
8. 呼叫 result verifier。
9. 產生 `context_block`，交給 chat answer LLM 使用。

`context_block` 會包含：

- Query Template 名稱
- 查詢條件
- 查詢結果摘要
- row_count
- source.database
- source.template_id
- source.executed_at

## Chat Stream 如何使用 MCP

`backend/app/features/chat/api/chat.py` 的 `/chat/stream` 已經整合 query pipeline。

位置在：

1. parse request
2. load session/history
3. persist user message
4. RAG rewrite
5. RAG retrieve context
6. attachment context 合併到 context
7. 呼叫 `query_pipeline.run(...)`
8. 如果有 `context_block`，append 到 context
9. 再呼叫 `chat_service.stream_answer(...)`

特殊情況：

- `ask_clarification`：直接 stream 澄清問題，不呼叫長回答 LLM。
- `rejected`：直接 stream 安全拒絕或補充資訊，不執行 SQL。
- `call_query_template`：確定 MCP query 已執行且 result verification 完成後，再把 `context_block` 放進 prompt。
- pipeline 例外：記錄 `logger.exception`，context 補上「API 查詢暫時失敗」，再走原本 RAG 流程。

## 使用範例

使用者問：

```text
請查 A123 在 P01 的 BOM cost
```

### 1. RAG 先取得文件背景

Chat stream 會先執行原本 RAG 流程，取得文件 context 和 citations。

這些文件可能說明：

- BOM cost 是什麼
- 查 BOM cost 需要料號與 project id
- 成本資料欄位定義

但文件不是最新交易資料來源。

### 2. Query Pipeline 找候選 Query Card

Pipeline 會用 `rag_query` 或 `user_message` 找 candidate query cards。

因為問題包含 BOM cost，所以找到：

```json
{
  "query_name": "query_bom_cost",
  "title": "BOM Cost",
  "required_args": {
    "part_no": { "type": "string" },
    "project_id": { "type": "string" }
  }
}
```

### 3. Planner 產生 QueryPlan

Planner 看到使用者提供了：

- `part_no = A123`
- `project_id = P01`

因此產生：

```json
{
  "decision": "call_query_template",
  "query_name": "query_bom_cost",
  "arguments": {
    "part_no": "A123",
    "project_id": "P01"
  },
  "missing_args": [],
  "confidence": 0.82,
  "reason": "The question needs database-backed facts and all required arguments are present.",
  "required_evidence_ids": ["evidence_context"]
}
```

注意：這裡沒有 SQL，也沒有 `raw_sql`。

### 4. Validator 檢查 QueryPlan

Validator 會確認：

- `query_bom_cost` 存在於 registry
- `query_bom_cost` 存在於 candidate cards
- required args 完整
- arguments 符合 Pydantic schema
- confidence >= 0.7
- 沒有 `raw_sql`
- SQL template 合法

如果全部通過，action 會是：

```json
{ "action": "execute" }
```

### 5. MCP tool 執行固定 SQL template

Pipeline 呼叫 MCP Query Executor，Executor 只會呼叫固定 tool：

```python
query_bom_cost({"part_no": "A123"})
```

Tool 會從 registry 取得 SQL template，例如：

```text
template_id = query_bom_cost:v1
allowed_params = ("part_no",)
timeout_sec = 10
```

然後使用：

```python
execute_prepared(sql=template.sql, params={"part_no": "A123"}, timeout_sec=10)
```

LLM 沒有機會提供 raw SQL。

### 6. Result Verifier 檢查結果

假設 MCP tool 回傳：

```json
{
  "query_name": "query_bom_cost",
  "status": "success",
  "input": {
    "part_no": "A123",
    "project_id": "P01"
  },
  "row_count": 1,
  "columns": ["part_no", "unit_price", "currency", "vendor", "updated_at"],
  "data": [
    {
      "part_no": "A123",
      "unit_price": 12.5,
      "currency": "USD",
      "vendor": "Acme",
      "updated_at": "2026-06-30T12:00:00Z"
    }
  ],
  "source": {
    "database": "mock",
    "template_id": "query_bom_cost:v1",
    "executed_at": "2026-07-01T00:00:00Z"
  },
  "warnings": [],
  "error": null
}
```

Verifier 會確認：

- status 成功
- row_count 不是 0
- 沒超過 row limit
- 必要欄位存在
- 型別符合 output schema

### 7. Pipeline 產生 context_block

Pipeline 會產生一段給回答 LLM 用的 context block：

```text
Query Template 名稱: query_bom_cost
查詢條件: {"part_no": "A123", "project_id": "P01"}
查詢結果摘要: [{"currency": "USD", "part_no": "A123", "unit_price": 12.5, "updated_at": "2026-06-30T12:00:00Z", "vendor": "Acme"}]
row_count: 1
source.database: mock
source.template_id: query_bom_cost:v1
source.executed_at: 2026-07-01T00:00:00Z
```

這段會 append 到原本 RAG context。

### 8. 最終回答

`chat_service.stream_answer(...)` 會看到：

- 文件 context：用來說明流程、定義、背景
- query context block：用來回答最新資料

因此回答時應以 API / SQL 查詢結果為準，例如：

```text
查詢 A123 在 P01 的 BOM cost 結果如下：

- unit_price: 12.5
- currency: USD
- vendor: Acme
- updated_at: 2026-06-30T12:00:00Z

查詢條件：part_no=A123, project_id=P01
資料來源：database=mock, template_id=query_bom_cost:v1, executed_at=2026-07-01T00:00:00Z
```

## 查無資料時

如果使用者問：

```text
請查 Z999 在 P01 的 BOM cost
```

MCP tool 回傳 `row_count = 0` 時，系統會明確回答查無資料。

它不會用文件裡的舊資料補出一個成本答案。

## 缺少參數時

如果使用者問：

```text
請查 A123 的 BOM cost
```

Planner / Validator 會發現缺少 `project_id`。

Pipeline decision 會是：

```json
{ "decision": "ask_clarification" }
```

Chat stream 會直接回：

```text
我需要先釐清缺少的查詢條件：project_id。
```

不會呼叫 MCP executor，也不會呼叫原本長回答 LLM 假裝查詢完成。

## 安全邊界

這套設計刻意把權責切開：

- LLM 只能選 query template 和填 arguments。
- Validator 決定能不能執行。
- MCP tool 只執行 registry 裡的固定 SQL。
- DatabaseClient 只提供 prepared execution。
- Route 不知道 Planner / Validator / SQL 細節。

因此即使 LLM 輸出：

```json
{
  "arguments": {
    "raw_sql": "SELECT * FROM users"
  }
}
```

也會被 Planner validator 或 Query validator 擋掉，pipeline 回 `rejected`，不會執行查詢。
