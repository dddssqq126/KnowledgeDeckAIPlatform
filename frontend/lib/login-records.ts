"use client";

import {
  resolveUserContextFromLocation,
  type LoginUserContext,
} from "../app/UserContext";
import { api } from "./api";

export type LoginRecordPayload = LoginUserContext;

export async function recordLoginRecord(
  context: LoginRecordPayload = resolveUserContextFromLocation(),
): Promise<void> {
  if (!context.UserAccountName) return;
  await api.post("/auth/login-records", context);
}

export function recordLoginRecordSilently(
  context?: LoginRecordPayload,
): void {
  void recordLoginRecord(context).catch(() => undefined);
}
