import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Marquee } from "./marquee";

describe("Marquee", () => {
  it("renders its children twice so the loop appears seamless", () => {
    render(
      <Marquee>
        <span data-testid="logo">acme</span>
      </Marquee>,
    );
    expect(screen.getAllByTestId("logo")).toHaveLength(2);
  });
});
