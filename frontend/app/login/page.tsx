"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { isAxiosError } from "axios";

import { api } from "../../lib/api";
import { useAuthStore } from "../../lib/auth-store";

const ERROR_KEYS: Record<string, string> = {
  invalid_credentials: "auth.error.invalid_credentials",
};

const ERROR_FALLBACKS: Record<string, string> = {
  "auth.error.invalid_credentials": "Incorrect username or password.",
  "auth.error.network": "Could not reach the server. Please try again.",
};

type LoginResponse = {
  user?: { id?: number; username?: string };
  username?: string;
  message?: string;
};

function extractUsername(data: LoginResponse): string {
  if (typeof data.user?.username === "string") return data.user.username;
  if (typeof data.username === "string") return data.username;
  if (typeof data.message === "string") return data.message;
  return "";
}

export default function LoginPage() {
  const router = useRouter();
  const setSession = useAuthStore((s) => s.setSession);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrorKey(null);
    setSubmitting(true);
    try {
      const res = await api.post<LoginResponse>("/auth/login", { username, password });
      const returnedName = extractUsername(res.data).trim();
      if (!returnedName || returnedName !== username.trim()) {
        setErrorKey("auth.error.invalid_credentials");
        return;
      }

      setSession({
        id: res.data.user?.id ?? 0,
        username: returnedName,
      });
      router.push("/chat");
    } catch (err) {
      if (isAxiosError(err) && err.response?.data?.detail) {
        const detail = err.response.data.detail as string;
        setErrorKey(ERROR_KEYS[detail] ?? "auth.error.network");
      } else {
        setErrorKey("auth.error.network");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-white p-6 shadow-sm"
        aria-label="Login form"
      >
        <h1 className="text-xl font-semibold">KnowledgeDeck</h1>
        <div className="space-y-2">
          <label htmlFor="username" className="block text-sm">Username</label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="password" className="block text-sm">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm"
          />
        </div>
        {errorKey ? (
          <div data-testid="login-error" data-error-key={errorKey} className="text-sm text-red-600">
            {ERROR_FALLBACKS[errorKey] ?? errorKey}
          </div>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-foreground px-3 py-2 text-sm text-white disabled:opacity-50"
        >
          {submitting ? "..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
