"use client";

import { Calendar, Database, Eye, EyeOff, LockKeyhole, MessageSquareText, RefreshCw, Search, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getAdminDatabaseOverview,
  type AdminChatSessionRow,
  type AdminDatabaseOverview,
  type AdminUserRow,
} from "../../../lib/admin";

function formatDate(value: string | null): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function maskPassword(password: string): string {
  if (!password) return "(passwordless)";
  return "•".repeat(Math.min(Math.max(password.length, 6), 16));
}

function countUserMessages(sessions: AdminChatSessionRow[]): number {
  return sessions.reduce(
    (total, session) =>
      total + session.messages.filter((message) => message.role === "user").length,
    0,
  );
}

function countAssistantMessages(sessions: AdminChatSessionRow[]): number {
  return sessions.reduce(
    (total, session) =>
      total + session.messages.filter((message) => message.role === "assistant").length,
    0,
  );
}

export default function AdminDatabasePage() {
  const [overview, setOverview] = useState<AdminDatabaseOverview | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showPasswords, setShowPasswords] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadOverview({ soft = false }: { soft?: boolean } = {}) {
    if (soft) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const data = await getAdminDatabaseOverview();
      setOverview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load database overview");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadOverview();
  }, []);

  const filtered = useMemo(() => {
    if (!overview) return { users: [] as AdminUserRow[], chat_sessions: [] as AdminChatSessionRow[] };
    const normalized = query.trim().toLowerCase();
    if (!normalized) return overview;

    return {
      ...overview,
      users: overview.users.filter((user) =>
        [user.id.toString(), user.username, user.password].some((value) =>
          value.toLowerCase().includes(normalized),
        ),
      ),
      chat_sessions: overview.chat_sessions.filter((session) =>
        [
          session.id.toString(),
          session.owner_username,
          session.title,
          ...session.messages.map((message) => message.content),
        ].some((value) => value.toLowerCase().includes(normalized)),
      ),
    };
  }, [overview, query]);

  const totals = overview?.totals ?? { users: 0, chat_sessions: 0, chat_messages: 0 };
  const userMessages = overview ? countUserMessages(overview.chat_sessions) : 0;
  const assistantMessages = overview ? countAssistantMessages(overview.chat_sessions) : 0;

  return (
    <section className="h-full overflow-auto bg-[radial-gradient(circle_at_top_left,rgba(66,133,244,0.18),transparent_32%),radial-gradient(circle_at_top_right,rgba(168,85,247,0.16),transparent_30%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)))] px-6 py-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="overflow-hidden rounded-[2rem] border border-white/40 bg-white/70 shadow-2xl shadow-blue-500/10 backdrop-blur dark:border-white/10 dark:bg-slate-950/70">
          <div className="relative px-6 py-7 sm:px-8">
            <div className="absolute right-8 top-6 hidden h-28 w-28 rounded-full bg-gradient-to-br from-blue-500 via-purple-500 to-emerald-400 opacity-20 blur-2xl sm:block" />
            <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-3xl">
                <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:border-blue-400/30 dark:bg-blue-500/10 dark:text-blue-200">
                  <Database className="h-3.5 w-3.5" />
                  Admin database console
                </div>
                <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">
                  Login 與對話資料庫管理頁面
                </h1>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  以 Gemini 風格的漸層、玻璃質感卡片呈現 users、chat_sessions 與 chat_messages 目前資料。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setShowPasswords((current) => !current)}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-white dark:border-white/10 dark:bg-white/10 dark:text-slate-100"
                >
                  {showPasswords ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  {showPasswords ? "隱藏密碼" : "顯示密碼"}
                </button>
                <button
                  type="button"
                  onClick={() => void loadOverview({ soft: true })}
                  disabled={refreshing || loading}
                  className="inline-flex items-center gap-2 rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-slate-950/20 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-950"
                >
                  <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                  重新整理
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          <Metric icon={UserRound} label="Login users" value={loading ? "--" : totals.users} tone="from-blue-500 to-cyan-400" />
          <Metric icon={MessageSquareText} label="Chat sessions" value={loading ? "--" : totals.chat_sessions} tone="from-purple-500 to-fuchsia-400" />
          <Metric icon={Database} label="Messages" value={loading ? "--" : totals.chat_messages} tone="from-emerald-500 to-teal-400" />
          <Metric icon={UserRound} label="User prompts" value={loading ? "--" : userMessages} tone="from-amber-500 to-orange-400" />
          <Metric icon={MessageSquareText} label="AI replies" value={loading ? "--" : assistantMessages} tone="from-rose-500 to-pink-400" />
        </div>

        <div className="flex items-center gap-3 rounded-3xl border border-white/50 bg-white/70 px-4 py-3 shadow-lg shadow-slate-200/60 backdrop-blur dark:border-white/10 dark:bg-slate-950/70 dark:shadow-none">
          <Search className="h-5 w-5 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜尋 username、password、對話標題或訊息內容..."
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
        </div>

        {error ? (
          <div className="rounded-3xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-200">
            {error}
          </div>
        ) : null}

        <div className="grid gap-6 xl:grid-cols-[0.92fr_1.08fr]">
          <Panel title="Login database / users" subtitle="users table：帳號、密碼欄位與對話統計">
            {loading ? (
              <LoadingRows />
            ) : filtered.users.length === 0 ? (
              <EmptyState label="找不到符合條件的 login 資料" />
            ) : (
              <div className="space-y-3">
                {filtered.users.map((user) => (
                  <div key={user.id} className="rounded-2xl border border-slate-200/80 bg-white/80 p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.03]">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-500/20 dark:text-blue-200">
                            #{user.id}
                          </span>
                          <h3 className="truncate text-base font-semibold text-slate-950 dark:text-white">{user.username}</h3>
                        </div>
                        <div className="mt-3 grid gap-2 text-sm text-slate-600 dark:text-slate-300">
                          <Field icon={LockKeyhole} label="password" value={showPasswords ? user.password || "(passwordless)" : maskPassword(user.password)} mono />
                          <Field icon={Calendar} label="created" value={formatDate(user.created_at)} />
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-center text-xs">
                        <MiniStat label="sessions" value={user.chat_session_count} />
                        <MiniStat label="messages" value={user.chat_message_count} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Conversation database / chats" subtitle="chat_sessions + chat_messages：完整列印每個 session 的訊息">
            {loading ? (
              <LoadingRows />
            ) : filtered.chat_sessions.length === 0 ? (
              <EmptyState label="找不到符合條件的對話資料" />
            ) : (
              <div className="space-y-4">
                {filtered.chat_sessions.map((session) => (
                  <div key={session.id} className="overflow-hidden rounded-3xl border border-slate-200/80 bg-white/80 shadow-sm dark:border-white/10 dark:bg-white/[0.03]">
                    <div className="border-b border-slate-200/70 bg-gradient-to-r from-blue-50 via-purple-50 to-emerald-50 p-4 dark:border-white/10 dark:from-blue-500/10 dark:via-purple-500/10 dark:to-emerald-500/10">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                            <span>session #{session.id}</span>
                            <span>owner: {session.owner_username} (#{session.owner_user_id})</span>
                            {session.deleted_at ? <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-700 dark:bg-red-500/20 dark:text-red-200">deleted</span> : null}
                          </div>
                          <h3 className="truncate text-base font-semibold text-slate-950 dark:text-white">{session.title}</h3>
                        </div>
                        <MiniStat label="messages" value={session.message_count} />
                      </div>
                      <div className="mt-3 grid gap-2 text-xs text-slate-500 dark:text-slate-400 sm:grid-cols-2">
                        <span>created: {formatDate(session.created_at)}</span>
                        <span>updated: {formatDate(session.updated_at)}</span>
                      </div>
                    </div>
                    <div className="space-y-3 p-4">
                      {session.messages.length === 0 ? (
                        <p className="text-sm text-slate-500">No messages</p>
                      ) : (
                        session.messages.map((message) => (
                          <article key={message.id} className="rounded-2xl border border-slate-200/70 bg-slate-50/80 p-3 dark:border-white/10 dark:bg-slate-900/60">
                            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                              <span className={`rounded-full px-2 py-0.5 font-semibold ${message.role === "user" ? "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-200" : "bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-200"}`}>
                                {message.role} · message #{message.id}
                              </span>
                              <span className="text-slate-500 dark:text-slate-400">{formatDate(message.created_at)}</span>
                            </div>
                            <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700 dark:text-slate-200">{message.content}</p>
                          </article>
                        ))
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </section>
  );
}

type IconComponent = typeof Database;

function Metric({ icon: Icon, label, value, tone }: { icon: IconComponent; label: string; value: number | string; tone: string }) {
  return (
    <div className="rounded-3xl border border-white/50 bg-white/75 p-4 shadow-lg shadow-slate-200/60 backdrop-blur dark:border-white/10 dark:bg-slate-950/70 dark:shadow-none">
      <div className={`mb-3 inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br ${tone} text-white shadow-lg`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-slate-950 dark:text-white">{value}</div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="min-h-[28rem] rounded-[2rem] border border-white/50 bg-white/70 p-4 shadow-xl shadow-slate-200/60 backdrop-blur dark:border-white/10 dark:bg-slate-950/70 dark:shadow-none">
      <div className="mb-4 px-1">
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{title}</h2>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
      </div>
      <div className="nice-scrollbar max-h-[44rem] overflow-auto pr-1">{children}</div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white/80 px-3 py-2 dark:border-white/10 dark:bg-white/5">
      <div className="text-base font-semibold text-slate-950 dark:text-white">{value}</div>
      <div className="text-[0.65rem] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

function Field({ icon: Icon, label, value, mono = false }: { icon: IconComponent; label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <span className="shrink-0 text-xs font-medium uppercase tracking-wide text-slate-400">{label}</span>
      <span className={`min-w-0 truncate ${mono ? "font-mono" : ""}`} title={value}>{value}</span>
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="h-24 animate-pulse rounded-2xl bg-slate-200/70 dark:bg-white/10" />
      ))}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 px-5 py-10 text-center text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
      {label}
    </div>
  );
}
