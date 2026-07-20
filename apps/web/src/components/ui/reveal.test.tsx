import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Reveal } from "./reveal";

describe("Reveal", () => {
  it("renders its children", () => {
    render(
      <Reveal>
        <p>hello world</p>
      </Reveal>,
    );
    expect(screen.getByText("hello world")).toBeInTheDocument();
  });

  it("respects the as prop and renders the correct tag", () => {
    render(
      <Reveal as="section" className="x-section">
        <p>inside</p>
      </Reveal>,
    );
    expect(screen.getByText("inside")).toBeInTheDocument();
    const section = document.querySelector("section.x-section");
    expect(section).not.toBeNull();
  });
});
