"use client";

export type FrontendDataMode = "backend" | "mock";

export function getFrontendDataMode(): FrontendDataMode {
  const value =
    process.env.NEXT_PUBLIC_DATA_MODE ??
    process.env.NEXT_PUBLIC_USE_MOCK_DATA ??
    "backend";
  return ["1", "true", "mock", "yes", "on"].includes(value.toLowerCase())
    ? "mock"
    : "backend";
}

export function isMockDataMode(): boolean {
  return getFrontendDataMode() === "mock";
}
