"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuthStore } from "../../lib/auth-store";

export default function LoginPage() {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    if (token) router.replace("/");
  }, [token, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="rounded-lg border border-border bg-white p-6 text-sm text-zinc-700 shadow-sm">
        Login is disabled. Using default token and owner user.
      </div>
    </main>
  );
}
