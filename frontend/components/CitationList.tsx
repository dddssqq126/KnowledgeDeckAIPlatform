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
