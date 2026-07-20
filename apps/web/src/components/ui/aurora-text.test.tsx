import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AuroraText } from "./aurora-text";

describe("AuroraText", () => {
  it("renders children inside a span with the gradient text class", () => {
    render(<AuroraText>headline</AuroraText>);
    const node = screen.getByText("headline");
    expect(node.tagName).toBe("SPAN");
    expect(node.className).toMatch(/bg-clip-text/);
    expect(node.className).toMatch(/text-transparent/);
  });
});
