# Tag × RAG × Chunk × Index 架構說明

本文說明 LLM 自動 tagging 如何接進既有 RAG pipeline,以及 tag / chunk / index 之間的關係,並列出實際更動的程式與資料儲存。內容涵蓋兩個 feature:

- **Feature A — Tag-aware RAG**(產生 + 索引 tag):§1–§8。
- **Feature B — Tag 在 UI 的呈現**(讀取 + 顯示 tag):§9。

對應文件:
- A 設計 [docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md](docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md) · 計畫 [docs/superpowers/plans/2026-05-27-tag-aware-rag.md](docs/superpowers/plans/2026-05-27-tag-aware-rag.md)
- B 設計 [docs/superpowers/specs/2026-05-27-tag-ui-display-design.md](docs/superpowers/specs/2026-05-27-tag-ui-display-design.md) · 計畫 [docs/superpowers/plans/2026-05-27-tag-ui-display.md](docs/superpowers/plans/2026-05-27-tag-ui-display.md)

---

## 1. 一句話總結

> **Tag 不是一個獨立的檢索步驟,而是「在切完 chunk、做 embedding 之前」由 LLM 產生、再被「揉進要被索引的文本」的一層語意增強。** 它讓內容稀薄的小文件擁有更豐富的向量訊號,從而被 RAG 更準確地檢索到。

關鍵設計取捨:**軟增強(soft enrichment),不是硬過濾**。Tag 會進到 embedding / BM25,也會存成可過濾的 payload 欄位,但**預設不在查詢時用 tag 過濾候選**——因為查詢端推錯 tag 會把正確文件排除掉、傷 recall。

---

## 2. 四個概念的關係

```
文件 (document)
  └─ 被切成多個 chunk            ← chunk:檢索與引用的最小單位
        每個 chunk 進入 INDEX:
          ├─ dense vector  (bge-m3, 1024 維, cosine)
          ├─ sparse vector (BM25, Qdrant IDF)
          └─ payload       (provenance + TAG 欄位)

TAG 的角色:
  • 產生時機:per-document(每份文件一次 LLM 呼叫),tag 套用到該文件的所有 chunk
  • 用法 1(主力):把 tag 串成一行,prepend 到「被 embedding / BM25 的文本」 → 增強 dense + sparse 兩個向量
  • 用法 2(備用):同樣的 tag 存成 payload 欄位並建 keyword index → 之後可做過濾/UI 篩選(目前不啟用)
```

- **Chunk** 是索引與引用單位。切法是字元數(`chunk_chars=1200`, `chunk_overlap=150`,見 `core/config.py`)。
- **Index** 是 Qdrant 的一個 collection(`knowledgedeck`),每個 chunk = 一個 point,帶 named dense + sparse 兩種向量 + 一份 payload。
- **Tag** 橫跨兩者:它在 chunk 進 index「之前」生成,並同時影響「向量內容」(增強)與「payload 欄位」(可過濾)。

---

## 3. Ingestion 流程(上傳時同步執行)

進入點:[`features/rag/services/ingestion.py`](backend/app/features/rag/services/ingestion.py) 的 `ingest_file()`。

```
上傳檔案
  │
  ▼
parse        document_parser.parse()         原始檔 → 文字段落 (ParsedSegment)
  │
  ▼
chunk        _build_chunks()                 段落 → chunk dict {text, page_number, chunk_index}
  │                                          (text_splitter, 字元數切法)
  ▼
TAG          tagger.generate_doc_tags()      ← 新增。每份文件一次 LLM 呼叫(重用 chat 模型)
  │          (取文件前 rag_tag_max_chars 字;gated by rag_tagging_enabled)
  │          產出 DocTags{topic[], doc_type, intent, language};失敗 → DocTags.empty()
  ▼
ENRICH       tagger.enrich_text_for_embedding(chunk_text, tags)   ← 新增
  │          每個 chunk 的「待索引文本」= "[topics: … | type: … | intent: …]\n" + 原文
  ▼
embed        _embed(embed_texts)             dense 向量 ← 用「增強後」文本
sparse       sparse_embed.embed_passages(embed_texts)  BM25 ← 用「增強後」文本
  │
  ▼
upsert       qdrant_store.upsert_chunks(chunks=原始chunk, …, tags=tags)
             寫入 Qdrant:
               vector  = 來自增強文本(dense + sparse)
               payload.text = 原始 chunk 文本(未含 tag 前綴) ← 重要:引用/顯示用原文
               payload tag 欄位 = tags_topic / doc_type / intent / language
```

**為什麼 enrich 一定在上傳當下、且在 embed 之前**:增強的本質是「把 tag 餵進 embedding」,所以 tag 必須先於 embedding 產生;它不能是事後補的步驟,否則要重新 embed 整份文件。代價是上傳多一次 LLM 呼叫(約 +1~4 秒,與 chat 共用 GPU 0)。

**穩健性**:`generate_doc_tags` 永不丟例外(失敗回空 tag);整段又包在 `ingest_file` 既有的 try/except 內。**tagging 失敗絕不會讓上傳失敗**——文件仍會以「未增強」狀態被索引。`rag_tagging_enabled=False` 可整個關掉(行為等同改動前)。

---

## 4. 檢索流程(Runtime)— tag 目前如何「間接」起作用

進入點:[`features/rag/services/rag.py`](backend/app/features/rag/services/rag.py) 的 `retrieve_context()`。**這條路徑本身沒有為 tag 改動**:

```
使用者問題
  │
  ▼
rewrite      chat_service.rewrite_for_retrieval()   縮寫展開 / 多輪代名詞 / code-aware
  │
  ▼
hybrid       qdrant_store.hybrid_search()           dense + sparse → RRF 融合
  │                                                 filter: user_id / kb_id(不含 tag)
  ▼
rerank       cross-encoder (bge-reranker-v2-m3)     top_k=20 → 重排
  │
  ▼
threshold    丟掉低於 rag_rerank_min_score 的
  │
  ▼
top-K        取 rag_final_top_k=5 → 組成 Context: 區塊 + citations
```

**Tag 的增益是隱性的**:因為小文件的 dense/sparse 向量在 ingestion 時已被 tag 增強,所以同一個查詢更容易把它們撈進 hybrid 的候選與 rerank 的前段。**查詢端沒有用 tag 做過濾**(刻意的 non-goal,避免 recall 風險)。payload 的 keyword index 已備好,未來要做 tag 過濾/加權時可啟用。

> 注意:`hybrid_search` 已有「collection 不存在就回 `[]`」的保護(沒上傳任何文件時 chat 不會報錯)。

---

## 5. 答案生成(另一條軸,與 retrieval 準確度無關)

[`chat_service.py`](backend/app/features/chat/services/chat_service.py) 的 `SYSTEM_PROMPT` 新增「答題紀律」:文件問答只依 `Context:`、資料不足要明說、模糊時反問一句。**這提升回答 faithfulness,不改變檢索結果**(它在檢索之後才作用)。

---

## 6. 更動的程式

| 檔案 | 更動 | commit |
|---|---|---|
| `backend/app/core/config.py` | 新增 `rag_tagging_enabled`、`rag_tag_max_chars` | `2eb4509` |
| `backend/app/features/rag/services/tagger.py`(新) | `DocTags`、`_parse_tags`、`enrich_text_for_embedding`、`generate_doc_tags` | `a30111f` `8c94e78` `1178399` |
| `backend/app/features/rag/services/qdrant_store.py` | `upsert_chunks` 多收 `tags` 並寫 4 個 tag payload 欄位;`ensure_collection` 多建 keyword index | `d1ff87f` |
| `backend/app/features/rag/services/ingestion.py` | `ingest_file` 接上 tagging + enrichment(embed 增強文本、payload 存原文) | `c63045d` |
| `backend/app/features/chat/services/chat_service.py` | `SYSTEM_PROMPT` 加答題紀律 | `7acff80` |
| `backend/tests/test_*.py` | tagger / qdrant payload / ingestion(啟用+停用)/ system prompt 測試 | 多個 |
| `docker-compose.yml` | 新增 `backend_data` volume(SQLite 持久化) | `5d33e3a` |
| `.env`(gitignored,未進版控) | `QDRANT_PATH=`(改用 server qdrant)、`DATABASE_URL` 指向 volume | — |

未動到的:`rag.py` 檢索 pipeline、reranker、hybrid 融合邏輯——tag 是接在 ingestion 端,檢索端不變。

---

## 7. 更動的「資料庫 / 資料儲存」

RAG 的資料其實分兩處,這次只有 Qdrant 的 schema 變了:

### 7.1 Qdrant(向量庫)— 有 schema 變更
每個 chunk 一個 point,payload 從原本只有 provenance,**新增 4 個 tag 欄位**:

| payload 欄位 | 來源 | 之前 | 現在 |
|---|---|---|---|
| `user_id` / `kb_id` / `file_id` | 系統 | ✅ (INTEGER index) | 不變 |
| `filename` / `text` / `page_number` / `chunk_index` | 系統 | ✅ | 不變(`text` 維持原文) |
| `tags_topic` (list) | LLM | — | ✅ 新增 + KEYWORD index |
| `doc_type` | LLM | — | ✅ 新增 + KEYWORD index |
| `intent` | LLM | — | ✅ 新增 + KEYWORD index |
| `language` | LLM | — | ✅ 新增 + KEYWORD index |

- 向量本身:dense `bge-m3`(1024 維,cosine)+ sparse BM25(named vectors,同一個 point),內容改為「來自增強文本」。
- **新的 KEYWORD index 只在「建立全新 collection」時產生**(`ensure_collection`)。既有 collection 要跑 `POST /admin/rag-reindex` 重建才會有,該端點也會順便對所有檔案重跑 ingestion 補 tag。

### 7.2 SQLite(關聯式 DB)— 無 schema 變更
KB / 檔案 / 聊天等關聯資料在 SQLite。**tag 不存在 SQLite**(只存在 Qdrant payload),所以**沒有任何 Alembic / SQL migration**。

### 7.3 持久化修正(資料存放位置,非 schema)
順手修掉兩個會「rebuild 就清空資料」的部署陷阱:
- **Qdrant**:原本因 `qdrant_path` 預設值而走 in-container embedded 且無 volume → 改成連 server `qdrant` 容器(有持久化 `qdrant_data` volume)。
- **SQLite**:原本在容器可寫層 `/app/knowledgedeck.db`,每次 `--build` 被清空 → 改放 `backend_data` volume 的 `/app/data/knowledgedeck.db`。

---

## 8. 重要參數(`core/config.py`)

| 參數 | 預設 | 作用 |
|---|---|---|
| `rag_tagging_enabled` | `True` | 總開關;`False` 等同改動前(可做 A/B) |
| `rag_tag_max_chars` | `4000` | 送進 tagger 的文件前綴長度上限 |
| `chunk_chars` / `chunk_overlap` | `1200` / `150` | 切 chunk(字元數) |
| `rag_dense_top_k` / `rag_final_top_k` | `20` / `5` | rerank 前候選數 / rerank 後進 prompt 的數量 |
| `rag_rerank_min_score` | `0.10` | rerank 分數門檻 |

tag 的枚舉值(`tagger.py`):`doc_type ∈ {guide, faq, api, reference, code, release_note}`、`intent ∈ {how_to, troubleshooting, conceptual, policy}`;`topic` 自由詞,上限 5 個。

---

## 9. Tag 在 UI 的呈現(Feature B:讀取與顯示)

§1–§8 把 tag 產生並存進 Qdrant payload,但**沒有任何地方顯示**。Feature B 是**唯讀**地把既有 payload 的 tag 撈出來顯示在兩個地方。**無 schema 變更、無查詢端 tag 過濾**(維持非目標),純粹「讀出來顯示」。

### 9.1 共用後端能力:`list_file_tags`

新增 [`qdrant_store.list_file_tags(user_id, kb_id)`](backend/app/features/rag/services/qdrant_store.py):

- 用 payload filter(`user_id` + `kb_id`)`scroll` 該 KB 的所有 points(分頁直到 `offset` 為 None)。
- 依 `file_id` 聚合:tag 是 per-document,取每個檔案第一個 point 的 tag;同時數該檔的 point 數當 `chunk_count`。
- collection 不存在 → 回 `[]`(沿用 `hybrid_search` 的 `collection_exists` 保護)。
- 回 `[{file_id, doc_type, intent, tags_topic, chunk_count}, …]`。

### 9.2 B1 — RAG Databases 檢視器

**讀取路徑**:
```
前端 rag-databases 頁
  → listFileTags(kbId)  →  GET /rag/kb/{kb_id}/file-tags
                              │ 驗證 KB 屬於本人(owner_user_id == user.id, 未刪) 否則 404
                              ▼
                           qdrant_store.list_file_tags(user_id, kb_id)  → 讀 Qdrant payload
```

- **後端**:新 read-only router [`features/rag/api/inspect.py`](backend/app/features/rag/api/inspect.py)(prefix `/rag`,與放破壞性操作的 `admin.py` 分開),在 `main.py` 註冊。`FileTags` response model = 上述五欄。
- **前端**:[`rag-databases/page.tsx`](frontend/app/(protected)/rag-databases/page.tsx) 把原本**假的 `estimateVectors`** 換成**真實 chunk 數總和**,並在每個檔案列依 `db.fileTags.get(file.id)` 顯示 `doc_type` / `intent` / `#topic` chips。沒 tag 的檔案不顯示 chip;mock 模式 `listFileTags` 回 `[]`。client fn + `FileTags` type 加在 [`lib/knowledge-bases.ts`](frontend/lib/knowledge-bases.ts)。

### 9.3 B2 — Chat citation 顯示 tag

**這是 pass-through**:[`rag.py`](backend/app/features/rag/services/rag.py) 組 citation 時,從 `hit["payload"]` 多帶 `doc_type` + `tags_topic`(刻意不帶 `intent`)。下游全部不變:`ChatMessage.citations`(JSON 欄,無 schema 變更)→ SSE `citations` 事件 → 前端。

```
retrieve_context() citation dict  +doc_type +tags_topic
  → ChatMessage.citations (JSON)  → SSE "citations"  → 前端 Citation type → 顯示 chips
```

- **前端**:`Citation` type([`lib/chat.ts`](frontend/lib/chat.ts))加可選 `doc_type?` / `tags_topic?`。
- **兩個聊天渲染器都要顯示**(重要):
  - 主聊天 `/` 頁 [`(protected)/page.tsx`](frontend/app/(protected)/page.tsx) 有**自己的** `CitationList`(帶下載鈕)→ 在檔名旁加 chips。
  - Presenton 聊天用的 [`components/ChatWorkspace.tsx`](frontend/components/ChatWorkspace.tsx) → 改用抽出的共用元件 [`components/CitationList.tsx`](frontend/components/CitationList.tsx)。
  - (唯讀的 `shared-chat/[token]` 頁延後,非必要。)
- 舊訊息的 citation 沒有這些欄位 → 因為是 optional,照常只顯示檔名。

### 9.4 更動的程式(Feature B)

| 檔案 | 更動 | commit |
|---|---|---|
| `backend/app/features/rag/services/rag.py` | citation 帶 `doc_type` + `tags_topic` | `aa18ae9` |
| `frontend/lib/chat.ts` · `components/CitationList.tsx`(新) · `components/ChatWorkspace.tsx` | Citation type + 共用 CitationList + 接線 | `6c240b0` |
| `backend/app/features/rag/services/qdrant_store.py` | `list_file_tags()` | `5f3734b` |
| `backend/app/features/rag/api/inspect.py`(新) · `backend/app/main.py` | `GET /rag/kb/{id}/file-tags` + 註冊 | `eb81a2e` |
| `frontend/lib/knowledge-bases.ts` · `rag-databases/page.tsx` | `listFileTags` + 真實 chunk 數 + chips | `53083d2` |
| `frontend/app/(protected)/page.tsx` | 主聊天 CitationList 補上 tag chips | `0718f89` |

**資料庫**:Feature B **完全無 schema 變更**(只讀 Qdrant payload,SQL 不動)。

