/**
 * #507: the book's introduction above its first chapter -- \is, \ip, \iot,
 * \io1 and their kin -- and editing one of its lines. The displays are the
 * engine's own output for these strings (verseDisplayFixtures.ts). jsdom does
 * not lay out, so indents are not checked here.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { bookIntroduction, editIntroduction } = vi.hoisted(() => ({
  bookIntroduction: vi.fn(), editIntroduction: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({ bridge: { bookIntroduction, editIntroduction } }));

import BookIntroduction from "../BookIntroduction.svelte";
import { checkingProgress, currentChapter, project } from "../../stores";
import { introOpen } from "../../editorPrefs";
import type { IntroEntry } from "../../types/finding";
import { displayFor } from "./verseDisplayFixtures";

const PARAGRAPH = "The book of \\bk Psalms\\bk* is a hymn book.";
const OUTLINE_1 = "Book one \\ior 1-41\\ior*";
const WITH_NOTE = "A line\\f + \\ft with a note\\f* in it.";

const entry = (index: number, tag: string, text: string): IntroEntry => ({ index, tag, text, display: displayFor(text) });

// headers.json also holds \id, \h, \toc1 and \mt, so an introduction's
// indexes do not start at 0.
const ENTRIES: IntroEntry[] = [
  entry(4, "is", "Introduction"),
  entry(5, "ip", PARAGRAPH),
  entry(6, "iot", "Outline"),
  entry(7, "io1", OUTLINE_1),
  entry(8, "ip", WITH_NOTE),
];

const idle = { running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter" } as const;

function openBook(path = "C:/p/psa", bookId = "psa", chapters = ["1", "2"]): void {
  project.set({ path, bookId, bookName: "Psalms", targetLanguage: "English", tcVersion: "", chapters, checkTypes: {} } as never);
}

beforeEach(() => {
  bookIntroduction.mockReset();
  editIntroduction.mockReset();
  bookIntroduction.mockResolvedValue({ bookId: "psa", entries: ENTRIES });
  checkingProgress.set({ ...idle });
  introOpen.set(true);
  currentChapter.set("1");
  openBook();
});
afterEach(() => { cleanup(); project.set(null); });

const lines = () => Array.from(document.querySelectorAll<HTMLElement>(".intro-line"));

describe("BookIntroduction reading", () => {
  it("shows the book's introduction, each line classed by its marker", async () => {
    render(BookIntroduction);
    await screen.findByRole("region", { name: "Book introduction" });
    expect(lines().map((line) => [line.dataset.introTag, line.querySelector(".intro-text")?.textContent])).toEqual([
      ["is", "Introduction"],
      ["ip", "The book of Psalms is a hymn book."],
      ["iot", "Outline"],
      ["io1", "Book one 1-41"],
      // The "f" is the footnote's callout, where the note was lifted from.
      ["ip", "A linef in it."],
    ]);
    expect(lines().map((line) => line.classList.contains(`il-${line.dataset.introTag}`))).toEqual([true, true, true, true, true]);
    // No marker is shown, and the styles the engine reports are drawn.
    expect(document.querySelector(".intro-body")?.textContent).not.toContain("\\");
    expect(lines()[1].querySelector(".st-bk")?.textContent).toBe("Psalms");
    expect(lines()[3].querySelector(".st-ior")?.textContent).toBe("1-41");
  });

  it("puts a footnote behind a callout where it was, with its text as the hint", async () => {
    render(BookIntroduction);
    await screen.findByRole("region", { name: "Book introduction" });
    const callout = screen.getByLabelText("Footnote: with a note");
    expect(callout.textContent).toBe("f");
    expect(lines()[4].querySelector(".intro-text")?.textContent).toBe("A linef in it.");
  });

  it("is shown above the book's first chapter only", async () => {
    currentChapter.set("2");
    render(BookIntroduction);
    await waitFor(() => expect(bookIntroduction).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("region", { name: "Book introduction" })).toBeNull();
    currentChapter.set("1");
    expect(await screen.findByRole("region", { name: "Book introduction" })).toBeInTheDocument();
  });

  it("shows nothing for a book with no introduction, or when it cannot be read", async () => {
    bookIntroduction.mockResolvedValue({ bookId: "psa", entries: [] });
    render(BookIntroduction);
    await waitFor(() => expect(bookIntroduction).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Book introduction" })).toBeNull();
    cleanup();

    bookIntroduction.mockRejectedValue(new Error("engine busy"));
    openBook("C:/p/other", "php");
    render(BookIntroduction);
    await waitFor(() => expect(bookIntroduction).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("region", { name: "Book introduction" })).toBeNull();
  });

  it("folds away and back, and says how many lines it holds", async () => {
    render(BookIntroduction);
    const toggle = await screen.findByRole("button", { name: /Introduction\s+5 lines/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(lines()).toHaveLength(0);
    await fireEvent.click(toggle);
    expect(lines()).toHaveLength(5);
  });

  it("reads the introduction again when another book is opened", async () => {
    render(BookIntroduction);
    await screen.findByRole("region", { name: "Book introduction" });
    bookIntroduction.mockResolvedValue({ bookId: "php", entries: [entry(3, "ip", "Paul wrote this letter.")] });
    openBook("C:/p/php", "php", ["1"]);
    await waitFor(() => expect(lines().map((line) => line.querySelector(".intro-text")?.textContent)).toEqual(["Paul wrote this letter."]));
    expect(bookIntroduction).toHaveBeenCalledTimes(2);
  });
});

describe("BookIntroduction editing", () => {
  async function openEditor(label: RegExp): Promise<HTMLTextAreaElement> {
    render(BookIntroduction);
    await fireEvent.click(await screen.findByRole("button", { name: label }));
    return screen.getByRole("textbox") as HTMLTextAreaElement;
  }

  it("edits a line as its stored string and shows what the engine stored", async () => {
    const area = await openEditor(/^Edit the introduction paragraph: The book of Psalms/);
    // The stored string, markers and all, as the verse editor shows a verse.
    expect(area.value).toBe(PARAGRAPH);
    const changed = "The book of \\bk Psalms\\bk* is Israel's hymn book.";
    editIntroduction.mockResolvedValue({
      entry: { index: 5, tag: "ip", text: changed, display: { ...displayFor(PARAGRAPH), plain: "The book of Psalms is Israel's hymn book." } },
      warnings: [],
    });
    await fireEvent.input(area, { target: { value: changed } });
    await fireEvent.click(screen.getByLabelText("Save the introduction paragraph"));

    await waitFor(() => expect(lines()[1].querySelector(".intro-text")?.textContent).toBe("The book of Psalms is Israel's hymn book."));
    // The line's place in the book's headers, the new text, and the text the edit started from.
    expect(editIntroduction).toHaveBeenCalledWith(5, changed, PARAGRAPH);
    expect(screen.queryByRole("textbox")).toBeNull();
    // The other lines are untouched.
    expect(lines()[3].querySelector(".intro-text")?.textContent).toBe("Book one 1-41");
  });

  it("saves on Ctrl+Enter and names each kind of line", async () => {
    const area = await openEditor(/^Edit the outline entry: Book one 1-41$/);
    expect(screen.getByLabelText("Text of the outline entry")).toBe(area);
    editIntroduction.mockResolvedValue({ entry: entry(7, "io1", "Book one \\ior 1-41\\ior*"), warnings: [] });
    await fireEvent.input(area, { target: { value: "Book 1 \\ior 1-41\\ior*" } });
    await fireEvent.keyDown(area, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(editIntroduction).toHaveBeenCalledWith(7, "Book 1 \\ior 1-41\\ior*", OUTLINE_1));
    expect(screen.getByRole("button", { name: "Edit the introduction heading: Introduction" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit the outline title: Outline" })).toBeInTheDocument();
  });

  it("writes nothing on Escape or when the text was not changed", async () => {
    const area = await openEditor(/^Edit the introduction heading: Introduction$/);
    await fireEvent.input(area, { target: { value: "About" } });
    await fireEvent.keyDown(area, { key: "Escape" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(lines()[0].querySelector(".intro-text")?.textContent).toBe("Introduction");
    await fireEvent.click(screen.getByRole("button", { name: "Edit the introduction heading: Introduction" }));
    await fireEvent.click(screen.getByLabelText("Save the introduction heading"));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(editIntroduction).not.toHaveBeenCalled();
  });

  it("keeps the typed text and says why when the engine refuses", async () => {
    const area = await openEditor(/^Edit the introduction heading: Introduction$/);
    editIntroduction.mockRejectedValueOnce(new Error("REVISION_CONFLICT: this line was changed after the edit was started; nothing was written."));
    await fireEvent.input(area, { target: { value: "About this book" } });
    await fireEvent.click(screen.getByLabelText("Save the introduction heading"));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed after you started");
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("About this book");
  });

  it("reports marker problems in a saved line, and cannot be edited while a check runs", async () => {
    const area = await openEditor(/^Edit the introduction heading: Introduction$/);
    editIntroduction.mockResolvedValue({ entry: entry(4, "is", "About \\bk this"), warnings: ["Unbalanced \\bk: 1 open, 0 close"] });
    await fireEvent.input(area, { target: { value: "About \\bk this" } });
    await fireEvent.click(screen.getByLabelText("Save the introduction heading"));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved, but check the markers: Unbalanced \\bk: 1 open, 0 close");
    checkingProgress.set({ ...idle, running: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit the outline title: Outline" })).toBeDisabled());
  });
});
