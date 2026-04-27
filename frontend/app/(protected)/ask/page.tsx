"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { askOnce, type Citation } from "../../../lib/chat";
import { useKbStore } from "../../../lib/kb-store";

export default function AskPage() {
  const kbs = useKbStore((s) => s.kbs);
  const loaded = useKbStore((s) => s.loaded);
  const refresh = useKbStore((s) => s.refresh);

  const [question, setQuestion] = useState("");
  const [useRag, setUseRag] = useState(true);
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([]);
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);

  function toggleKb(id: number) {
    setSelectedKbIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  }

  async function handleAsk() {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setAnswer("");
    setCitations([]);
    try {
      const result = await askOnce({
        message: q,
        useRag,
        kbIds: selectedKbIds.length ? selectedKbIds : null,
        onToken: (t) => setAnswer((cur) => cur + t),
      });
      setAnswer(result.answer);
      setCitations(result.citations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get summary");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="h-full overflow-auto px-6 py-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <div>
          <h1 className="text-xl font-semibold">RAG Summary (單次問答)</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            這個頁面是單次提問，不保留聊天上下文。每次送出都只回答這一題。
          </p>
        </div>

        <div className="space-y-3 rounded-lg border border-border bg-white p-4">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={5}
            placeholder="輸入你的問題（例如：幫我總結這份技術文件重點）"
            className="w-full rounded-md border border-border px-3 py-2 text-sm"
          />

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={useRag}
              onChange={(e) => setUseRag(e.target.checked)}
            />
            使用 RAG
          </label>

          {useRag ? (
            <div className="rounded-md border border-border p-3">
              <div className="mb-2 text-xs text-muted-foreground">選擇知識庫</div>
              <div className="flex flex-wrap gap-2">
                {kbs.map((kb) => (
                  <label
                    key={kb.id}
                    className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={selectedKbIds.includes(kb.id)}
                      onChange={() => toggleKb(kb.id)}
                    />
                    {kb.name}
                  </label>
                ))}
                {loaded && kbs.length === 0 ? (
                  <span className="text-xs text-muted-foreground">目前沒有知識庫</span>
                ) : null}
              </div>
            </div>
          ) : null}

          <button
            type="button"
            onClick={handleAsk}
            disabled={loading || !question.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-foreground px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            送出單次問題
          </button>
        </div>

        <div className="rounded-lg border border-border bg-white p-4">
          <div className="text-sm font-medium">回答摘要</div>
          {error ? <div className="mt-2 text-sm text-red-600">{error}</div> : null}
          {!error && !answer ? (
            <div className="mt-2 text-sm text-muted-foreground">尚未產生答案</div>
          ) : (
            <div className="mt-2 whitespace-pre-wrap text-sm">{answer}</div>
          )}
          {citations.length > 0 ? (
            <div className="mt-3 border-t border-border pt-2">
              <div className="text-xs font-medium text-muted-foreground">引用來源</div>
              <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                {citations.map((c) => (
                  <li key={`${c.file_id}-${c.filename}`}>{c.filename}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
