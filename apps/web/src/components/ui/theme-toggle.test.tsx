import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeToggle } from "./theme-toggle";

describe("ThemeToggle", () => {
  it("renders a trigger button with an accessible Theme label", () => {
    render(<ThemeToggle />);
    const trigger = screen.getByRole("button", { name: /theme/i });
    expect(trigger).toBeInTheDocument();
  });
});
