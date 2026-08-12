"use client";

import { Download, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { RelatedImage } from "../lib/chat";
import { downloadKnowledgeFile } from "../lib/knowledge-bases";

type LoadedImage = RelatedImage & { objectUrl: string };

function sourceLabel(image: RelatedImage): string {
  return image.source_extension === "pptx"
    ? `${image.source_filename} · PPTX slide ${image.page_number}`
    : `${image.source_filename} · PDF page ${image.page_number}`;
}

export function RelatedImageStrip({ images }: { images: RelatedImage[] }) {
  const [loaded, setLoaded] = useState<LoadedImage[]>([]);
  const [selected, setSelected] = useState<LoadedImage | null>(null);

  useEffect(() => {
    let cancelled = false;
    const objectUrls: string[] = [];
    void Promise.all(
      images.slice(0, 5).map(async (image) => {
        const response = await api.get<Blob>(image.content_url, {
          responseType: "blob",
        });
        const objectUrl = URL.createObjectURL(response.data);
        objectUrls.push(objectUrl);
        return { ...image, objectUrl };
      }),
    )
      .then((items) => {
        if (!cancelled) setLoaded(items);
      })
      .catch(() => {
        if (!cancelled) setLoaded([]);
      });
    return () => {
      cancelled = true;
      if (typeof URL.revokeObjectURL === "function") {
        for (const url of objectUrls) URL.revokeObjectURL(url);
      }
    };
  }, [images]);

  if (!loaded.length) return null;

  return (
    <>
      <div className="mt-4 border-t border-border/60 pt-3">
        <div className="mb-2 text-sm text-muted-foreground">Related images</div>
        <div className="flex max-w-full gap-3 overflow-x-auto pb-1">
          {loaded.map((image) => (
            <button
              type="button"
              key={image.id}
              onClick={() => setSelected(image)}
              className="w-36 shrink-0 overflow-hidden rounded-lg border border-border bg-card text-left shadow-sm hover:border-foreground/30"
              aria-label={`Open ${image.name}`}
            >
              <img
                src={image.objectUrl}
                alt={image.name}
                className="h-24 w-full object-cover"
              />
              <span className="block truncate px-2 py-1.5 text-xs" title={image.name}>
                {image.name}
              </span>
              <span className="block truncate px-2 pb-1.5 text-[11px] text-muted-foreground" title={sourceLabel(image)}>
                {sourceLabel(image)}
              </span>
            </button>
          ))}
        </div>
      </div>
      {selected ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={selected.name}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-6"
          onClick={() => setSelected(null)}
        >
          <div
            className="relative max-h-full max-w-5xl overflow-auto rounded-xl bg-card p-4 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="absolute right-3 top-3 rounded-full bg-background/90 p-2"
              aria-label="Close image"
            >
              <X className="h-4 w-4" />
            </button>
            <img
              src={selected.objectUrl}
              alt={selected.name}
              className="max-h-[75vh] max-w-full object-contain"
            />
            <div className="mt-3 font-medium">{selected.name}</div>
            <div className="text-sm text-muted-foreground">{sourceLabel(selected)}</div>
            <button
              type="button"
              onClick={() => void downloadKnowledgeFile(selected.source_file_id, selected.source_filename)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              <Download className="h-4 w-4" /> Download source file
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
