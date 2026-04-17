import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import BottomNav from "./BottomNav.svelte";

describe("BottomNav", () => {
  it("renders all six tab buttons", () => {
    const { getAllByRole } = render(BottomNav, { props: { activeIdx: 0 } });
    expect(getAllByRole("button")).toHaveLength(6);
  });

  it("renders each tab by aria-label", () => {
    const { getByLabelText } = render(BottomNav, { props: { activeIdx: 0 } });
    expect(getByLabelText("Ingest")).toBeInTheDocument();
    expect(getByLabelText("Library")).toBeInTheDocument();
    expect(getByLabelText("Darktable")).toBeInTheDocument();
    expect(getByLabelText("Export")).toBeInTheDocument();
    expect(getByLabelText("Cartridge")).toBeInTheDocument();
    expect(getByLabelText("Settings")).toBeInTheDocument();
  });

  it("applies active class to the active tab only", () => {
    const { getByLabelText } = render(BottomNav, { props: { activeIdx: 2 } });
    expect(getByLabelText("Darktable").className).toContain("active");
    expect(getByLabelText("Ingest").className).not.toContain("active");
  });

  it("dispatches select event with tab index on click", async () => {
    const results: number[] = [];
    const { getByLabelText, component } = render(BottomNav, { props: { activeIdx: 0 } });
    component.$on("select", (e: CustomEvent<number>) => results.push(e.detail));
    await fireEvent.click(getByLabelText("Library"));
    expect(results).toEqual([1]);
  });
});
