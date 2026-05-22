# API Reference

KnowledgeDeck exposes a REST API plus two SSE streaming endpoints. All endpoints (except `POST /auth/login`, `GET /health`, `GET /ready`) require an `Authorization: Bearer <token>` header.

> For an architecture overview see [ARCHITECTURE.md](ARCHITECTURE.md). For a quickstart see [README.md](../README.md).

---

## Conventions

- **Base URL** in compose: `http://localhost:8080` (or your host:8080 for remote dev).
- **Auth header**: `Authorization: Bearer <token>`. Token comes from `POST /auth/login`. Format is currently `u_<userId>` (opaque to clients).
- **Content type**: `application/json` for request bodies; multipart for file uploads.
- **Errors**: FastAPI default — `{"detail": "<code-or-message>"}` with appropriate 4xx/5xx status. Validation errors come from Pydantic with a structured `detail`.
- **Pagination**: not supported in MVP. List endpoints return everything the user owns.
- **Soft-delete**: KBs, files, and chat/slide sessions are soft-deleted (`deleted_at` set). Listing endpoints filter them out.

### Common error codes

| Code | When |
|---|---|
| `invalid_token` | Bearer header missing, malformed, or doesn't resolve to a user |
| `not_found` | Resource doesn't exist or doesn't belong to the requesting user |
| `invalid_extension` | Upload file extension not in `{txt, pdf, cs, md, docx, pptx, py, html, css}` |
| `invalid_content` | Magic-byte or UTF-8 check failed |
| `file_too_large` | Upload exceeded 50 MB |
| `duplicate_filename` | KB already has a non-deleted file with the same name |
| `storage_error` | SQLite object storage write failed |
| `no_outline_ready` | `/render` called before any `[OUTLINE_READY]` assistant turn |
| `outline_unparsable` | Latest `[OUTLINE_READY]` turn doesn't contain `## Slide N: ...` blocks |

---

## Auth

### POST /auth/login

Public. Returns a bearer token.

**Request**:
```json
{ "username": "admin", "password": "your-password" }
```

**Response 200**:
```json
{ "token": "u_1", "user": { "id": 1, "username": "admin" } }
```

**Errors**: `401 invalid_credentials`

**Example**:
```bash
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
```

### GET /auth/me

Echo back the current user.

**Response 200**:
```json
{ "id": 1, "username": "admin" }
```

**Errors**: `401 invalid_token`

---

## Health

### GET /health

Liveness check. Always 200 if the process is up.

**Response 200**: `{"status": "ok"}`

### GET /ready

Readiness check. Returns ready when the backend process can serve requests; SQLite schema/object initialization happens during startup.

**Response 200**: `{"status": "ready"}`

---

## LLM Info

### GET /llm/info

Returns the configured chat LLM's display name and model id. Used by the frontend to populate the `Model: <label>` header.

**Response 200**:
```json
{ "label": "Gemma 4 E4B", "model_id": "google/gemma-4-E4B-it" }
```

---

## Knowledge Bases

### GET /knowledge-bases

List the current user's KBs (newest first).

**Response 200**:
```json
[
  { "id": 1, "name": "research", "description": null, "created_at": "2026-04-26T10:00:00+00:00" }
]
```

### POST /knowledge-bases

Create a new KB.

**Request**:
```json
{ "name": "research", "description": "ML papers" }
```

**Response 201**:
```json
{ "id": 1, "name": "research", "description": "ML papers", "created_at": "2026-04-26T10:00:00+00:00" }
```

**Errors**: `409 duplicate_name`

### PATCH /knowledge-bases/{kb_id}

Rename / update description.

**Request**:
```json
{ "name": "research-2026", "description": "..." }
```

**Response 200**: same shape as POST.

**Errors**: `404 not_found`, `409 duplicate_name`

### DELETE /knowledge-bases/{kb_id}

Soft-delete the KB. Cascades to files and their vectors.

**Response 204**: empty body.

**Errors**: `404 not_found`

---

## Files (per-KB)

### GET /knowledge-bases/{kb_id}/files

List files in a KB.

**Response 200**:
```json
[
  {
    "id": 12,
    "filename": "react_hooks.txt",
    "extension": "txt",
    "size_bytes": 2406,
    "content_sha256": "a1b2...",
    "status": "indexed",
    "status_error": null,
    "created_at": "2026-04-26T10:01:00+00:00"
  }
]
```

`status` is one of: `uploaded` (initial), `parsing`, `parsed`, `embedding`, `indexed` (success), `failed`. The synchronous ingest pipeline transitions `uploaded → indexed | failed` in the same request.

### POST /knowledge-bases/{kb_id}/files

Upload a file. Synchronous: parses + chunks + embeds + indexes inline. Returns the final file row with terminal status.

**Request**: `multipart/form-data` with field `file`. Accepted extensions: `txt`, `md`, `pdf`, `cs`, `py`, `html`, `css`, `docx`, `pptx`. 50 MB cap.

**Response 201**: same shape as the list entry above. `status` is `indexed` on success or `failed` on any pipeline error (with `status_error` populated).

**Errors**:
- `400 invalid_extension` — extension not in allow-list
- `400 invalid_content` — magic-byte / UTF-8 check failed
- `409 duplicate_filename` — KB already has a non-deleted file with this name
- `413 file_too_large` — exceeded `MAX_UPLOAD_BYTES` (default 50 MiB)
- `500 storage_error` — SQLite object storage failure

**Example**:
```bash
curl -X POST "http://localhost:8080/knowledge-bases/1/files" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@./react_hooks.txt"
```

### DELETE /knowledge-bases/{kb_id}/files/{file_id}

Soft-delete a file. Vectors are removed from Qdrant immediately; the SQLite object blob stays.

**Response 204**: empty body.

**Errors**: `404 not_found`

---

## Chat

### GET /chat/sessions

List user's chat sessions (most recently updated first).

**Response 200**:
```json
[
  { "id": 5, "title": "Kubernetes basics", "created_at": "...", "updated_at": "..." }
]
```

### POST /chat/sessions

Create a new empty session. Title is auto-derived from the first user message on first stream.

**Request**:
```json
{ "title": null }
```

**Response 201**:
```json
{ "id": 5, "title": "New Chat", "created_at": "...", "updated_at": "..." }
```

### GET /chat/sessions/{session_id}

Session detail with full message history.

**Response 200**:
```json
{
  "id": 5,
  "title": "...",
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    {
      "id": 100,
      "role": "user",
      "content": "Tell me about React hooks",
      "citations": null,
      "created_at": "..."
    },
    {
      "id": 101,
      "role": "assistant",
      "content": "Hooks let you opt into React's state management...",
      "citations": [{"file_id": 12, "filename": "react_hooks.txt"}],
      "created_at": "..."
    }
  ]
}
```

### PATCH /chat/sessions/{session_id}

Rename a session.

**Request**: `{"title": "New title"}`

**Response 200**: same shape as POST.

### DELETE /chat/sessions/{session_id}

Soft-delete.

**Response 204**: empty body.

### POST /chat/stream

Server-Sent Events stream. The body specifies which session to append to and whether to ground the answer in RAG.

**Request**:
```json
{
  "session_id": 5,
  "message": "What are the main types?",
  "use_rag": true,
  "kb_ids": [1, 2]
}
```

`kb_ids: null` = search across ALL the user's KBs (no KB filter). `use_rag: false` = skip retrieval, no `Context:` block in the prompt.

**Response**: `text/event-stream`

**Event types** (in order):
```
event: token
data: {"text": "Hooks "}

event: token
data: {"text": "let "}

... many more token events ...

event: citations
data: {"items": [{"file_id": 12, "filename": "react_hooks.txt"}, ...]}

event: done
data: {}
```

On error:
```
event: error
data: {"message": "..."}
```

The user message is persisted before streaming starts; the assistant message is persisted after the token stream ends but before the `done` event. So a client that disconnects mid-stream still has both turns in the DB on the next session fetch.

**RAG behavior**:
1. If `use_rag=true` AND there's prior history, the request goes through a query-rewriter LLM call first (resolves "and the deployment one?" into a standalone query).
2. Hybrid retrieval (dense + sparse + RRF) returns up to 20 candidates from the selected KBs.
3. Cross-encoder rerank scores each candidate; below `RAG_RERANK_MIN_SCORE` is dropped.
4. Top `RAG_FINAL_TOP_K` (default 5) chunks become the prompt's `Context:` block.
5. Citations in the SSE event are unique by file_id and reflect what actually went into the prompt.

**Example**:
```bash
curl -N -X POST http://localhost:8080/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id":5,"message":"What are React hooks?","use_rag":true,"kb_ids":null}'
```

---

## Slide Maker

### GET /slide-sessions

List user's slide decks.

**Response 200**:
```json
[
  {
    "id": 14,
    "title": "5 slides about database indexing",
    "status": "rendered",
    "has_pptx": true,
    "custom_template_id": null,
    "custom_template_name": null,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

`status`: `outlining`, `rendering`, `rendered`, `failed`.

### POST /slide-sessions

Create empty deck.

**Request**: `{"title": null}`
**Response 201**: same shape as list entry.

### GET /slide-sessions/{session_id}

Detail with full message history.

**Response 200**:
```json
{
  "id": 14,
  "title": "...",
  "status": "rendered",
  "has_pptx": true,
  "custom_template_id": null,
  "custom_template_name": null,
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    { "id": 200, "role": "user", "content": "5 slides about database indexing", ... },
    { "id": 201, "role": "assistant", "content": "What's the audience? ...", ... },
    { "id": 202, "role": "user", "content": "junior backend devs, modern style", ... },
    { "id": 203, "role": "assistant",
      "content": "## Slide 1: ...\n[OUTLINE_READY template=modern language=English]", ... },
    { "id": 204, "role": "assistant", "content": "[RENDERED:8] Your presentation is ready.", ... }
  ]
}
```

The `[OUTLINE_READY ...]` and `[RENDERED:N]` / `[RENDER_FAILED:N]` markers are part of the message content. Frontend strips/parses them — clients integrating directly should handle the same.

### PATCH /slide-sessions/{session_id}

Rename a deck.

**Request**: `{"title": "..."}`
**Response 200**: same shape as POST.

### DELETE /slide-sessions/{session_id}

Soft-delete.

**Response 204**: empty body.

### POST /slide-sessions/{session_id}/stream

Server-Sent Events planner conversation. Same shape as `/chat/stream` plus an `outline_ready: bool` field on the `done` event.

**Request**:
```json
{
  "message": "5 slides about database indexing for backend devs",
  "use_rag": true,
  "kb_ids": null
}
```

**Events**:
```
event: token         (many)
event: citations
event: done
data: {"outline_ready": true}    ← when assistant emitted [OUTLINE_READY ...]
```

When `outline_ready: true`, the frontend automatically POSTs `/render` to start PPTX generation.

### POST /slide-sessions/{session_id}/render

Build a PPTX via Presenton from the latest `[OUTLINE_READY]` outline. Synchronous (15-30s typical).

**Request**:
```json
{ "template": "general", "language": "English" }
```

Both fields are optional. Precedence: `session.custom_template_id` > marker `template=...` > body `template` > default `"general"`. Allowed templates: `general`, `modern`, `standard`, `swift`.

**Response 200** (success or failure — both produce a persisted assistant message):
```json
{
  "session": { /* SlideSessionOut, status now 'rendered' or 'failed' */ },
  "message": {
    "id": 204,
    "role": "assistant",
    "content": "[RENDERED:8] Your presentation is ready.",
    "citations": null,
    "created_at": "..."
  }
}
```

On Presenton failure, the message content is `[RENDER_FAILED:N] <error excerpt>`.

**Errors** (only true 4xx, raised as HTTPException):
- `400 no_outline_ready` — no `[OUTLINE_READY]` assistant turn exists
- `400 outline_unparsable` — outline doesn't contain `## Slide N:` blocks

### GET /slide-sessions/{session_id}/download

Stream the rendered PPTX.

**Response 200**: `application/vnd.openxmlformats-officedocument.presentationml.presentation` body, `Content-Disposition: attachment; filename="<title>.pptx"`.

**Errors**: `404 not_rendered_yet` if the session has no PPTX yet.

### GET /slide-sessions/available-templates *(currently unused by UI)*

Lists user-authored templates known to Presenton. Exists for a future self-hosted PPTX-template-upload flow; the UI doesn't currently invoke it.

**Response 200**:
```json
[ { "id": "<uuid>", "name": "..." } ]
```

### PATCH /slide-sessions/{session_id}/template *(currently unused by UI)*

Pin a custom template to a session.

**Request**:
```json
{ "custom_template_id": "<uuid>", "custom_template_name": "..." }
```

(Both null = clear.)

**Response 200**: SlideSessionOut.

---

## Admin

### POST /admin/rag-reindex

**Destructive.** Drops the Qdrant collection and re-ingests every non-deleted file from SQLite object blobs. Used after vector-pipeline changes (e.g., when sparse vectors were added).

Auth-only (any logged-in user) for MVP. In production, gate behind an admin role.

**Response 200**:
```json
{
  "reindexed": 13,
  "failed": 0,
  "skipped": 0,
  "failed_files": []
}
```

`skipped` counts files already in `failed` state (not retried). `failed_files` lists `{id, filename, error}` for any file that re-ingest couldn't process.

**Example**:
```bash
curl -X POST http://localhost:8080/admin/rag-reindex -H "Authorization: Bearer $TOKEN"
```

---

## Streaming format reference

Both `/chat/stream` and `/slide-sessions/{id}/stream` use Server-Sent Events. Frame format:

```
event: <type>\n
data: <json>\n
\n
```

Each frame is terminated by `\n\n`. The client should buffer until it sees `\n\n`, then parse. Use `fetch(POST)` + `ReadableStream`, not `EventSource` — `EventSource` cannot attach the `Authorization` header.

Example client (TypeScript):
```ts
const res = await fetch(url, { method: "POST", headers: {...}, body: JSON.stringify(req) });
const reader = res.body!.getReader();
const decoder = new TextDecoder();
let buffer = "";
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  let sep: number;
  while ((sep = buffer.indexOf("\n\n")) >= 0) {
    const frame = buffer.slice(0, sep);
    buffer = buffer.slice(sep + 2);
    // parse "event: ...\ndata: ..."
    const lines = frame.split("\n");
    const event = lines.find(l => l.startsWith("event:"))?.slice(6).trim();
    const data = lines.find(l => l.startsWith("data:"))?.slice(5).trim();
    handle(event, JSON.parse(data ?? "{}"));
  }
}
```

---

## Quick recipe: end-to-end RAG chat

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")

# 1. Create a KB
KB=$(curl -s -X POST http://localhost:8080/knowledge-bases \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

# 2. Upload a file
curl -s -X POST "http://localhost:8080/knowledge-bases/$KB/files" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@./testData/kubernetes_basics.txt"

# 3. Create a chat session
SID=$(curl -s -X POST http://localhost:8080/chat/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"demo"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

# 4. Stream a RAG-grounded reply
curl -N -X POST http://localhost:8080/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":$SID,\"message\":\"What are Kubernetes pods?\",\"use_rag\":true,\"kb_ids\":[$KB]}"
```

---

## Quick recipe: generate a PPTX

```bash
SSID=$(curl -s -X POST http://localhost:8080/slide-sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"k8s deck"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

# Conversational planning (multi-turn, the assistant will ask clarifying
# questions and only emit [OUTLINE_READY] once you confirm)
curl -N -X POST "http://localhost:8080/slide-sessions/$SSID/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"3 slides about Kubernetes pods for backend devs","use_rag":true,"kb_ids":null}'

# After the assistant emits [OUTLINE_READY], either the frontend
# auto-renders or you can POST /render manually
curl -X POST "http://localhost:8080/slide-sessions/$SSID/render" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{}'

# Download the rendered PPTX
curl -L -o deck.pptx \
  "http://localhost:8080/slide-sessions/$SSID/download" \
  -H "Authorization: Bearer $TOKEN"
```
