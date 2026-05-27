import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CitationList } from "./CitationList";

describe("CitationList", () => {
  it("renders filename, doc_type chip, and topic chips", () => {
    render(
      <CitationList
        citations={[
          { file_id: 1, filename: "k8s.txt", doc_type: "guide", tags_topic: ["kubernetes", "hpa"] },
        ]}
      />,
    );
    expect(screen.getByText("k8s.txt")).toBeInTheDocument();
    expect(screen.getByText("guide")).toBeInTheDocument();
    expect(screen.getByText("#kubernetes")).toBeInTheDocument();
    expect(screen.getByText("#hpa")).toBeInTheDocument();
  });

  it("renders just the filename when no tags (back-compat)", () => {
    render(<CitationList citations={[{ file_id: 2, filename: "old.txt" }]} />);
    expect(screen.getByText("old.txt")).toBeInTheDocument();
    expect(screen.queryByText("guide")).not.toBeInTheDocument();
  });

  it("renders nothing when empty", () => {
    const { container } = render(<CitationList citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
