import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import EditorHeader from "../EditorHeader.svelte";
import { rawView } from "../../editorPrefs";
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

  // 2026-11-11, third round: no breadcrumb; book, chapter "of N", Go to, Raw USFM icon, tools.
  it("reads, left to right: book, chapter picker of N, Go to, Raw USFM, and has no breadcrumb", () => {
    const { container } = render(EditorHeader);
    const header = container.querySelector(".editor-header") as HTMLElement;
    const [where, goto, tools] = Array.from(header.children) as HTMLElement[];
    expect(where).toHaveTextContent("Philippians");
    expect(where).toContainElement(screen.getByRole("group", { name: "Chapter navigation" }));
    expect(screen.getByRole("group", { name: "Chapter navigation" })).toHaveTextContent("of 4");
    expect((screen.getByRole("combobox", { name: "Chapter" }) as HTMLSelectElement).value).toBe("2");
    expect(goto).toContainElement(goToBox());
    expect(tools.firstElementChild).toBe(screen.getByRole("button", { name: "Raw USFM" }));
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: "Projects" })).toBeNull();
  });

  it("carries the Raw USFM toggle as an icon with its name in the title; it shows its state and is saved", async () => {
    render(EditorHeader);
    const raw = screen.getByRole("button", { name: "Raw USFM" });
    expect(raw).toHaveAttribute("aria-pressed", "false");
    expect(raw.getAttribute("title")).toMatch(/^Raw USFM/);
    expect(raw.querySelector("svg")).not.toBeNull();
    expect(raw.textContent?.trim()).toBe("");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(true);
    expect(raw).toHaveAttribute("aria-pressed", "true");
    expect(raw.getAttribute("title")).toMatch(/^Raw USFM \(on\)/);
    expect(localStorage.getItem("bridge.editor.rawView.v1")).toBe("true");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(false);
  });

  it("a collection's book is the book switcher; a single book is its name as text", async () => {
    const onBookChange = vi.fn();
    openBook(["1"], [{ path: "/c/php", bookName: "Philippians" }, { path: "/c/col", bookName: "Colossians" }]);
    const view = render(EditorHeader, { props: { onBookChange } });
    const books = screen.getByRole("combobox", { name: "Book" }) as HTMLSelectElement;
    expect(books.value).toBe("/c/php");
    await fireEvent.change(books, { target: { value: "/c/col" } });
    expect(onBookChange).toHaveBeenCalledWith("/c/col");
    view.unmount();
    openBook();
    render(EditorHeader, { props: { bookSwitching: true } });
    expect(screen.queryByRole("combobox", { name: "Book" })).toBeNull();
    expect(screen.getByText("Philippians")).toBeInTheDocument();
  });

  // jsdom lays nothing out, so these pin the rules, not the rendering.
  it("is styled to stay at the top of the panel, on one row, with the book giving way first", () => {
    const source: string = readFileSync(resolve("src/lib/components/EditorHeader.svelte"), "utf8");
    const rule = (selector: string) => new RegExp(`${selector.replace(/[.]/g, "\\.")}\\s*\\{([^}]*)\\}`).exec(source)?.[1] ?? "";
    expect(rule(".editor-header")).toContain("position: sticky");
    expect(rule(".editor-header")).toContain("top: 0");
    expect(rule(".editor-header")).toContain("flex: none");
    expect(rule(".editor-header")).not.toContain("flex-wrap");
    expect(rule(".book-name")).toContain("text-overflow: ellipsis");
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

  it("App hands the header the book, chapter and Go to handlers, and its overflow menu has no Raw USFM", () => {
    const app: string = readFileSync(resolve("src/App.svelte"), "utf8");
    expect(app).not.toContain("Raw USFM");
    const use = /<EditorHeader[^>]*>/.exec(app)?.[0] ?? "";
    expect(use).toContain("onBookChange={switchBook}");
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
    await fireEvent.change(screen.getByRole("combobox", { name: "Chapter" }), { target: { value: "4" } });
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

  it("the steppers are real buttons with titles", () => {
    render(EditorHeader);
    expect(prev().tagName).toBe("BUTTON");
    expect(next().tagName).toBe("BUTTON");
    expect(prev()).toHaveAttribute("title");
    expect(next()).toHaveAttribute("title");
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
