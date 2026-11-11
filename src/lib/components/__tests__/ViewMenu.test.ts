import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

import ViewMenu from "../ViewMenu.svelte";
import { SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, setSidePanel, sidePanelRecency, sidePanels } from "../../editorPrefs";

function reset(): void {
  for (const id of SIDE_PANEL_ORDER) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial, float: null });
  }
  sidePanelRecency.set([]);
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 1366 });
  window.dispatchEvent(new Event("resize"));
}

const trigger = () => screen.getByRole("button", { name: /^View/ });
const entry = (name: string) => screen.getByRole("menuitemcheckbox", { name });

describe("ViewMenu (#488)", () => {
  beforeEach(reset);

  // #487: Language QA is a tab of the Review panel, with no toggle of its own.
  it("lists the four panels, ticked where the panel is on, and has no Language QA entry", async () => {
    render(ViewMenu);
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(trigger());
    const names = screen.getAllByRole("menuitemcheckbox").map((item) => item.textContent?.replace("✓", "").trim());
    expect(names).toEqual(["Source", "Reference", "Paratext", "Review"]);
    expect(screen.queryByRole("menuitemcheckbox", { name: /Language QA/ })).toBeNull();
    expect(entry("Review")).toHaveAttribute("aria-checked", "true");
    expect(entry("Review")).toHaveTextContent("✓");
    expect(entry("Source")).toHaveAttribute("aria-checked", "false");
    expect(entry("Source")).not.toHaveTextContent("✓");
    // Nothing is folded at 1366 with one panel open.
    expect(trigger().title).not.toMatch(/too narrow/);
  });

  it("toggles a panel and stays open, so several can be changed in one visit", async () => {
    render(ViewMenu);
    await fireEvent.click(trigger());
    await fireEvent.click(entry("Reference"));
    expect(get(sidePanels).reference.open).toBe(true);
    expect(entry("Reference")).toHaveAttribute("aria-checked", "true");
    await fireEvent.click(entry("Review"));
    expect(get(sidePanels).review.open).toBe(false);
    expect(entry("Review")).toHaveAttribute("aria-checked", "false");
  });

  it("is keyboard operable: arrows move, Escape closes and returns focus", async () => {
    render(ViewMenu);
    trigger().focus();
    await fireEvent.keyDown(trigger(), { key: "ArrowDown" });
    await Promise.resolve();
    expect(document.activeElement).toBe(entry("Source"));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(entry("Reference"));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "End" });
    expect(document.activeElement).toBe(entry("Review"));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(entry("Source"));
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  it("closes on a press outside", async () => {
    render(ViewMenu);
    await fireEvent.click(trigger());
    await fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });
  // A panel folded for width: see panelFit.test.ts ("the View menu marks a
  // folded panel ...").
});
