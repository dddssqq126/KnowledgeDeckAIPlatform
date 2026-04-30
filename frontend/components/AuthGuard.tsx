"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "../lib/api";
import { useAuthStore } from "../lib/auth-store";
import { AUTO_LOGIN, USE_MOCK_DATA } from "../lib/runtime-config";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const setSession = useAuthStore((s) => s.setSession);
  const clearSession = useAuthStore((s) => s.clearSession);
  // Start as `false` for SSR — `useAuthStore.persist` does not exist on the
  // server (zustand persist is a client-only middleware). The effect below
  // flips this to true once we are on the client and persist has hydrated.
  const [hydrated, setHydrated] = useState(false);
  const [verified, setVerified] = useState(false);

  useEffect(() => {
    const persist = useAuthStore.persist;
    if (!persist) return;
    if (persist.hasHydrated()) {
      setHydrated(true);
      return;
    }
    return persist.onFinishHydration(() => setHydrated(true));
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    if (AUTO_LOGIN || USE_MOCK_DATA) {
      setVerified(true);
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
