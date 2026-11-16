import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import EditorHeader from "../EditorHeader.svelte";
import { rawView, textScale } from "../../editorPrefs";
import { currentChapter, project } from "../../stores";
import type { ProjectInfo } from "../../types/finding";

function openBook(chapters: string[] = ["1", "2", "3", "4"], books: Array<{ path: string; bookName: string }> = []): void {
  project.set({
    path: "/c/php", bookId: "php", bookName: "Philippians", targetLanguage: "Tamil", tcVersion: "3",
    chapters, checkTypes: {}, importedProjects: books,
  } as unknown as ProjectInfo);
}

const prev = () => screen.getByLabelText("Previous chapter") as HTMLButtonElement;
const next = () => screen.getByLabelText("Next chapter") as HTMLButtonElement;
const goToBox = () => screen.getByRole("textbox", { name: "Go to" }) as HTMLInputElement;
const submitGoTo = () => fireEvent.submit(goToBox().closest("form") as HTMLFormElement);

describe("EditorHeader (#489)", () => {
  beforeEach(() => { rawView.set(false); openBook(); currentChapter.set("2"); });

  // 2026-11-15: "Chapter", the picker, "of N", the arrows; Go to; text size and the USFM toggle.
  it("reads, left to right: Chapter, the picker, of N and the arrows, Go to, then text size and Raw USFM; no book or breadcrumb", () => {
    const { container } = render(EditorHeader);
    const header = container.querySelector(".editor-header") as HTMLElement;
    const nav = screen.getByRole("group", { name: "Chapter navigation" });
    const tools = container.querySelector(".tools") as HTMLElement;
    expect(header.firstElementChild).toBe(nav);
    expect(nav).not.toHaveTextContent("Philippians");
    expect(nav).toHaveTextContent(/^Chapter\s*2\s*of 4/);
    expect(nav).toContainElement(prev());
    expect(nav).toContainElement(next());
    expect(nav.compareDocumentPosition(goToBox()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(goToBox().compareDocumentPosition(tools) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(Array.from(tools.querySelectorAll("button")).map((item) => item.getAttribute("aria-label")))
      .toEqual(["Smaller text", "Larger text", "Raw USFM", "What the marks mean"]);
    expect(screen.queryByRole("combobox", { name: "Book" })).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: "Projects" })).toBeNull();
  });

  it("the picker opens a grid of the book's chapters; a click or the keyboard chooses one", async () => {
    const onChapterChange = vi.fn();
    render(EditorHeader, { props: { onChapterChange } });
    const trigger = screen.getByRole("button", { name: /^Chapter 2/ });
    expect(screen.queryByRole("listbox")).toBeNull();
    await fireEvent.click(trigger);
    expect(screen.getAllByRole("option").map((item) => item.textContent)).toEqual(["1", "2", "3", "4"]);
    expect(screen.getByRole("option", { name: "2" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("option", { name: "2" })));
    await fireEvent.click(screen.getByRole("option", { name: "4" }));
    expect(onChapterChange).toHaveBeenLastCalledWith("4");
    expect(screen.queryByRole("listbox")).toBeNull();
    // Arrow keys move the focus; the open chapter chosen again changes nothing.
    await fireEvent.click(trigger);
    await fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowRight" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("option", { name: "3" })));
    await fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowLeft" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("option", { name: "2" })));
    await fireEvent.click(screen.getByRole("option", { name: "2" }));
    expect(onChapterChange).toHaveBeenCalledOnce();
    await fireEvent.click(trigger);
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("carries the Raw USFM toggle as an icon with an instant hint; it shows its state and is saved", async () => {
    render(EditorHeader);
    const raw = screen.getByRole("button", { name: "Raw USFM" });
    expect(raw).toHaveAttribute("aria-pressed", "false");
    expect(raw).not.toHaveAttribute("title");
    expect(raw.querySelector("svg")).not.toBeNull();
    expect(raw.textContent?.trim()).toBe("");
    await fireEvent.mouseEnter(raw);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Show USFM markers/);
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(true);
    expect(raw).toHaveAttribute("aria-pressed", "true");
    await fireEvent.mouseEnter(raw);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^USFM markers are showing/);
    await fireEvent.mouseLeave(raw);
    // As on the left rail: the accent colour means on, and the hover is grey.
    const css = readFileSync(resolve("src/lib/components/EditorHeader.svelte"), "utf8");
    expect(css).toMatch(/\.raw-toggle:hover:not\(:disabled\) \{ background: var\(--bg\); color: var\(--text\); \}/);
    expect(css).toMatch(/\.raw-toggle\[aria-pressed="true"\]:hover:not\(:disabled\) \{ color: var\(--accent\); \}/);
    expect(localStorage.getItem("bridge.editor.rawView.v1")).toBe("true");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(false);
  });

  it("the legend opens a list of what the marks mean, drawn with the real mark styles, and closes on Escape", async () => {
    render(EditorHeader);
    const legend = screen.getByRole("button", { name: "What the marks mean" });
    expect(screen.queryByRole("dialog")).toBeNull();
    await fireEvent.click(legend);
    const panel = screen.getByRole("dialog", { name: "What the marks mean" });
    expect(panel).toHaveTextContent("The small raised number is the verse's open issues");
    expect(panel).toHaveTextContent("Unicode: an invisible or unusual character");
    expect(panel.querySelector("mark.m-lqa-unicode")).not.toBeNull();
    expect(panel.querySelector("mark.m-gr")).not.toBeNull();
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("A− and A+ step the verse text size, stop at either end, and say the size in their hint", async () => {
    textScale.set(1);
    render(EditorHeader);
    const smaller = screen.getByRole("button", { name: "Smaller text" });
    const larger = screen.getByRole("button", { name: "Larger text" });
    await fireEvent.click(larger);
    expect(get(textScale)).toBe(1.15);
    await fireEvent.mouseEnter(larger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Larger text (now 115%)");
    await fireEvent.mouseLeave(larger);
    await fireEvent.click(smaller);
    await fireEvent.click(smaller);
    expect(get(textScale)).toBe(0.85);
    expect(smaller).toBeDisabled();
    expect(larger).not.toBeDisabled();
    textScale.set(1);
  });

  // jsdom lays nothing out, so these pin the rules, not the rendering.
  it("is styled to stay at the top of the panel, on one row", () => {
    const source: string = readFileSync(resolve("src/lib/components/EditorHeader.svelte"), "utf8");
    const rule = (selector: string) => new RegExp(`${selector.replace(/[.]/g, "\\.")}\\s*\\{([^}]*)\\}`).exec(source)?.[1] ?? "";
    expect(rule(".editor-header")).toContain("position: sticky");
    expect(rule(".editor-header")).toContain("top: 0");
    expect(rule(".editor-header")).toContain("flex: none");
    expect(rule(".editor-header")).not.toContain("flex-wrap");
    expect(rule(".chapter-nav")).toContain("flex: none");
    expect(rule(".tools")).toContain("flex: none");
    // The error sits over the verses; it does not change the header's height.
    expect(rule(".goto-error")).toContain("position: absolute");
    // It spans the header and wraps, so the column never cuts it: placed
    // against the Go to box it ran past the column's right edge.
    expect(rule(".goto-error")).toContain("left: 8px; right: 8px");
    expect(rule(".goto-error")).not.toContain("max-content");
    expect(rule(".goto")).not.toContain("position: relative");
  });

  it("App hands the header the chapter and Go to handlers and no overflow menu, and the top bar the book switch", () => {
    const app: string = readFileSync(resolve("src/App.svelte"), "utf8");
    expect(app).not.toContain("Raw USFM");
    // Text size is the header's own; Reset layout is on the tab strip.
    expect(app).not.toContain("Reset workspace layout");
    expect(app).not.toContain('label="Editor tools"');
    const use = /<EditorHeader[^>]*>/.exec(app)?.[0] ?? "";
    expect(use).not.toContain("onBookChange");
    const bar = app.slice(app.indexOf("<TopBar"), app.indexOf("/>", app.indexOf("<TopBar")));
    expect(bar).toContain("onBookChange={switchBook}");
    expect(use).toContain("onChapterChange={switchChapter}");
    expect(use).toContain("onGoTo={goTo}");
  });
});

describe("EditorHeader chapter navigation (issue #53)", () => {
  beforeEach(() => { openBook(); currentChapter.set("2"); });

  it("steps to the previous and next chapter through the same handler as the dropdown", async () => {
    const onChapterChange = vi.fn();
    render(EditorHeader, { props: { onChapterChange } });
    await fireEvent.click(next());
    expect(onChapterChange).toHaveBeenCalledWith("3");
    await fireEvent.click(prev());
    expect(onChapterChange).toHaveBeenCalledWith("1");
    await fireEvent.click(screen.getByRole("button", { name: /^Chapter 2/ }));
    await fireEvent.click(screen.getByRole("option", { name: "4" }));
    expect(onChapterChange).toHaveBeenLastCalledWith("4");
    expect(onChapterChange).toHaveBeenCalledTimes(3);
  });

  it("disables Previous on the first chapter and Next on the last", async () => {
    const onChapterChange = vi.fn();
    currentChapter.set("1");
    const view = render(EditorHeader, { props: { onChapterChange } });
    expect(prev()).toBeDisabled();
    expect(next()).not.toBeDisabled();
    view.unmount();
    currentChapter.set("4");
    render(EditorHeader, { props: { onChapterChange } });
    expect(next()).toBeDisabled();
    expect(prev()).not.toBeDisabled();
    await fireEvent.click(next());
    expect(onChapterChange).not.toHaveBeenCalled();
  });

  it("disables both ends for a single-chapter book", () => {
    openBook(["1"]);
    currentChapter.set("1");
    render(EditorHeader);
    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  it("steps by position in the book's chapter list, not by number", async () => {
    // Chapter ids are strings from the engine and are not guaranteed to be a
    // clean 1..n run; stepping must agree with the dropdown the reader sees.
    openBook(["1", "2", "2b", "3"]);
    const onChapterChange = vi.fn();
    render(EditorHeader, { props: { onChapterChange } });
    await fireEvent.click(next());
    expect(onChapterChange).toHaveBeenCalledWith("2b");
  });

  it("disables both controls when the current chapter is not in the book", () => {
    // Mid-book-switch: the chapter list has already changed under a chapter
    // number that no longer exists. Stepping from nowhere would be a guess.
    currentChapter.set("99");
    render(EditorHeader);
    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  it("the steppers are real buttons with instant hints", async () => {
    currentChapter.set("1");
    render(EditorHeader);
    expect(prev().tagName).toBe("BUTTON");
    expect(next().tagName).toBe("BUTTON");
    await fireEvent.mouseEnter(next());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Next chapter");
    await fireEvent.mouseLeave(next());
    await fireEvent.mouseEnter(prev());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Already at the first chapter");
    await fireEvent.mouseLeave(prev());
  });
});

describe("EditorHeader Go to", () => {
  beforeEach(() => { openBook(); currentChapter.set("2"); });

  it("hands what was typed to the caller on Enter and clears the box when the editor moved", async () => {
    const onGoTo = vi.fn().mockResolvedValue("");
    render(EditorHeader, { props: { onGoTo } });
    await fireEvent.input(goToBox(), { target: { value: "3:4" } });
    await submitGoTo();
    expect(onGoTo).toHaveBeenCalledWith("3:4");
    await waitFor(() => expect(goToBox().value).toBe(""));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the caller's sentence for an entry that cannot be gone to, keeps what was typed, and clears on the next keystroke", async () => {
    const onGoTo = vi.fn().mockResolvedValue("Chapter 40 is not in this book.");
    render(EditorHeader, { props: { onGoTo } });
    await fireEvent.input(goToBox(), { target: { value: "40:1" } });
    await submitGoTo();
    expect(await screen.findByRole("alert")).toHaveTextContent("Chapter 40 is not in this book.");
    expect(goToBox().value).toBe("40:1");
    expect(goToBox()).toHaveAttribute("aria-invalid", "true");
    expect(goToBox()).toHaveAccessibleDescription("Chapter 40 is not in this book.");
    await fireEvent.input(goToBox(), { target: { value: "4:1" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(goToBox()).not.toHaveAttribute("aria-invalid");
  });

  it("does nothing for an empty box", async () => {
    const onGoTo = vi.fn();
    render(EditorHeader, { props: { onGoTo } });
    await submitGoTo();
    expect(onGoTo).not.toHaveBeenCalled();
  });
});
