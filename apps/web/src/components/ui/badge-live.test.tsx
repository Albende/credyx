import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BadgeLive } from "./badge-live";

describe("BadgeLive", () => {
  it("defaults to the LIVE label", () => {
    render(<BadgeLive />);
    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });

  it("renders a custom label when one is supplied", () => {
    render(<BadgeLive label="STREAMING" />);
    expect(screen.getByText("STREAMING")).toBeInTheDocument();
  });
});
