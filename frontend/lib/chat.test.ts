import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat } from "./chat";

describe("chat API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("surfaces JSON error details for failed stream requests", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "session_not_found" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const onError = vi.fn();

    await streamChat(
      { session_id: 404, message: "hi", use_rag: false, kb_ids: null },
      {
        onToken: vi.fn(),
        onCitations: vi.fn(),
        onDone: vi.fn(),
        onError,
      },
    );

    expect(onError).toHaveBeenCalledWith("HTTP 404: session_not_found");
  });
});
