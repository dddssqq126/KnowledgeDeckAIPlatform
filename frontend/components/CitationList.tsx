import type { Citation } from "../lib/chat";

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-2 border-t border-zinc-700 pt-2 text-xs text-zinc-400">
      Sources:{" "}
      {citations.map((c, i) => (
        <span key={c.file_id}>
          {i > 0 ? ", " : ""}
          {c.filename}
          {c.doc_type ? (
            <span className="ml-1 rounded bg-zinc-700 px-1 text-[10px] text-zinc-200">
              {c.doc_type}
            </span>
          ) : null}
          {c.vendor && c.vendor !== "unknown" ? (
            <span className="ml-1 rounded bg-amber-900/50 px-1 text-[10px] text-amber-100">
              {c.vendor}
            </span>
          ) : null}
          {c.platform && c.platform !== "unknown" ? (
            <span className="ml-1 rounded bg-cyan-900/50 px-1 text-[10px] text-cyan-100">
              {c.platform}
            </span>
          ) : null}
          {c.knowledge_type && c.knowledge_type !== "unknown" ? (
            <span className="ml-1 rounded bg-violet-900/50 px-1 text-[10px] text-violet-100">
              {c.knowledge_type}
            </span>
          ) : null}
          {(c.tags_topic ?? []).map((t) => (
            <span key={t} className="ml-1 text-[10px] text-zinc-500">
              #{t}
            </span>
          ))}
        </span>
      ))}
    </div>
  );
}
