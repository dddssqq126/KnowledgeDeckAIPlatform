"use client";

import { Presentation, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";

import { useSlideStore } from "../../../../lib/slide-store";

export default function PresentonSlidesPage() {
  const router = useRouter();
  const newSession = useSlideStore((s) => s.newSession);

  async function startPresentonSlideFlow() {
    const session = await newSession();
    router.push(`/slides/${session.id}`);
  }

  return (
    <div className="mx-auto w-full max-w-4xl p-6">
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
        <div className="mb-4 flex items-center gap-2 text-zinc-200">
          <Sparkles className="h-5 w-5" />
          <h1 className="text-xl font-semibold">Presenton 製作簡報流程</h1>
        </div>
        <p className="mb-6 text-sm text-zinc-400">
          從這裡快速建立簡報專案，接著進入編輯頁完成大綱、產生投影片與下載檔案。
        </p>

        <ol className="mb-6 list-decimal space-y-2 pl-5 text-sm text-zinc-300">
          <li>建立新的簡報專案</li>
          <li>輸入主題與內容方向</li>
          <li>生成與調整投影片內容</li>
          <li>匯出簡報檔案</li>
        </ol>

        <button
          type="button"
          onClick={startPresentonSlideFlow}
          className="inline-flex items-center gap-2 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-200"
        >
          <Presentation className="h-4 w-4" />
          開始建立簡報
        </button>
      </div>
    </div>
  );
}
