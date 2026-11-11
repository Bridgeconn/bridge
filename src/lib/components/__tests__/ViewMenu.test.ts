import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

import ViewMenu from "../ViewMenu.svelte";
import { SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, setSidePanel, sidePanels } from "../../editorPrefs";
import { languageQaShown, setLanguageQaShown, toggleLanguageQaShown } from "../../viewMenu";

function reset(): void {
  for (const id of SIDE_PANEL_ORDER) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial, float: null });
  }
}

const trigger = () => screen.getByRole("button", { name: /^View/ });
const entry = (name: string) => screen.getByRole("menuitemcheckbox", { name });

describe("ViewMenu (#488)", () => {
  beforeEach(reset);

  it("lists the five panels, ticked where the panel is on", async () => {
    render(ViewMenu);
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(trigger());
    const names = screen.getAllByRole("menuitemcheckbox").map((item) => item.textContent?.replace("✓", "").trim());
    expect(names).toEqual(["Source", "Reference", "Paratext", "Language QA", "Review"]);
    expect(entry("Review")).toHaveAttribute("aria-checked", "true");
    expect(entry("Review")).toHaveTextContent("✓");
    expect(entry("Source")).toHaveAttribute("aria-checked", "false");
    expect(entry("Source")).not.toHaveTextContent("✓");
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

  it("the Language QA entry follows languageQaShown and calls its toggle", async () => {
    render(ViewMenu);
    await fireEvent.click(trigger());
    expect(get(languageQaShown)).toBe(false);
    await fireEvent.click(entry("Language QA"));
    expect(get(languageQaShown)).toBe(true);
    expect(entry("Language QA")).toHaveAttribute("aria-checked", "true");
    toggleLanguageQaShown();
    await Promise.resolve();
    expect(entry("Language QA")).toHaveAttribute("aria-checked", "false");
    setLanguageQaShown(true);
    expect(get(sidePanels).languageQa.open).toBe(true);
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
});
