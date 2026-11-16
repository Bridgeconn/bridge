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
  const actions = { onWordAlignment: vi.fn(), onAlignmentReview: vi.fn(), onCrossVerse: vi.fn(), onAlignChapter: vi.fn() };
  render(AlignmentMenu, { props: { ...actions, alignChapterTitle: "Align this chapter automatically", ...props } });
  return actions;
}

describe("AlignmentMenu (#488)", () => {
  // 2026-11-16 (Joel): Word alignment is in the menu, first; then the order
  // of the work itself; each entry has its icon.
  it("holds Word alignment, Cross-verse alignment, Alignment Review and Align chapter with AI, in that order", async () => {
    mount();
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(trigger());
    expect(screen.getAllByRole("menuitem").map((item) => item.querySelector(".entry")?.textContent?.trim()))
      .toEqual(["Word alignment", "Cross-verse alignment", "Alignment Review", "Align chapter with AI"]);
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
    await fireEvent.click(entry("Align chapter with AI"));
    expect(actions.onAlignChapter).toHaveBeenCalledOnce();
  });

  it("keeps the buttons' disabled states and tooltips", async () => {
    const actions = mount({ crossVerseDisabled: true, alignChapterDisabled: true,
      alignChapterTitle: "Add an API key in Settings to align automatically" });
    await fireEvent.click(trigger());
    const cross = entry(/Cross-verse alignment/);
    expect(cross).toBeDisabled();
    expect(hintOf(cross)).toBe("Align several verses of this chapter side by side (Ctrl-click or Shift-click verses to pick them first)");
    const auto = entry("Align chapter with AI");
    expect(auto).toBeDisabled();
    expect(hintOf(auto)).toBe("Add an API key in Settings to align automatically");
    await fireEvent.click(cross);
    await fireEvent.click(auto);
    expect(actions.onCrossVerse).not.toHaveBeenCalled();
    expect(actions.onAlignChapter).not.toHaveBeenCalled();
    expect(entry("Alignment Review")).toBeEnabled();
  });

  it("counts the picked verses on Cross-verse alignment, as the button did", async () => {
    mount({ selectedCount: 3 });
    await fireEvent.click(trigger());
    const cross = entry(/Cross-verse alignment/);
    expect(cross.querySelector(".entry")?.textContent?.replace(/ /g, " ")).toBe("Cross-verse alignment (3)");
    expect(hintOf(cross)).toBe("Open the 3 selected verses side by side");
  });

  it("shows the estimate being read on its entry", async () => {
    mount({ alignChapterLabel: "Working out the cost…", alignChapterDisabled: true });
    await fireEvent.click(trigger());
    expect(entry("Working out the cost…")).toBeDisabled();
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
    expect(document.activeElement).toBe(entry("Align chapter with AI"));
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
    // "Align chapter with AI" is still AutoAlignChapterButton's job, as a strip.
    expect(app).toMatch(/<AutoAlignChapterButton\s+strip/);
  });
});
