"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type LoginUserContext = {
  DeptName: string | null;
  Chinesename: string | null;
  DeptID: string | null;
  EmpId: string | null;
  UserAccountName: string;
};

type UserContextInput = Partial<
  Record<keyof LoginUserContext, string | null | undefined>
>;

type UserContextValue = {
  userContext: LoginUserContext;
  setUserContext: (next: LoginUserContext) => void;
  clearUserContext: () => void;
};

const DEFAULT_USER_CONTEXT: LoginUserContext = {
  DeptName: null,
  Chinesename: null,
  DeptID: null,
  EmpId: null,
  UserAccountName: "",
};

const STORAGE_KEY = "knowledgedeck-user-context";

const UserContext = createContext<UserContextValue | null>(null);

function trimOrNull(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function trimOrEmpty(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

function findSearchParam(params: URLSearchParams, names: string[]): string | null {
  for (const name of names) {
    const exact = params.get(name);
    if (exact !== null) return exact;
  }

  const normalizedNames = new Set(names.map((name) => name.toLowerCase()));
  for (const [key, value] of params.entries()) {
    if (normalizedNames.has(key.toLowerCase())) return value;
  }

  return null;
}

function readStoredUserContext(): LoginUserContext {
  if (typeof window === "undefined") return DEFAULT_USER_CONTEXT;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_USER_CONTEXT;
    const parsed = JSON.parse(raw) as Partial<LoginUserContext>;
    return normalizeUserContext(parsed);
  } catch {
    return DEFAULT_USER_CONTEXT;
  }
}

function writeStoredUserContext(next: LoginUserContext): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

export function normalizeUserContext(value: UserContextInput): LoginUserContext {
  return {
    DeptName: trimOrNull(value.DeptName),
    Chinesename: trimOrNull(value.Chinesename),
    DeptID: trimOrNull(value.DeptID),
    EmpId: trimOrNull(value.EmpId),
    UserAccountName: trimOrEmpty(value.UserAccountName),
  };
}

export function resolveUserContextFromLocation(): LoginUserContext {
  if (typeof window === "undefined") return DEFAULT_USER_CONTEXT;

  const stored = readStoredUserContext();
  const params = new URLSearchParams(window.location.search);
  const fromUrl = normalizeUserContext({
    DeptName: findSearchParam(params, ["DeptName", "dept_name"]),
    Chinesename: findSearchParam(params, [
      "Chinesename",
      "ChineseName",
      "chinese_name",
    ]),
    DeptID: findSearchParam(params, ["DeptID", "dept_id"]),
    EmpId: findSearchParam(params, ["EmpId", "EmpID", "emp_id"]),
    UserAccountName: findSearchParam(params, [
      "UserAccountName",
      "user_account_name",
      "username",
      "user_name",
      "user",
      "name",
    ]),
  });

  return {
    DeptName: fromUrl.DeptName ?? stored.DeptName,
    Chinesename: fromUrl.Chinesename ?? stored.Chinesename,
    DeptID: fromUrl.DeptID ?? stored.DeptID,
    EmpId: fromUrl.EmpId ?? stored.EmpId,
    UserAccountName: fromUrl.UserAccountName || stored.UserAccountName,
  };
}

export function UserProvider({ children }: { children: ReactNode }) {
  const [userContext, setUserContextState] = useState<LoginUserContext>(
    DEFAULT_USER_CONTEXT,
  );

  useEffect(() => {
    const resolved = resolveUserContextFromLocation();
    setUserContextState(resolved);
    writeStoredUserContext(resolved);
  }, []);

  const setUserContext = useCallback((next: LoginUserContext) => {
    const normalized = normalizeUserContext(next);
    setUserContextState(normalized);
    writeStoredUserContext(normalized);
  }, []);

  const clearUserContext = useCallback(() => {
    setUserContextState(DEFAULT_USER_CONTEXT);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const value = useMemo(
    () => ({ userContext, setUserContext, clearUserContext }),
    [clearUserContext, setUserContext, userContext],
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUserContext(): UserContextValue {
  const value = useContext(UserContext);
  if (!value) {
    throw new Error("useUserContext must be used within UserProvider");
  }
  return value;
}
