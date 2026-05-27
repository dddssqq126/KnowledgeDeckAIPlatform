"use client";

import { Database, Download, FileText, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  type FileTags,
  type KnowledgeBase,
  type KnowledgeFile,
  downloadKnowledgeFile,
  listFileTags,
  listFiles,
  listKnowledgeBases,
} from "../../../lib/knowledge-bases";

type RagDatabase = KnowledgeBase & {
  files: KnowledgeFile[];
  vector_count: number;
  embedding_model: string;
  fileTags: Map<number, FileTags>;
};

type FilteredRagDatabase = RagDatabase & {
  visible_files: KnowledgeFile[];
  database_matches: boolean;
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function RagDatabasesPage() {
  const [databases, setDatabases] = useState<RagDatabase[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const kbs = await listKnowledgeBases();
        const rows = await Promise.all(
          kbs.map(async (kb) => {
            const files = await listFiles(kb.id);
            const tags = await listFileTags(kb.id);
            const fileTags = new Map(tags.map((t) => [t.file_id, t]));
            return {
              ...kb,
              files,
              file_count: files.length,
              vector_count: tags.reduce((sum, t) => sum + t.chunk_count, 0),
              embedding_model: "BAAI/bge-m3",
              fileTags,
            };
          }),
        );
        if (!cancelled) setDatabases(rows);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load RAG databases");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const totals = useMemo(
    () => ({
      files: databases.reduce((sum, db) => sum + db.files.length, 0),
      vectors: databases.reduce((sum, db) => sum + db.vector_count, 0),
    }),
    [databases],
  );

  const filteredDatabases = useMemo<FilteredRagDatabase[]>(() => {
    const normalized = query.trim().toLowerCase();
    return databases
      .map((db) => {
        const databaseMatches = normalized
          ? db.name.toLowerCase().includes(normalized)
          : false;
        const visibleFiles = normalized
          ? db.files.filter((file) =>
              file.filename.toLowerCase().includes(normalized),
            )
          : db.files;
        return {
          ...db,
          visible_files: visibleFiles,
          database_matches: databaseMatches,
        };
      })
      .filter(
        (db) =>
          !normalized || db.database_matches || db.visible_files.length > 0,
      );
  }, [databases, query]);

  async function handleDownload(file: KnowledgeFile) {
    try {
      await downloadKnowledgeFile(file.id, file.filename);
    } catch (err) {
      window.alert(
        err instanceof Error ? err.message : "Failed to download file",
      );
    }
  }

  return (
    <section className="h-full overflow-auto px-6 py-6">
      <div className="mx-auto max-w-6xl space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">RAG Databases</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              All indexed knowledge bases and the files currently available for
              retrieval.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <Metric label="Databases" value={loading ? "--" : databases.length} />
            <Metric label="Files" value={loading ? "--" : totals.files} />
            <Metric label="Vectors" value={loading ? "--" : totals.vectors} />
          </div>
        </div>

        <label className="flex h-10 max-w-md items-center gap-2 rounded-md border border-border bg-white px-3 text-sm text-muted-foreground focus-within:border-foreground/40">
          <Search className="h-4 w-4" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search imported files"
            className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>

        {error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-sm text-muted-foreground">
            Loading RAG databases...
          </div>
        ) : databases.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-sm text-muted-foreground">
            No RAG databases yet.
          </div>
        ) : filteredDatabases.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-sm text-muted-foreground">
            No files match your search.
          </div>
        ) : (
          <div className="grid gap-3">
            {filteredDatabases.map((db) => (
              <article
                key={db.id}
                className="rounded-lg border border-border bg-white p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-muted-foreground" />
                      <h2 className="truncate text-sm font-medium">{db.name}</h2>
                      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                        {db.files.length > 0 ? "ready" : "empty"}
                      </span>
                    </div>
                    {db.description ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {db.description}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex gap-2 text-xs text-muted-foreground">
                    <span>{db.files.length} files</span>
                    <span>{db.vector_count} vectors</span>
                    <span>{db.embedding_model}</span>
                  </div>
                </div>

                <div className="mt-3 overflow-hidden rounded-md border border-border">
                  {db.files.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                      This database has no indexed files.
                    </div>
                  ) : db.visible_files.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                      No files match your search in this database.
                    </div>
                  ) : (
                    <ul className="divide-y divide-border">
                      {db.visible_files.map((file) => (
                        <li
                          key={file.id}
                          className="flex items-center justify-between gap-3 px-3 py-2 text-xs"
                        >
                          <div className="flex min-w-0 flex-col">
                            <div className="flex items-center gap-2">
                              <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                              <span className="truncate text-foreground">
                                {file.filename}
                              </span>
                            </div>
                            {(() => {
                              const t = db.fileTags.get(file.id);
                              if (!t) return null;
                              return (
                                <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px]">
                                  {t.doc_type ? (
                                    <span className="rounded bg-emerald-50 px-1 text-emerald-700">{t.doc_type}</span>
                                  ) : null}
                                  {t.intent ? (
                                    <span className="rounded bg-sky-50 px-1 text-sky-700">{t.intent}</span>
                                  ) : null}
                                  {t.tags_topic.map((tp) => (
                                    <span key={tp} className="text-muted-foreground">#{tp}</span>
                                  ))}
                                </div>
                              );
                            })()}
                          </div>
                          <div className="flex shrink-0 items-center gap-3 text-muted-foreground">
                            <span>{file.extension.toUpperCase()}</span>
                            <span>{formatSize(file.size_bytes)}</span>
                            <span>{file.status}</span>
                            <button
                              type="button"
                              onClick={() => void handleDownload(file)}
                              aria-label={`Download ${file.filename}`}
                              title={`Download ${file.filename}`}
                              className="rounded p-1 hover:bg-muted hover:text-foreground"
                            >
                              <Download className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-border bg-white px-3 py-2">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}
