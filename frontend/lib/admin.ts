"use client";

import { api } from "./api";

export type AdminUserRow = {
  id: number;
  username: string;
  password: string;
  created_at: string;
  chat_session_count: number;
  chat_message_count: number;
};

export type AdminChatMessageRow = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type AdminChatSessionRow = {
  id: number;
  owner_user_id: number;
  owner_username: string;
  title: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  message_count: number;
  messages: AdminChatMessageRow[];
};

export type AdminDatabaseOverview = {
  users: AdminUserRow[];
  chat_sessions: AdminChatSessionRow[];
  totals: {
    users: number;
    chat_sessions: number;
    chat_messages: number;
  };
};

export async function getAdminDatabaseOverview(): Promise<AdminDatabaseOverview> {
  const response = await api.get<AdminDatabaseOverview>("/admin/database-overview");
  return response.data;
}
