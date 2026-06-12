"use client";

import {
  Database,
  FileText,
  LayoutDashboard,
  LayoutTemplate,
  MessageSquare,
  Moon,
  Palette,
  Presentation,
  Search,
  Settings,
  Sparkles,
  Sun,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SidebarItemList } from "./SidebarItemList";
import { useAuthStore } from "../lib/auth-store";
import { searchChatSessions, type ChatSearchResult } from "../lib/chat";
import { useChatSessionsStore } from "../lib/chat-store";
import { useKbStore } from "../lib/kb-store";
import { useSlideStore } from "../lib/slide-store";
import { useThemeStore } from "../lib/theme-store";

/**
 * Single sidebar shared across all (protected) pages. Top nav is fixed; the
 * lower list swaps based on the active section (Knowledge Bases / Chat /
 * Slide Maker). Dashboard hides the lower list entirely.
 */
export function AppSidebar() {
  const pathname = usePathname() ?? "/";
  const params = useSearchParams();
  const routeParams = useParams<{ id?: string }>();
  const user = useAuthStore((s) => s.user);
  const externalUsername = useAuthStore((s) => s.externalUsername);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);

  const onDashboard = pathname === "/dashboard";
  const onChat = pathname === "/";
  const onKb = pathname.startsWith("/knowledge-bases");
  const onSlides = pathname.startsWith("/slides");
  const onRagDatabases = pathname.startsWith("/rag-databases");
  const onPresenton = pathname.startsWith("/presenton");

  return (
    <aside className="hidden w-72 flex-col border-r border-border bg-card/90 md:flex">
      <div className="flex items-center justify-between border-b border-border px-5 py-5 text-xl font-semibold">
        <span>KnowledgeDeck</span>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </div>
      <nav className="space-y-1.5 px-3 py-4 text-base">
        <NavLink href="/dashboard" active={onDashboard} icon={LayoutDashboard}>
          Dashboard
        </NavLink>
        <NavLink href="/knowledge-bases" active={onKb} icon={Search}>
          Knowledge Bases
        </NavLink>
        <NavLink href="/rag-databases" active={onRagDatabases} icon={Database}>
          RAG Databases
        </NavLink>
        <NavLink href="/" active={onChat} icon={MessageSquare}>
          Chat
        </NavLink>
        <NavLink href="/slides" active={onSlides} icon={Presentation}>
          Slide Maker
        </NavLink>
        <NavLink href="/presenton" active={onPresenton} icon={Sparkles}>
          Presenton
        </NavLink>
      </nav>

      {onChat ? (
        <ChatList activeSidParam={params.get("sid")} />
      ) : onKb ? (
        <KbList activeIdParam={routeParams?.id ?? null} />
      ) : onSlides ? (
        <SlideList activeIdParam={routeParams?.id ?? null} />
      ) : onPresenton ? (
        <PresentonList pathname={pathname} />
      ) : null /* Dashboard: no lower list per Q1=A. */}

      <div className="border-t border-border px-4 py-4 text-sm text-muted-foreground">
        <div className="mb-2 truncate" title={user?.username ?? externalUsername}>
          {user?.username ?? externalUsername}
        </div>
        <div className="rounded-md border border-border px-3 py-2">
          External login user
        </div>
      </div>
    </aside>
  );
}

const presentonItems = [
  { id: 1, title: "Dashboard", href: "/presenton", icon: LayoutDashboard },
  { id: 2, title: "New Presentation", href: "/presenton/upload", icon: Upload },
  { id: 3, title: "Documents Preview", href: "/presenton/documents-preview", icon: FileText },
  { id: 4, title: "Outline", href: "/presenton/outline", icon: Sparkles },
  { id: 5, title: "Presentation Editor", href: "/presenton/presentation", icon: Presentation },
  { id: 6, title: "Templates", href: "/presenton/templates", icon: LayoutTemplate },
  { id: 7, title: "Template Preview", href: "/presenton/template-preview", icon: Search },
  { id: 8, title: "Custom Template", href: "/presenton/custom-template", icon: LayoutTemplate },
  { id: 9, title: "Themes", href: "/presenton/themes", icon: Palette },
  { id: 10, title: "Media and Fonts", href: "/presenton/media", icon: Search },
  { id: 11, title: "Settings", href: "/presenton/settings", icon: Settings },
];

function PresentonList({ pathname }: { pathname: string }) {
  return (
    <div className="nice-scrollbar min-h-0 flex-1 overflow-auto border-t border-border px-3 py-4">
      <div className="mb-3 px-2 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Presenton
      </div>
      <div className="space-y-1.5">
        {presentonItems.map(({ href, icon: Icon, title }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-base ${
                active
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <Icon className="h-5 w-5" />
              <span className="truncate">{title}</span>
            </Link>
          );
        })}
      </div>
      <div className="mt-4 rounded-md border border-dashed border-border px-3 py-3 text-sm leading-relaxed text-muted-foreground">
        Presenton opens the original app from NEXT_PUBLIC_PRESENTON_APP_URL.
      </div>
    </div>
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
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      <Icon className="h-5 w-5" />
      {children}
    </Link>
  );
}

// --- Lower-list bindings: each variant subscribes to its own Zustand store ---

function ChatList({ activeSidParam }: { activeSidParam: string | null }) {
  const router = useRouter();
  const sessions = useChatSessionsStore((s) => s.sessions);
  const loaded = useChatSessionsStore((s) => s.loaded);
  const refresh = useChatSessionsStore((s) => s.refresh);
  const newChat = useChatSessionsStore((s) => s.newChat);
  const remove = useChatSessionsStore((s) => s.remove);
  const rename = useChatSessionsStore((s) => s.rename);
  const activeId = activeSidParam ? Number(activeSidParam) : null;
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ChatSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const id = window.setTimeout(() => {
      searchChatSessions(trimmed)
        .then((items) => {
          if (!cancelled) setResults(items);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [query]);

  return (
    <>
      <div className="border-t border-border px-3 pt-4">
        {query.trim() ? (
          <div className="mb-3 flex items-center justify-between px-1 text-sm font-medium uppercase tracking-wide text-muted-foreground">
            <span>Search Chats</span>
          </div>
        ) : null}
        <SearchBox value={query} onChange={setQuery} />
      </div>
      {query.trim() ? (
        <div className="nice-scrollbar min-h-0 flex-1 overflow-auto px-3 py-3">
          <div className="space-y-1.5">
            {searching ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">Searching...</div>
            ) : results.length === 0 ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">No matches</div>
            ) : (
              results.map((item) => (
                <button
                  key={`${item.session_id}:${item.created_at}:${item.snippet}`}
                  type="button"
                  onClick={() => router.push(`/?sid=${item.session_id}`)}
                  className={`w-full rounded-md px-3 py-2.5 text-left ${
                    item.session_id === activeId
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <div className="truncate text-base font-medium">{item.session_title}</div>
                  <div className="mt-1 line-clamp-2 text-sm leading-5 text-muted-foreground">
                    {item.snippet}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      ) : (
        <SidebarItemList
          label="Chats"
          items={sessions}
          loaded={loaded}
          activeId={activeId}
          onSelect={(id) => router.push(`/?sid=${id}`)}
          onCreate={async () => {
            const s = await newChat();
            router.push(`/?sid=${s.id}`);
          }}
          onDelete={async (id) => {
            await remove(id);
            if (id === activeId) router.push("/");
          }}
          onRename={async (id, title) => {
            await rename(id, title);
          }}
          emptyLabel="Start a new chat"
        />
      )}
    </>
  );
}

function SearchBox({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex h-11 items-center gap-2 rounded-full border border-border bg-background px-3 text-sm text-muted-foreground focus-within:border-foreground/40">
      <Search className="h-4 w-4" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search chats"
        className="min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground"
      />
    </label>
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
