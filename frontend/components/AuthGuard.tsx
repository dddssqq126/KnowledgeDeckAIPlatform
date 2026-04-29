"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "../lib/api";
import { useAuthStore } from "../lib/auth-store";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const setSession = useAuthStore((s) => s.setSession);
  const clearSession = useAuthStore((s) => s.clearSession);
  // Start as `false` for SSR — auth persistence is client-only.
  const [hydrated, setHydrated] = useState(false);
  const [verified, setVerified] = useState(false);

  useEffect(() => {
    useAuthStore.persist.rehydrate().finally(() => setHydrated(true));
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    api
      .get("/auth/me")
      .then((res) => {
        if (cancelled) return;
        setSession(token, { id: res.data.id, username: res.data.username });
        setVerified(true);
      })
      .catch(() => {
        if (cancelled) return;
        clearSession();
        router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, token, router, setSession, clearSession]);

  if (!hydrated || !verified) return null;
  return <>{children}</>;
}
