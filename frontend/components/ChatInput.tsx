"use client";

import { useEffect, useRef, useState } from "react";

import type { KnowledgeBase } from "../lib/knowledge-bases";

type Props = {
  knowledgeBases: KnowledgeBase[];
  disabled: boolean;
  onSend: (text: string, useRag: boolean, kbIds: number[] | null) => void;
};

export function ChatInput({ knowledgeBases, disabled, onSend }: Props) {
  const [text, setText] = useState("");
  // Default to RAG enabled — most users want grounded answers and toggling
  // off is one click. Empty `kb_ids` = no filter (all KBs) on the backend.
  const [useRag, setUseRag] = useState(true);
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([]);
  const [pickerInitialized, setPickerInitialized] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);

  // Once the KB list arrives, default to "everything checked" so the user
  // sees the explicit selection (matches the spirit of "All KBs").
  useEffect(() => {
    if (pickerInitialized) return;
    if (knowledgeBases.length === 0) return;
    setSelectedKbIds(knowledgeBases.map((kb) => kb.id));
    setPickerInitialized(true);
  }, [knowledgeBases, pickerInitialized]);

  // Close the KB picker when clicking outside.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!pickerRef.current?.contains(e.target as Node)) setPickerOpen(false);
    }
    if (pickerOpen) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [pickerOpen]);

  function submit() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    const kbIds = selectedKbIds.length === 0 ? null : selectedKbIds;
    onSend(trimmed, useRag, kbIds);
    setText("");
  }

  function toggleKb(id: number) {
    setSelectedKbIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  }

  const allSelected =
    knowledgeBases.length > 0 &&
    selectedKbIds.length === knowledgeBases.length;
  const kbLabel =
    selectedKbIds.length === 0 || allSelected
      ? "All KBs"
      : selectedKbIds.length === 1
        ? knowledgeBases.find((k) => k.id === selectedKbIds[0])?.name ?? "1 KB"
        : `${selectedKbIds.length} KBs`;

  return (
    <div className="border-t border-zinc-800 bg-zinc-950 p-3">
      <div className="mx-auto max-w-5xl rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask anything (Enter to send, Shift+Enter for newline)…"
          rows={2}
          className="w-full resize-none bg-transparent text-sm text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-50"
          disabled={disabled}
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400">
              <input
                type="checkbox"
                checked={useRag}
                onChange={(e) => setUseRag(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Use RAG
            </label>
            <div className="relative" ref={pickerRef}>
              <button
                type="button"
                onClick={() => setPickerOpen((o) => !o)}
                disabled={!useRag || knowledgeBases.length === 0}
                className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
              >
                {kbLabel} ▾
              </button>
              {pickerOpen ? (
                <div className="absolute bottom-full mb-1 w-56 max-h-64 overflow-auto rounded-md border border-zinc-700 bg-zinc-900 p-2 shadow-lg">
                  {knowledgeBases.length === 0 ? (
                    <div className="px-2 py-1 text-xs text-zinc-400">
                      No knowledge bases yet
                    </div>
                  ) : (
                    <>
                      <div className="flex gap-1 px-1 pb-1">
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedKbIds(knowledgeBases.map((k) => k.id))
                          }
                          className="flex-1 rounded px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-800"
                        >
                          Select all
                        </button>
                        <button
                          type="button"
                          onClick={() => setSelectedKbIds([])}
                          className="flex-1 rounded px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-800"
                        >
                          Clear
                        </button>
                      </div>
                      <div className="my-1 border-t border-zinc-700" />
                      {knowledgeBases.map((kb) => (
                        <label
                          key={kb.id}
                          className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-800"
                        >
                          <input
                            type="checkbox"
                            checked={selectedKbIds.includes(kb.id)}
                            onChange={() => toggleKb(kb.id)}
                            className="h-3.5 w-3.5"
                          />
                          <span className="truncate">{kb.name}</span>
                        </label>
                      ))}
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !text.trim()}
            className="rounded-md bg-foreground px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {disabled ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
