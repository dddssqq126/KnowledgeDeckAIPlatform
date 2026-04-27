"use client";

import { LayoutDashboard, LogOut, MessageSquare, Presentation, Search } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { SidebarItemList } from "./SidebarItemList";
import { useAuthStore } from "../lib/auth-store";
import { useChatSessionsStore } from "../lib/chat-store";
import { useKbStore } from "../lib/kb-store";
import { useSlideStore } from "../lib/slide-store";

/**
 * Single sidebar shared across all (protected) pages. Top nav is fixed; the
 * lower list swaps based on the active section (Knowledge Bases / Chat /
 * Slide Maker). Dashboard hides the lower list entirely.
 */
export function AppSidebar() {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const params = useSearchParams();
  const routeParams = useParams<{ id?: string }>();
  const user = useAuthStore((s) => s.user);
  const clearSession = useAuthStore((s) => s.clearSession);

  const onDashboard = pathname === "/dashboard";
  const onChat = pathname === "/";
  const onPresentonChat = pathname.startsWith("/presenton");
  const onKb = pathname.startsWith("/knowledge-bases");
  const onSlides = pathname.startsWith("/slides");

  function handleLogout() {
    clearSession();
    router.push("/login");
  }

  return (
    <aside className="hidden w-64 flex-col border-r border-zinc-800 bg-zinc-950 text-zinc-100 md:flex">
      <div className="border-b border-zinc-800 px-4 py-4 text-lg font-semibold">
        KnowledgeDeck
      </div>
      <nav className="space-y-1 px-2 py-3 text-sm">
        <NavLink href="/dashboard" active={onDashboard} icon={LayoutDashboard}>
          Dashboard
        </NavLink>
        <NavLink href="/knowledge-bases" active={onKb} icon={Search}>
          Knowledge Bases
        </NavLink>
        <NavLink href="/" active={onChat} icon={MessageSquare}>
          Chat
        </NavLink>
        <NavLink href="/presenton/chat" active={onPresentonChat} icon={MessageSquare}>
          Presenton Chat
        </NavLink>
        <NavLink href="/slides" active={onSlides} icon={Presentation}>
          Slide Maker
        </NavLink>
      </nav>

      {onChat ? (
        <ChatList activeSidParam={params.get("sid")} basePath="/" />
      ) : onPresentonChat ? (
        <ChatList activeSidParam={params.get("sid")} basePath="/presenton/chat" />
      ) : onKb ? (
        <KbList activeIdParam={routeParams?.id ?? null} />
      ) : onSlides ? (
        <SlideList activeIdParam={routeParams?.id ?? null} />
      ) : null /* Dashboard: no lower list per Q1=A. */}

      <div className="border-t border-zinc-800 px-3 py-3 text-xs text-zinc-400">
        <div className="mb-2 truncate" title={user?.username}>
          {user?.username ?? ""}
        </div>
        <button
          type="button"
          onClick={handleLogout}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1 hover:bg-zinc-800 hover:text-zinc-100"
        >
          <LogOut className="h-4 w-4" />
          Logout
        </button>
      </div>
    </aside>
  );
}

function NavLink({
  href,
  active,
  icon: Icon,
  children,
}: {
  href: string;
  active: boolean;
  icon: typeof MessageSquare;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-2 rounded-md px-3 py-2 ${
        active
          ? "bg-zinc-800 text-zinc-100"
          : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
      }`}
    >
      <Icon className="h-4 w-4" />
      {children}
    </Link>
  );
}

// --- Lower-list bindings: each variant subscribes to its own Zustand store ---

function ChatList({
  activeSidParam,
  basePath,
}: {
  activeSidParam: string | null;
  basePath: string;
}) {
  const router = useRouter();
  const sessions = useChatSessionsStore((s) => s.sessions);
  const loaded = useChatSessionsStore((s) => s.loaded);
  const refresh = useChatSessionsStore((s) => s.refresh);
  const newChat = useChatSessionsStore((s) => s.newChat);
  const remove = useChatSessionsStore((s) => s.remove);
  const rename = useChatSessionsStore((s) => s.rename);
  const activeId = activeSidParam ? Number(activeSidParam) : null;

  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);

  return (
    <SidebarItemList
      label="Chats"
      items={sessions}
      loaded={loaded}
      activeId={activeId}
      onSelect={(id) => router.push(`${basePath}?sid=${id}`)}
      onCreate={async () => {
        const s = await newChat();
        router.push(`${basePath}?sid=${s.id}`);
      }}
      onDelete={async (id) => {
        await remove(id);
        if (id === activeId) router.push(basePath);
      }}
      onRename={async (id, title) => {
        await rename(id, title);
      }}
      emptyLabel="Start a new chat"
    />
  );
}

function KbList({ activeIdParam }: { activeIdParam: string | null }) {
  const router = useRouter();
  const kbs = useKbStore((s) => s.kbs);
  const loaded = useKbStore((s) => s.loaded);
  const refresh = useKbStore((s) => s.refresh);
  const create = useKbStore((s) => s.create);
  const remove = useKbStore((s) => s.remove);
  const rename = useKbStore((s) => s.rename);
  const activeId = activeIdParam ? Number(activeIdParam) : null;

  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);

  return (
    <SidebarItemList
      label="Knowledge Bases"
      items={kbs.map((kb) => ({ id: kb.id, title: kb.name }))}
      loaded={loaded}
      activeId={activeId}
      onSelect={(id) => router.push(`/knowledge-bases/${id}`)}
      onCreate={async () => {
        const name = window.prompt("New knowledge base name");
        if (!name?.trim()) return;
        try {
          const created = await create(name.trim());
          router.push(`/knowledge-bases/${created.id}`);
        } catch (err) {
          window.alert(
            err instanceof Error ? err.message : "Failed to create KB",
          );
        }
      }}
      onDelete={async (id) => {
        await remove(id);
        if (id === activeId) router.push("/knowledge-bases");
      }}
      onRename={async (id, name) => {
        await rename(id, name);
      }}
      emptyLabel="No knowledge bases yet"
    />
  );
}

function SlideList({ activeIdParam }: { activeIdParam: string | null }) {
  const router = useRouter();
  const sessions = useSlideStore((s) => s.sessions);
  const loaded = useSlideStore((s) => s.loaded);
  const refresh = useSlideStore((s) => s.refresh);
  const newSession = useSlideStore((s) => s.newSession);
  const remove = useSlideStore((s) => s.remove);
  const rename = useSlideStore((s) => s.rename);
  const activeId = activeIdParam ? Number(activeIdParam) : null;

  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);

  return (
    <SidebarItemList
      label="Slide Decks"
      items={sessions}
      loaded={loaded}
      activeId={activeId}
      onSelect={(id) => router.push(`/slides/${id}`)}
      onCreate={async () => {
        const s = await newSession();
        router.push(`/slides/${s.id}`);
      }}
      onDelete={async (id) => {
        await remove(id);
        if (id === activeId) router.push("/slides");
      }}
      onRename={async (id, title) => {
        await rename(id, title);
      }}
      emptyLabel="Start a new deck"
    />
  );
}
