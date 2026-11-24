import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import AlignmentMenu from "../AlignmentMenu.svelte";

const trigger = () => screen.getByRole("button", { name: /^Alignment/ });
const entry = (name: RegExp | string) => screen.getByRole("menuitem", { name });

// The entries' hints are the app's instant tooltip (2026-11-16), read by pointing at them.
function hintOf(element: Element): string {
  fireEvent.mouseEnter(element);
  // The newest hint: the menu's first entry is focused when it opens, and shows its own.
  const text = Array.from(document.querySelectorAll('[role="tooltip"]')).pop()?.textContent ?? "";
  fireEvent.mouseLeave(element);
  return text;
}

function mount(props: Record<string, unknown> = {}) {
  const actions = { onWordAlignment: vi.fn(), onAlignmentReview: vi.fn(), onCrossVerse: vi.fn(), onAlignWithAI: vi.fn() };
  render(AlignmentMenu, { props: { ...actions, alignAITitle: "Align one chapter, several, or the whole book automatically", ...props } });
  return actions;
}

describe("AlignmentMenu (#488)", () => {
  // 2026-11-16 (Joel): Word alignment is in the menu, first; then the order
  // of the work itself; each entry has its icon.
  it("holds Word alignment, Cross-verse alignment, Alignment Review and Align with AI, in that order", async () => {
    mount();
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(trigger());
    expect(screen.getAllByRole("menuitem").map((item) => item.querySelector(".entry")?.textContent?.trim()))
      .toEqual(["Word alignment", "Cross-verse alignment", "Alignment Review", "Align with AI"]);
    for (const item of screen.getAllByRole("menuitem")) expect(item.querySelector("svg")).not.toBeNull();
  });

  it("opens Word alignment, and says when a tab is already open", async () => {
    const actions = mount();
    await fireEvent.click(trigger());
    expect(hintOf(entry(/Word alignment/))).toBe("Align the words of the selected verse to the source");
    expect(screen.queryByText("open")).toBeNull();
    await fireEvent.click(entry(/Word alignment/));
    expect(actions.onWordAlignment).toHaveBeenCalledOnce();
  });

  it("marks the two tabs that are open, and needs a verse for Word alignment", async () => {
    const actions = mount({ wordOpen: true, crossOpen: true });
    await fireEvent.click(trigger());
    expect(entry(/Word alignment/)).toHaveTextContent("open");
    expect(hintOf(entry(/Word alignment/))).toBe("Word alignment is already open. Click to show it");
    expect(hintOf(entry(/Cross-verse alignment/))).toBe("Cross-verse alignment is already open. Click to show it");
    await fireEvent.click(entry(/Word alignment/));
    expect(actions.onWordAlignment).toHaveBeenCalledOnce();
  });

  it("turns Word alignment off with no verse selected", async () => {
    const actions = mount({ wordDisabled: true });
    await fireEvent.click(trigger());
    expect(entry(/Word alignment/)).toBeDisabled();
    expect(hintOf(entry(/Word alignment/))).toBe("Select a verse first");
    await fireEvent.click(entry(/Word alignment/));
    expect(actions.onWordAlignment).not.toHaveBeenCalled();
  });

  it("each entry does what its button did and closes the menu", async () => {
    const actions = mount();
    await fireEvent.click(trigger());
    await fireEvent.click(entry("Alignment Review"));
    expect(actions.onAlignmentReview).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(trigger());
    await fireEvent.click(entry(/Cross-verse alignment/));
    expect(actions.onCrossVerse).toHaveBeenCalledOnce();
    await fireEvent.click(trigger());
    await fireEvent.click(entry("Align with AI"));
    expect(actions.onAlignWithAI).toHaveBeenCalledOnce();
  });

  it("keeps the buttons' disabled states and tooltips", async () => {
    const actions = mount({ crossVerseDisabled: true, alignAIDisabled: true,
      alignAITitle: "Add an API key or sign in with ChatGPT in Settings to align automatically" });
    await fireEvent.click(trigger());
    const cross = entry(/Cross-verse alignment/);
    expect(cross).toBeDisabled();
    expect(hintOf(cross)).toBe("Align several verses of this chapter side by side (Ctrl-click or Shift-click verses to pick them first)");
    const auto = entry("Align with AI");
    expect(auto).toBeDisabled();
    expect(hintOf(auto)).toBe("Add an API key or sign in with ChatGPT in Settings to align automatically");
    await fireEvent.click(cross);
    await fireEvent.click(auto);
    expect(actions.onCrossVerse).not.toHaveBeenCalled();
    expect(actions.onAlignWithAI).not.toHaveBeenCalled();
    expect(entry("Alignment Review")).toBeEnabled();
  });

  it("counts the picked verses on Cross-verse alignment, as the button did", async () => {
    mount({ selectedCount: 3 });
    await fireEvent.click(trigger());
    const cross = entry(/Cross-verse alignment/);
    expect(cross.querySelector(".entry")?.textContent?.replace(/ /g, " ")).toBe("Cross-verse alignment (3)");
    expect(hintOf(cross)).toBe("Open the 3 selected verses side by side");
  });

  // 2026-11-24: the entry opens a dialog, so it no longer changes its label
  // while a cost is worked out. A run under way is said on the entry, which
  // stays enabled: choosing it shows the run's progress.
  it("says a run is under way on its entry, and still opens", async () => {
    const actions = mount({ alignAIRunning: true, alignAITitle: "An automatic alignment is running. Click to see its progress" });
    await fireEvent.click(trigger());
    const auto = entry(/Align with AI/);
    expect(auto).toBeEnabled();
    expect(auto).toHaveTextContent("running");
    expect(auto.querySelector(".entry")?.textContent).toBe("Align with AI");
    expect(hintOf(auto)).toBe("An automatic alignment is running. Click to see its progress");
    await fireEvent.click(auto);
    expect(actions.onAlignWithAI).toHaveBeenCalledOnce();
  });

  it("shows no running mark when nothing runs", async () => {
    mount();
    await fireEvent.click(trigger());
    expect(entry("Align with AI")).not.toHaveTextContent("running");
  });

  it("is keyboard operable: arrows skip a disabled entry, Escape closes and returns focus", async () => {
    mount({ crossVerseDisabled: true });
    trigger().focus();
    await fireEvent.keyDown(trigger(), { key: "ArrowDown" });
    await Promise.resolve();
    expect(document.activeElement).toBe(entry(/Word alignment/));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(entry("Alignment Review"));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(entry("Align with AI"));
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  // The wiring is App's, which no test mounts: pinned as written.
  it("is on the editor's left rail after Check and Bookmarks, and the second bar is gone", () => {
    const app: string = readFileSync(resolve("src/App.svelte"), "utf8");
    const menus = app.slice(app.indexOf("<ActivityBar>"), app.indexOf("</ActivityBar>"));
    const at = (text: string) => menus.indexOf(text);
    expect(at("<CheckMenu rail")).toBeGreaterThan(-1);
    expect(at("<CheckMenu rail")).toBeLessThan(at('aria-label="Bookmarks"'));
    expect(at('aria-label="Bookmarks"')).toBeLessThan(at("<AlignmentMenu rail"));
    expect(app).not.toContain('slot="menus"');
    expect(app).not.toContain("editor-toolbar");
    expect(app).not.toContain("whole-book-btn");
    // "Align with AI" opens the dialog; its run shows as a strip above the text.
    expect(app).toMatch(/<AutoAlignStrip\s/);
    expect(app).toMatch(/<AutoAlignDialog\s/);
    expect(app).toContain("onAlignWithAI={() => (autoAlignDialogOpen = true)}");
    expect(app).not.toContain("AutoAlignChapterButton");
  });
});
