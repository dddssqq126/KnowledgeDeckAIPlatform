import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SlidesIndexPage from "./page";
import { recordLoginRecordSilently } from "../../../lib/login-records";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("../../../lib/slide-store", () => ({
  useSlideStore: (selector: any) =>
    selector({
      newSession: vi.fn(),
    }),
}));

vi.mock("../../../lib/login-records", () => ({
  recordLoginRecordSilently: vi.fn(),
}));

describe("SlidesIndexPage", () => {
  it("records a login record when the user enters the slides page", async () => {
    render(<SlidesIndexPage />);

    expect(screen.getByText("Slide Maker")).toBeInTheDocument();
    await waitFor(() => {
      expect(recordLoginRecordSilently).toHaveBeenCalledTimes(1);
    });
  });
});
