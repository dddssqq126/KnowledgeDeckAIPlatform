"use client";

import {
  ChevronDown,
  Database,
  SendHorizontal,
  Sparkles,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { KnowledgeBase } from "../lib/knowledge-bases";

type Props = {
  knowledgeBases: KnowledgeBase[];
  disabled: boolean;
  onSend: (
    text: string,
    useRag: boolean,
    kbIds: number[] | null,
    deepMode: boolean,
  ) => void;
  showDeepMode?: boolean;
};

export function ChatInput({
  knowledgeBases,
  disabled,
  onSend,
  showDeepMode = false,
}: Props) {
  const [text, setText] = useState("");
  // Default to RAG enabled. Empty `kb_ids` = no filter (all KBs) on the backend.
  const [useRag, setUseRag] = useState(true);
  const [deepMode, setDeepMode] = useState(false);
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([]);
  const [pickerInitialized, setPickerInitialized] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (pickerInitialized) return;
    if (knowledgeBases.length === 0) return;
    setSelectedKbIds(knowledgeBases.map((kb) => kb.id));
    setPickerInitialized(true);
  }, [knowledgeBases, pickerInitialized]);

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
    onSend(trimmed, useRag, kbIds, useRag && deepMode);
    setText("");
  }

  function toggleKb(id: number) {
    setSelectedKbIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  }

  const allSelected =
    knowledgeBases.length > 0 && selectedKbIds.length === knowledgeBases.length;
  const kbLabel =
    selectedKbIds.length === 0 || allSelected
      ? "All KBs"
      : selectedKbIds.length === 1
        ? (knowledgeBases.find((k) => k.id === selectedKbIds[0])?.name ??
          "1 KB")
        : `${selectedKbIds.length} KBs`;

  return (
    <div className="border-t border-white/70 bg-white/55 px-4 py-4 shadow-[0_-18px_60px_rgba(60,64,67,0.08)] backdrop-blur-2xl">
      <div className="mx-auto max-w-5xl rounded-[2rem] bg-gradient-to-r from-[#d2e3fc] via-[#f8d7e8] to-[#ceead6] p-[1px] shadow-[0_18px_60px_rgba(66,133,244,0.18)]">
        <div className="rounded-[calc(2rem-1px)] bg-white/90 px-4 py-3 backdrop-blur-xl">
          <div className="flex items-start gap-3">
            <div className="mt-1 hidden h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#4285f4] via-[#a142f4] to-[#fbbc04] text-white shadow-md sm:flex">
              <Sparkles className="h-4 w-4" />
            </div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder="Ask KnowledgeDeck anything"
              rows={2}
              className="min-h-14 w-full resize-none bg-transparent text-base leading-7 text-slate-900 outline-none placeholder:text-slate-400 disabled:opacity-50"
              disabled={disabled}
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-[#d2e3fc] bg-[#f8fbff] px-3 py-1.5 text-xs font-medium text-[#1a73e8] transition hover:bg-[#e8f0fe]">
                <input
                  type="checkbox"
                  checked={useRag}
                  onChange={(e) => setUseRag(e.target.checked)}
                  className="h-3.5 w-3.5 accent-[#1a73e8]"
                />
                <Database className="h-3.5 w-3.5" />
                Use RAG
              </label>
              {showDeepMode ? (
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-[#fce8b2] bg-[#fff8e1] px-3 py-1.5 text-xs font-medium text-[#b06000] transition hover:bg-[#feefc3] has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50">
                  <input
                    aria-label="deepmmode"
                    type="checkbox"
                    checked={deepMode}
                    onChange={(e) => setDeepMode(e.target.checked)}
                    disabled={!useRag}
                    className="h-3.5 w-3.5 accent-[#fbbc04] disabled:opacity-40"
                  />
                  <Zap className="h-3.5 w-3.5" />
                  Deep mode
                </label>
              ) : null}
              <div className="relative" ref={pickerRef}>
                <button
                  type="button"
                  onClick={() => setPickerOpen((o) => !o)}
                  disabled={!useRag || knowledgeBases.length === 0}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition hover:border-[#4285f4]/40 hover:text-[#1a73e8] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {kbLabel}
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {pickerOpen ? (
                  <div className="absolute bottom-full mb-2 max-h-64 w-64 overflow-auto rounded-2xl border border-white/80 bg-white/95 p-2 shadow-[0_18px_55px_rgba(60,64,67,0.16)] backdrop-blur-xl">
                    {knowledgeBases.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-slate-500">
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
                            className="flex-1 rounded-full px-3 py-1.5 text-xs font-medium text-[#1a73e8] hover:bg-[#e8f0fe]"
                          >
                            Select all
                          </button>
                          <button
                            type="button"
                            onClick={() => setSelectedKbIds([])}
                            className="flex-1 rounded-full px-3 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100"
                          >
                            Clear
                          </button>
                        </div>
                        <div className="my-1 border-t border-slate-100" />
                        {knowledgeBases.map((kb) => (
                          <label
                            key={kb.id}
                            className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-[#f8fbff] hover:text-[#1a73e8]"
                          >
                            <input
                              type="checkbox"
                              checked={selectedKbIds.includes(kb.id)}
                              onChange={() => toggleKb(kb.id)}
                              className="h-3.5 w-3.5 accent-[#1a73e8]"
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
              className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-[#1a73e8] via-[#5f7cf7] to-[#a142f4] px-4 py-2 text-sm font-semibold text-white shadow-[0_10px_28px_rgba(66,133,244,0.28)] transition hover:-translate-y-0.5 hover:shadow-[0_14px_34px_rgba(66,133,244,0.34)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
            >
              {disabled ? "Thinking" : "Send"}
              <SendHorizontal className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
