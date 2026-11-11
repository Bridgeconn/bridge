import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import EditorHeader from "../EditorHeader.svelte";
import { rawView } from "../../editorPrefs";
import { project } from "../../stores";
import type { ProjectInfo } from "../../types/finding";

const LONG = "A very long project name that would never fit beside the chapter in a narrow editor column";

function openBook(books: Array<{ path: string; bookName: string }> = []): void {
  project.set({
    path: "/c/php", bookId: "php", bookName: "Philippians", targetLanguage: "Tamil", tcVersion: "3",
    chapters: ["1", "2", "3", "4"], checkTypes: {}, importedProjects: books,
  } as unknown as ProjectInfo);
}

describe("EditorHeader (#489)", () => {
  beforeEach(() => { rawView.set(false); openBook(); });

  it("names the chapter", () => {
    render(EditorHeader, { props: { chapter: "3", total: 4 } });
    expect(screen.getByRole("heading", { name: "Chapter 3 of 4" })).toBeInTheDocument();
  });

  it("carries the Raw USFM toggle, which shows its state and is saved", async () => {
    render(EditorHeader, { props: { chapter: "1", total: 4 } });
    const raw = screen.getByRole("button", { name: "Raw USFM" });
    expect(raw).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(true);
    expect(raw).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("bridge.editor.rawView.v1")).toBe("true");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(false);
    expect(raw).toHaveAttribute("aria-pressed", "false");
  });

  // Follow-up of 2026-11-11: breadcrumb, chapter, Raw USFM, overflow menu.
  it("reads, left to right: breadcrumb, chapter, Raw USFM, then the tools", () => {
    const { container } = render(EditorHeader, { props: { chapter: "1", total: 4, projectName: "IRV Tamil" } });
    const header = container.querySelector(".editor-header") as HTMLElement;
    const [crumbs, chapter, tools] = Array.from(header.children) as HTMLElement[];
    expect(crumbs).toBe(screen.getByRole("navigation", { name: "Navigation" }));
    expect(chapter).toBe(screen.getByRole("heading", { name: "Chapter 1 of 4" }));
    expect(tools).toContainElement(screen.getByRole("button", { name: "Raw USFM" }));
    expect(tools.firstElementChild).toBe(screen.getByRole("button", { name: "Raw USFM" }));
    expect(crumbs.textContent?.replace(/\s+/g, " ").trim()).toBe("Projects › IRV Tamil › Philippians");
  });

  it("the breadcrumb navigates as it did in the top bar", async () => {
    const onGoHome = vi.fn(), onGoToDashboard = vi.fn(), onBookChange = vi.fn();
    openBook([{ path: "/c/php", bookName: "Philippians" }, { path: "/c/col", bookName: "Colossians" }]);
    render(EditorHeader, { props: { chapter: "1", total: 4, projectName: "IRV Tamil", onGoHome, onGoToDashboard, onBookChange } });
    await fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(onGoHome).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "IRV Tamil" }));
    expect(onGoToDashboard).toHaveBeenCalledOnce();
    // A collection: the book crumb is the book switcher.
    const books = screen.getByRole("combobox", { name: "Book" }) as HTMLSelectElement;
    expect(books.value).toBe("/c/php");
    await fireEvent.change(books, { target: { value: "/c/col" } });
    expect(onBookChange).toHaveBeenCalledWith("/c/col");
  });

  it("a single book shows its name as text, and a book being opened disables the crumbs that would start another wait", () => {
    render(EditorHeader, { props: { chapter: "1", total: 4, projectName: "IRV Tamil", bookSwitching: true } });
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText("Philippians")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "IRV Tamil" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Projects" })).toBeEnabled();
  });

  // jsdom lays nothing out, so the truncation is pinned as the rules that
  // give it, plus the full name in the tooltip.
  it("a long project name truncates instead of pushing the chapter or the tools out", () => {
    render(EditorHeader, { props: { chapter: "1", total: 4, projectName: LONG } });
    expect(screen.getByRole("button", { name: LONG })).toHaveAttribute("title", LONG);
    const source: string = readFileSync(resolve("src/lib/components/EditorHeader.svelte"), "utf8");
    const rule = (selector: string) => new RegExp(`${selector.replace(/[.]/g, "\\.")}\\s*\\{([^}]*)\\}`).exec(source)?.[1] ?? "";
    // Equal side tracks that may shrink to nothing: the chapter stays centred.
    expect(rule(".editor-header")).toContain("grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)");
    expect(rule(".breadcrumb")).toContain("min-width: 0");
    expect(rule(".breadcrumb")).toContain("overflow: hidden");
    expect(rule(".crumb.project")).toContain("text-overflow: ellipsis");
    expect(rule(".crumb.project")).toContain("flex: 0 1 auto");
    expect(rule("h2")).toContain("white-space: nowrap");
  });

  // jsdom lays nothing out, so this pins the rule, not the rendering: the
  // header must not shrink in its column and stays at the top if that
  // column's own scroller moves.
  it("is styled to stay at the top of the panel", () => {
    const source: string = readFileSync(resolve("src/lib/components/EditorHeader.svelte"), "utf8");
    const rule = /\.editor-header\s*\{([^}]*)\}/.exec(source)?.[1] ?? "";
    expect(rule).toContain("position: sticky");
    expect(rule).toContain("top: 0");
    expect(rule).toContain("flex: none");
  });

  it("the overflow menu no longer offers Raw USFM, and App hands the header the breadcrumb", () => {
    const app: string = readFileSync(resolve("src/App.svelte"), "utf8");
    expect(app).not.toContain("Raw USFM");
    const use = /<EditorHeader[^>]*>/.exec(app)?.[0] ?? "";
    expect(use).toContain("{projectName}");
    expect(use).toContain("onGoHome={showProjectHome}");
    expect(use).toContain("onGoToDashboard={openDashboard}");
    expect(use).toContain("onBookChange={switchBook}");
  });
});
