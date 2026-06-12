"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

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
  const setExternalUser = useAuthStore((s) => s.setExternalUser);

  useEffect(() => {
    const username = resolveExternalUsername();
    setExternalUser(username);
    const next = params.get("next") || "/";
    router.replace(next.startsWith("/") ? next : "/");
  }, [params, router, setExternalUser]);

  return <LoginShell />;
}

function LoginShell() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 text-sm text-muted-foreground">
      Redirecting...
    </main>
  );
}
