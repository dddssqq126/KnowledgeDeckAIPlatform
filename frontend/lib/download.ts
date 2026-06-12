"use client";

export function safeFilename(value: string, fallback = "download"): string {
  const cleaned = value
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, " ")
    .slice(0, 120);
  return cleaned || fallback;
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadTextFile(
  content: string,
  filename: string,
  type = "text/markdown;charset=utf-8",
): void {
  downloadBlob(new Blob([content], { type }), filename);
}
