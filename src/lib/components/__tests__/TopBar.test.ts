import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";

const { engineInfo } = vi.hoisted(() => ({ engineInfo: vi.fn() }));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { engineInfo },
}));

import TopBar from "../TopBar.svelte";
import { project, currentChapter, navigationStatus } from "../../stores";
import type { ProjectInfo } from "../../types/finding";

function openBook(chapters: string[]): void {
  project.set({
    path: "C:/projects/php",
    bookId: "php",
    bookName: "Philippians",
    targetLanguage: "Tamil",
    tcVersion: "9",
    chapters,
    checkTypes: {},
  } as ProjectInfo);
}

function mount(overrides: Record<string, unknown> = {}) {
  return render(TopBar, {
    props: {
      screen: "editor",
      projectName: "Philippians",
      onGoHome: vi.fn(),
      onGoToDashboard: vi.fn(),
      onOpenSettings: vi.fn(),
      onOpenConnections: vi.fn(),
      onOpenExport: vi.fn(),
      onGotoVerse: vi.fn(),
      onChapterChange: vi.fn(),
      onBookChange: vi.fn(),
      exportEnabled: true,
      ...overrides,
    },
  });
}

const prev = () => screen.getByLabelText("Previous chapter") as HTMLButtonElement;
const next = () => screen.getByLabelText("Next chapter") as HTMLButtonElement;

// #347: a different Paratext project active shows as an error on the P mark,
// with the engine's sentence naming both projects as the tooltip.
describe("TopBar Paratext project mismatch (#347)", () => {
  beforeEach(() => {
    engineInfo.mockResolvedValue({ bridgeVersion: "0.9.7", companionSchemaVersion: 15 });
    openBook(["1"]);
    currentChapter.set("1");
  });

  it("marks P as an error and carries the message naming both projects", async () => {
    const message = "The active Paratext project, DVT (4ae31b0d…), does not match IRVTam (c2d042a9…), the project this book was imported from. Bridge neither follows nor sends navigation, and keeps notes queued, until that project is active in Paratext.";
    const target = { enabled: true, checking: false, connected: true, reference: "PHP 1:1", error: "", checkedAt: 1 };
    navigationStatus.set({
      enabled: true, ownsNavigation: true, ownerConflict: false, currentReference: "PHP 1:1", currentOrigin: "bridge",
      candidate: null,
      paratext: { ...target, projectMismatch: true, expectedProjectId: "c2d042a9-linked", expectedProjectName: "IRVTam", mismatchMessage: message } as never,
      logos: { ...target, enabled: false, connected: false } as never,
    });
    mount();
    const button = screen.getByRole("button", { name: /Sync/ });
    expect(button.getAttribute("title")).toBe(message);
    const mark = button.querySelector("span") as HTMLElement;
    expect(mark.textContent).toBe("P");
    expect(mark.classList.contains("error")).toBe(true);
    expect(mark.classList.contains("connected")).toBe(true);

    // The same project again: an ordinary connected mark and the plain tooltip.
    navigationStatus.update((state) => ({ ...state, paratext: { ...target, projectMismatch: false, mismatchMessage: "" } as never }));
    await tick();
    expect(button.getAttribute("title")).toBe("Paratext and Logos navigation");
    expect((button.querySelector("span") as HTMLElement).classList.contains("error")).toBe(false);
  });
});

describe("TopBar chapter navigation (issue #53)", () => {
  beforeEach(() => {
    engineInfo.mockResolvedValue({ bridgeVersion: "0.9.7", companionSchemaVersion: 15 });
    openBook(["1", "2", "3", "4"]);
    currentChapter.set("2");
  });

  it("steps to the previous and next chapter through the same handler as the dropdown", async () => {
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    await fireEvent.click(next());
    expect(onChapterChange).toHaveBeenCalledWith("3");

    await fireEvent.click(prev());
    expect(onChapterChange).toHaveBeenCalledWith("1");
    expect(onChapterChange).toHaveBeenCalledTimes(2);
  });

  it("disables Previous on the first chapter", async () => {
    currentChapter.set("1");
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    expect(prev()).toBeDisabled();
    expect(next()).not.toBeDisabled();
    await fireEvent.click(prev());
    expect(onChapterChange).not.toHaveBeenCalled();
  });

  it("disables Next on the last chapter", async () => {
    currentChapter.set("4");
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    expect(next()).toBeDisabled();
    expect(prev()).not.toBeDisabled();
    await fireEvent.click(next());
    expect(onChapterChange).not.toHaveBeenCalled();
  });

  it("disables both ends for a single-chapter book", () => {
    openBook(["1"]);
    currentChapter.set("1");
    mount();

    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  it("steps by position in the book's chapter list, not by number", async () => {
    // Chapter ids are strings from the engine and are not guaranteed to be a
    // clean 1..n run; stepping must agree with the dropdown the reader sees.
    openBook(["1", "2", "2b", "3"]);
    currentChapter.set("2");
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    await fireEvent.click(next());
    expect(onChapterChange).toHaveBeenCalledWith("2b");
  });

  it("disables both controls when the current chapter is not in the book", () => {
    // Mid-book-switch: the chapter list has already changed under a chapter
    // number that no longer exists. Stepping from nowhere would be a guess.
    currentChapter.set("99");
    mount();

    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  it("is labelled as a group and reachable by keyboard", () => {
    mount();
    expect(screen.getByRole("group", { name: "Chapter navigation" })).toBeTruthy();
    // Real <button>s, so they are tab-stops and Enter/Space activate them.
    expect(prev().tagName).toBe("BUTTON");
    expect(next().tagName).toBe("BUTTON");
    expect(prev()).toHaveAttribute("title");
    expect(next()).toHaveAttribute("title");
  });

  it("is absent outside the editor screen", () => {
    mount({ screen: "dashboard" });
    expect(screen.queryByLabelText("Previous chapter")).toBeNull();
    expect(screen.queryByLabelText("Next chapter")).toBeNull();
  });
});
