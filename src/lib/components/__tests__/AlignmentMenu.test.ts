import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import AlignmentMenu from "../AlignmentMenu.svelte";

const trigger = () => screen.getByRole("button", { name: /^Alignment/ });
const entry = (name: RegExp | string) => screen.getByRole("menuitem", { name });

function mount(props: Record<string, unknown> = {}) {
  const actions = { onAlignmentReview: vi.fn(), onCrossVerse: vi.fn(), onAlignChapter: vi.fn() };
  render(AlignmentMenu, { props: { ...actions, alignChapterTitle: "Align this chapter automatically", ...props } });
  return actions;
}

describe("AlignmentMenu (#488)", () => {
  it("holds the three actions of the old second bar, in their order", async () => {
    mount();
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(trigger());
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent?.trim()))
      .toEqual(["Alignment Review", "Cross-verse alignment", "Align chapter with AI"]);
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
    expect(cross.title).toBe("Align several verses of this chapter side by side (Ctrl-click or Shift-click verses to pick them first)");
    const auto = entry("Align chapter with AI");
    expect(auto).toBeDisabled();
    expect(auto.title).toBe("Add an API key in Settings to align automatically");
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
    expect(cross.textContent?.replace(/ /g, " ")).toBe("Cross-verse alignment (3)");
    expect(cross.title).toBe("Open the 3 selected verses side by side");
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
