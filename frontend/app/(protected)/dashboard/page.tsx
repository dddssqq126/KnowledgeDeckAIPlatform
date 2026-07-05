"use client";

import {
  FileText,
  Library,
  MessageSquare,
  Presentation,
} from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { useChatSessionsStore } from "../../../lib/chat-store";
import { useKbStore } from "../../../lib/kb-store";
import { useSlideStore } from "../../../lib/slide-store";

export default function DashboardPage() {
  const kbs = useKbStore((s) => s.kbs);
  const kbsLoaded = useKbStore((s) => s.loaded);
  const refreshKbs = useKbStore((s) => s.refresh);

  const sessions = useChatSessionsStore((s) => s.sessions);
  const sessionsLoaded = useChatSessionsStore((s) => s.loaded);
  const refreshSessions = useChatSessionsStore((s) => s.refresh);

  const slideSessions = useSlideStore((s) => s.sessions);
  const projectsLoaded = useSlideStore((s) => s.loaded);
  const refreshProjects = useSlideStore((s) => s.refresh);

  useEffect(() => {
    if (!kbsLoaded) refreshKbs();
  }, [kbsLoaded, refreshKbs]);
  useEffect(() => {
    if (!sessionsLoaded) refreshSessions();
  }, [sessionsLoaded, refreshSessions]);
  useEffect(() => {
    if (!projectsLoaded) refreshProjects();
  }, [projectsLoaded, refreshProjects]);

  const allLoaded = kbsLoaded && sessionsLoaded && projectsLoaded;
  const fileCount = kbs.reduce((sum, kb) => sum + kb.file_count, 0);

  return (
    <section className="h-full overflow-auto px-6 py-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Overview of your knowledge bases, conversations, and slide
            projects.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard
            icon={Library}
            label="Knowledge Bases"
            value={allLoaded ? kbs.length : "—"}
            href="/knowledge-bases"
          />
          <StatCard
            icon={FileText}
            label="Files"
            value={allLoaded ? fileCount : "—"}
            href="/knowledge-bases"
          />
          <StatCard
            icon={MessageSquare}
            label="Chats"
            value={allLoaded ? sessions.length : "—"}
            href="/"
          />
          <StatCard
            icon={Presentation}
            label="Slide Decks"
            value={allLoaded ? slideSessions.length : "—"}
            href="/slides"
          />
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <ModuleCard
            href="/knowledge-bases"
            icon={Library}
            title="Knowledge Bases"
            body={
              "Drop TXT, PDF, or CS files (single or whole folders) into a knowledge base. Each upload is parsed, chunked, embedded with bge-m3, and indexed in Qdrant — usable from Chat and Slide Maker as RAG context."
            }
          />
          <ModuleCard
            href="/"
            icon={MessageSquare}
            title="Chat"
            body={
              "Streaming conversation with Gemma 4. Toggle Use RAG to ground answers in selected knowledge bases; the assistant cites the files it pulled from."
            }
          />
          <ModuleCard
            href="/slides"
            icon={Presentation}
            title="Slide Maker"
            body={
              "Generate a slide outline from a single prompt, optionally grounded in your knowledge bases. The mock release downloads the outline as text; Presenton-rendered PPTX is on the roadmap."
            }
          />
        </div>
      </div>
    </section>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  href,
}: {
  icon: typeof Library;
  label: string;
  value: number | string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-lg border border-border bg-white p-4 transition-colors hover:border-foreground/20 hover:bg-muted/40"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </Link>
  );
}

function ModuleCard({
  icon: Icon,
  title,
  body,
  href,
}: {
  icon: typeof Library;
  title: string;
  body: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-lg border border-border bg-white p-4 transition-colors hover:border-foreground/20 hover:bg-muted/40"
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {body}
      </p>
    </Link>
  );
}
