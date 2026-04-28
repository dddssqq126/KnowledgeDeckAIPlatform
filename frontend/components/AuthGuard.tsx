"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useAuthStore } from "../lib/auth-store";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!user?.username) {
      router.replace("/login");
    }
  }, [hydrated, user, router]);

  if (!hydrated || !user?.username) return null;
  return <>{children}</>;
}
