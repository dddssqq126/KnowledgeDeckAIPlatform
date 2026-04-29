"use client";

import { useEffect, useState, type ReactNode } from "react";

import { useAuthStore } from "../lib/auth-store";

export function AuthGuard({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    useAuthStore.persist.rehydrate().finally(() => setHydrated(true));
  }, []);

  if (!hydrated || !token) return null;
  return <>{children}</>;
}
