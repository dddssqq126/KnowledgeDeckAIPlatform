"use client";

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
    attachments: File[],
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
  const [attachments, setAttachments] = useState<File[]>([]);
  const [validationMessage, setValidationMessage] = useState<string | null>(
    null,
  );
  const fileInputRef = useRef<HTMLInputElement | null>(null);
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
    if (disabled) return;
    if (!trimmed) {
      setValidationMessage("請記得輸入資料");
      return;
    }
    const kbIds = selectedKbIds.length === 0 ? null : selectedKbIds;
    onSend(trimmed, useRag, kbIds, useRag && deepMode, attachments);
    setText("");
    setValidationMessage(null);
    setAttachments([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function toggleKb(id: number) {
    setSelectedKbIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  }

  function addAttachments(files: FileList | null) {
    if (!files?.length) return;
    setAttachments((current) => [...current, ...Array.from(files)]);
  }

  function removeAttachment(index: number) {
    setAttachments((current) => current.filter((_, i) => i !== index));
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
          onChange={(e) => {
            setText(e.target.value);
            if (validationMessage) setValidationMessage(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask anything (Enter to send, Shift+Enter for newline)"
          rows={2}
          className="w-full resize-none bg-transparent text-sm text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-50"
          disabled={disabled}
        />
        {validationMessage ? (
          <div
            className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs text-amber-200"
            role="alert"
            aria-live="polite"
          >
            {validationMessage}
          </div>
        ) : null}
        {attachments.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {attachments.map((file, index) => (
              <span
                key={`${file.name}-${file.size}-${index}`}
                className="inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-200"
              >
                <span className="max-w-48 truncate">{file.name}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(index)}
                  className="text-zinc-400 hover:text-zinc-100"
                  aria-label={`Remove ${file.name}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.cs,.md,.py,.html,.css,.pptx"
              onChange={(e) => addAttachments(e.target.files)}
              className="hidden"
              disabled={disabled}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled}
              className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
            >
              Attach files
            </button>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400">
              <input
                type="checkbox"
                checked={useRag}
                onChange={(e) => setUseRag(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Use RAG
            </label>
            {showDeepMode ? (
              <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={deepMode}
                  onChange={(e) => setDeepMode(e.target.checked)}
                  disabled={!useRag}
                  className="h-3.5 w-3.5 disabled:opacity-40"
                />
                deepmmode
              </label>
            ) : null}
            <div className="relative" ref={pickerRef}>
              <button
                type="button"
                onClick={() => setPickerOpen((o) => !o)}
                disabled={!useRag || knowledgeBases.length === 0}
                className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
              >
                {kbLabel} v
              </button>
              {pickerOpen ? (
                <div className="absolute bottom-full mb-1 max-h-64 w-56 overflow-auto rounded-md border border-zinc-700 bg-zinc-900 p-2 shadow-lg">
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
            disabled={disabled}
            className="rounded-md bg-foreground px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {disabled ? "..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
