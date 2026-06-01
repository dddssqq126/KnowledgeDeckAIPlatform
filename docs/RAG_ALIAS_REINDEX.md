# RAG Alias Scanner、Reindex / Re-ingest 操作指南

這份文件說明：

1. 如何離線掃描所有已上傳文件，產生 canonical alias 建議。
2. 上傳的每一份文件實際存在哪裡。
3. 什麼時候需要 reindex / re-ingest。
4. 如何執行全量 reindex 與單檔 re-ingest。

---

## 1. Alias scanner 是什麼？

`python -m app.cli suggest-tag-aliases` 是一支離線 CLI 工具，用來掃描既有文件並輸出 alias suggestions JSON。

它會從以下來源找 alias candidate：

- DB 裡已存的 file tag 欄位：`tag_vendor`、`tag_platform`、`tag_knowledge_type`。
- 檔名，例如 `PCIe-Link-Training.pdf`。
- 從 object storage 讀出的原始文件內容，經 `document_parser.parse` 解析後取前面一段文字。

這支工具**只產生建議**，不會自動修改 DB，也不會自動修改 `tagger.py` 的 alias dict。你需要人工 review 後，再決定要不要把 alias 加進 tagger normalization。

---

## 2. 它會掃所有文件嗎？

預設會掃 DB 裡所有 `deleted_at IS NULL` 的文件，也就是所有未刪除文件。

程式查詢邏輯是：

```python
select(KnowledgeFile)
.where(KnowledgeFile.deleted_at.is_(None))
.order_by(KnowledgeFile.id)
```

如果只想先試跑一小部分，可以加 `--limit-files`。

---

## 3. Alias scanner 執行步驟

### 3.1 在 Docker Compose backend 容器內執行

建議在 backend 容器內跑，因為它需要讀 DB、讀 object storage，並使用 backend 的相同 `.env` / volume 設定。

```bash
docker compose exec backend python -m app.cli suggest-tag-aliases --limit-files 20
```

### 3.2 在本機 backend 環境執行

如果你是直接在本機跑 backend，請進入 backend 目錄：

```bash
cd backend
python -m app.cli suggest-tag-aliases --limit-files 20
```

### 3.3 先小量試跑

```bash
cd backend
python -m app.cli suggest-tag-aliases \
  --limit-files 20 \
  --min-count 2 \
  --sample-chars 6000
```

參數說明：

| 參數 | 說明 |
|---|---|
| `--limit-files 20` | 只掃前 20 份文件；不指定就是掃全部未刪除文件。 |
| `--min-count 2` | 同一 canonical 至少觀察到 2 次才輸出建議。 |
| `--sample-chars 6000` | 每份文件最多解析前 6000 字做掃描。 |

### 3.4 全量掃描並輸出成 JSON 檔

```bash
cd backend
python -m app.cli suggest-tag-aliases \
  -o alias-suggestions.json \
  --min-count 2 \
  --sample-chars 6000
```

輸出格式範例：

```json
{
  "suggestions": [
    {
      "field": "vendor",
      "canonical": "pci_sig",
      "aliases": ["PCI-SIG", "PCI SIG"],
      "count": 3,
      "examples": ["pcie-link-training.pdf", "pcie-spec.pdf"]
    }
  ]
}
```

欄位說明：

| 欄位 | 說明 |
|---|---|
| `field` | alias 來源欄位，例如 `vendor`、`platform`、`knowledge_type`、`filename`、`proper_noun`。 |
| `canonical` | 建議 normalize 到的 canonical slug。 |
| `aliases` | corpus 中觀察到的原始寫法。 |
| `count` | 觀察次數。 |
| `examples` | 出現過的文件範例，供人工 review。 |

### 3.5 人工 review 後更新 tagger aliases

如果你確認某組 aliases 是合理的，例如：

```json
{
  "field": "vendor",
  "canonical": "pci_sig",
  "aliases": ["PCI-SIG", "PCI SIG"]
}
```

可以把確認過的 mapping 加進 `backend/app/features/rag/services/tagger.py`，例如：

```python
_VENDOR_ALIASES = {
    "pci sig": "pci_sig",
    "pci-sig": "pci_sig",
    "pcisig": "pci_sig",
}
```

> 注意：scanner 不會自動改 code。這是刻意設計，避免把錯誤 alias 自動寫進 production tagging logic。

---

## 4. 上傳的每一份文件存在哪裡？

目前 object storage 是本機 filesystem 實作。

設定預設值：

```python
storage_bucket = "knowledgedeck"
local_storage_root = "/var/lib/knowledgedeck-storage"
```

`.env.example` 對應設定：

```env
LOCAL_STORAGE_ROOT=/var/lib/knowledgedeck-storage
STORAGE_BUCKET=knowledgedeck
```

實際 base path 是：

```text
<LOCAL_STORAGE_ROOT>/<STORAGE_BUCKET>
```

預設就是：

```text
/var/lib/knowledgedeck-storage/knowledgedeck
```

上傳時，每一份文件會取得一個 `storage_key`：

```text
kb/<kb_id>/files/<file_id>/original.<extension>
```

所以完整實體路徑會像：

```text
/var/lib/knowledgedeck-storage/knowledgedeck/kb/<kb_id>/files/<file_id>/original.<extension>
```

例如：

```text
/var/lib/knowledgedeck-storage/knowledgedeck/kb/3/files/27/original.pdf
```

---

## 5. 什麼時候需要 reindex / re-ingest？

### 需要 reindex / re-ingest 的情境

以下改動會影響已經進 Qdrant 的 payload、embedding text 或 sparse/dense vectors，因此既有文件需要重跑 ingestion：

- 修改 `tagger.py` aliases。
- 修改 tagger prompt 或 fallback tag 邏輯。
- 修改 chunking 參數。
- 修改 embedding enrichment，例如 tag line 內容。
- 修改 sparse / dense vector schema。
- 修改 Qdrant payload 欄位。

### 不一定需要 reindex 的情境

以下通常只影響「查詢時」邏輯，不一定需要重新 ingest 既有文件：

- 調整 `RAG_RERANK_CANDIDATE_K`。
- 調整 `RAG_HYBRID_PREFETCH_LIMIT`。
- 調整 `RAG_PER_FILE_CONTEXT_LIMIT`。
- 調整 `RAG_TAG_MATCH_BOOST`。

---

## 6. 全量 reindex：重建 Qdrant 並重新 ingest 所有文件

後端有一個 maintenance API：

```http
POST /admin/rag-reindex
```

這個 endpoint 會：

1. Drop + recreate Qdrant collection。
2. 查詢所有未刪除文件。
3. 從 object storage 讀原檔。
4. parse → chunk → dense embed → sparse embed → upsert Qdrant。
5. 更新 file status。

> 注意：目前 `FAILED` 狀態的 file 會被 skipped。

### 6.1 取得 token

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
```

### 6.2 執行全量 reindex

```bash
curl -s -X POST http://localhost:8080/admin/rag-reindex \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

回應範例：

```json
{
  "reindexed": 12,
  "failed": 0,
  "skipped": 1,
  "failed_files": []
}
```

### 6.3 什麼時候跑這個？

建議流程：

```bash
# 1. 掃 alias suggestions
cd backend
python -m app.cli suggest-tag-aliases -o alias-suggestions.json

# 2. 人工 review alias-suggestions.json
# 3. 修改 tagger.py aliases
# 4. 重啟 backend，使新 alias code 生效
# 5. 呼叫 /admin/rag-reindex 重建 Qdrant + 重新 ingest 所有文件
```

---

## 7. 單檔 re-ingest：重新 ingest 某一份文件

目前沒有獨立的 `POST /files/{id}/reingest` endpoint；但有兩種方式可以達到單檔 re-ingest。

### 方式 A：重新上傳該文件

最直覺的方式：

1. 刪除舊檔案。
2. 重新上傳同一份文件。

上傳流程會重新：parse → tag → chunk → embed → upsert Qdrant。

### 方式 B：使用 tag update endpoint 觸發 re-ingest

`PATCH /knowledge-bases/{kb_id}/files/{file_id}/tags` 會：

1. 更新該 file row 的 tag override。
2. 清掉該 file 在 Qdrant 的 vectors。
3. 從 object storage 讀原檔。
4. 重新跑 `ingest_file`。

也就是說，如果你想單檔 re-ingest，可以 PATCH 目前相同或新的 tags。

範例：

```bash
curl -s -X PATCH http://localhost:8080/knowledge-bases/3/files/27/tags \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "vendor": "3gpp",
    "platform": "5g_nr",
    "knowledge_type": "standard"
  }' \
  | python3 -m json.tool
```

如果你只是要「觸發重跑」但不想改 tags，可以先查目前 tags，再用同樣值 PATCH 回去。

---

## 8. Recommended workflow：alias scanner + reindex

建議完整流程如下：

```bash
# 1. 進 backend 環境
cd backend

# 2. 先小量掃描確認輸出
python -m app.cli suggest-tag-aliases --limit-files 20 --min-count 2

# 3. 全量掃描並輸出 JSON
python -m app.cli suggest-tag-aliases -o alias-suggestions.json --min-count 2

# 4. Review alias-suggestions.json
cat alias-suggestions.json

# 5. 把確認過的 alias 加進 backend/app/features/rag/services/tagger.py

# 6. 重啟 backend，讓新 code 生效
# docker compose restart backend

# 7. 取得 token
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")

# 8. 全量 reindex
curl -s -X POST http://localhost:8080/admin/rag-reindex \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

---

## 9. 常見問題

### Q1：Alias scanner 會不會改掉我的文件或 DB？

不會。它只讀 DB、讀 object storage、輸出 JSON suggestions。

### Q2：Alias scanner 掃不到某份文件內容怎麼辦？

如果某份文件讀取或 parse 失敗，scanner 會略過文字內容，但仍會用 filename 和 DB tag 欄位產生 observations。

### Q3：全量 reindex 會不會刪掉原始檔？

不會。`/admin/rag-reindex` 重建的是 Qdrant collection，原始檔仍在 object storage。

### Q4：修改 alias 後，不跑 reindex 會怎樣？

新上傳文件會使用新 alias；既有 Qdrant payload 仍是舊 tag，因此搜尋與 citations 中看到的既有 tags 不會更新。

### Q5：單檔 re-ingest 有沒有 API？

目前沒有獨立 re-ingest endpoint。可用重新上傳，或用 `PATCH /knowledge-bases/{kb_id}/files/{file_id}/tags` 觸發該檔重新 ingest。
