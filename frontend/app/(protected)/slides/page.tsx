"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { recordLoginRecordSilently } from "../../../lib/login-records";
import { useSlideStore } from "../../../lib/slide-store";

export default function SlidesIndexPage() {
  const router = useRouter();
  const newSession = useSlideStore((s) => s.newSession);

  useEffect(() => {
    recordLoginRecordSilently();
  }, []);

  async function handleNew() {
    const s = await newSession();
    router.push(`/slides/${s.id}`);
  }

  return (
    <section className="h-full overflow-auto px-6 py-6">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-xl font-semibold">Slide Maker</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          Chat with the slide planner to draft an outline grounded in your
          knowledge bases. When the outline is ready, render to PPTX via
          Presenton.
        </p>
        <div className="mt-6 rounded-lg border border-dashed border-border bg-white p-10 text-center">
          <p className="text-sm text-muted-foreground">
            Pick a deck from the sidebar, or start a new one.
          </p>
          <button
            type="button"
            onClick={handleNew}
            className="mt-4 inline-flex items-center gap-1 rounded-md bg-foreground px-3 py-1.5 text-sm text-white"
          >
            <Plus className="h-4 w-4" /> New deck
          </button>
        </div>
      </div>
    </section>
  );
}
