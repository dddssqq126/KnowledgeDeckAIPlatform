"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { api } from "../../lib/api";
import { resolveExternalUsername, useAuthStore } from "../../lib/auth-store";

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginShell />}>
      <LoginRedirect />
    </Suspense>
  );
}

function LoginRedirect() {
  const router = useRouter();
  const params = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);

  useEffect(() => {
    let cancelled = false;
    const username = resolveExternalUsername();
    (async () => {
      try {
        // Passwordless login: exchange the URL-derived username for a real
        // token so AuthGuard + the API's Bearer interceptor work. Without a
        // token the guard bounces us back here forever.
        const res = await api.post<{
          token: string;
          user: { id: number; username: string };
        }>("/auth/external", { username });
        if (cancelled) return;
        setSession(res.data.token, res.data.user);
        const next = params.get("next") || "/";
        router.replace(next.startsWith("/") ? next : "/");
      } catch {
        // Backend unreachable / provisioning failed: stay on the shell rather
        // than redirecting into a guard loop.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params, router, setSession]);

  return <LoginShell />;
}

function LoginShell() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 text-sm text-muted-foreground">
      Redirecting...
    </main>
  );
}
