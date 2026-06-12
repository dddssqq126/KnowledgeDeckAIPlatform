import { fireEvent, render, screen } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppSidebar } from "./AppSidebar";
import { api } from "../lib/api";
import { useChatSessionsStore } from "../lib/chat-store";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

describe("AppSidebar chat search", () => {
  let mock: MockAdapter;

  beforeEach(() => {
    mock = new MockAdapter(api);
    mock.onGet("/chat/search").reply(200, []);
    useChatSessionsStore.setState({
      sessions: [],
      loaded: true,
    });
  });

  afterEach(() => {
    mock.restore();
  });

  it("keeps focus in Search Chats when the first character has no matches", async () => {
    render(<AppSidebar />);

    const input = screen.getByPlaceholderText("Search chats");
    input.focus();
    fireEvent.change(input, { target: { value: "z" } });

    expect(document.activeElement).toBe(input);

    expect(await screen.findByText("No matches")).toBeInTheDocument();
    expect(document.activeElement).toBe(input);
  });
});
