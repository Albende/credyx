import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./sparkline";

describe("Sparkline", () => {
  it("renders an SVG with a polyline of N points for N data values", () => {
    const { container } = render(<Sparkline data={[1, 2, 3, 4]} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    const polyline = container.querySelector("polyline");
    expect(polyline).not.toBeNull();
    const points = polyline!.getAttribute("points")!.trim().split(/\s+/);
    expect(points).toHaveLength(4);
  });

  it("renders an empty svg when data is empty", () => {
    const { container } = render(<Sparkline data={[]} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(container.querySelector("polyline")).toBeNull();
  });
});
