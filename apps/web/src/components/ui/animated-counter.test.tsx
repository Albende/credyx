import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnimatedCounter } from "./animated-counter";

describe("AnimatedCounter", () => {
  it("renders prefix, suffix, and a formatted value in the accessible label", () => {
    render(<AnimatedCounter value={42} prefix="$" suffix=" USD" decimals={0} />);
    const node = screen.getByLabelText(/\$42 USD/);
    expect(node).toBeInTheDocument();
  });

  it("formats with the requested number of decimals", () => {
    render(<AnimatedCounter value={3.14159} decimals={2} prefix="~" />);
    const node = screen.getByLabelText(/~3\.14/);
    expect(node).toBeInTheDocument();
  });
});
