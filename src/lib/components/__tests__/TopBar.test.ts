import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { tick } from "svelte";

const { engineInfo, desktop, minimize, toggleMaximize, closeWindow, isMaximized, onResized, stopResize } = vi.hoisted(() => ({
  engineInfo: vi.fn(), desktop: vi.fn(() => false), minimize: vi.fn(), toggleMaximize: vi.fn(),
  closeWindow: vi.fn(), isMaximized: vi.fn(), onResized: vi.fn(), stopResize: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: desktop }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ minimize, toggleMaximize, close: closeWindow, isMaximized, onResized }),
}));

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

// #347: a different Paratext project active shows as an error on the Sync icon,
// with the engine's sentence naming both projects as the tooltip.
describe("TopBar Paratext project mismatch (#347)", () => {
  beforeEach(() => {
    engineInfo.mockResolvedValue({ bridgeVersion: "0.9.7", companionSchemaVersion: 15 });
    openBook(["1"]);
    currentChapter.set("1");
  });

  it("marks the Sync icon as an error and shows the mismatch message in its instant tooltip", async () => {
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
    await fireEvent.mouseEnter(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent(message);
    expect(button).toHaveClass("sync-error");
    expect(button).toHaveAccessibleName(/Paratext project mismatch/);
    expect(button.querySelector(".sync-dot")).toHaveClass("connected");

    // The same project again: an ordinary connected mark and the plain tooltip.
    navigationStatus.update((state) => ({ ...state, paratext: { ...target, projectMismatch: false, mismatchMessage: "" } as never }));
    await tick();
    expect(screen.getByRole("tooltip")).toHaveTextContent("Sync on · Paratext connected · Logos disconnected");
    expect(button).not.toHaveClass("sync-error");
    await fireEvent.mouseLeave(button);
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

describe("TopBar window controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktop.mockReturnValue(true);
    engineInfo.mockResolvedValue({ bridgeVersion: "0.19.0", companionSchemaVersion: 15 });
    isMaximized.mockResolvedValue(false);
    onResized.mockResolvedValue(stopResize);
  });

  it("minimizes, maximizes, restores and closes through the desktop window API", async () => {
    mount({ screen: "home" });
    await fireEvent.click(screen.getByRole("button", { name: "Minimize window" }));
    expect(minimize).toHaveBeenCalledOnce();
    isMaximized.mockResolvedValue(true);
    await fireEvent.click(screen.getByRole("button", { name: "Maximize window" }));
    await screen.findByRole("button", { name: "Restore window" });
    isMaximized.mockResolvedValue(false);
    await fireEvent.click(screen.getByRole("button", { name: "Restore window" }));
    await screen.findByRole("button", { name: "Maximize window" });
    expect(toggleMaximize).toHaveBeenCalledTimes(2);
    await fireEvent.click(screen.getByRole("button", { name: "Close window" }));
    expect(closeWindow).toHaveBeenCalledOnce();
  });

  it("keeps settings and sync accessible and releases its resize listener", async () => {
    const onOpenSettings = vi.fn();
    const onOpenConnections = vi.fn();
    const view = mount({ screen: "home", onOpenSettings, onOpenConnections });
    await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    await fireEvent.click(screen.getByRole("button", { name: /Sync/ }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(onOpenConnections).toHaveBeenCalledOnce();
    expect(screen.queryByRole("navigation")).toBeNull();
    await waitFor(() => expect(onResized).toHaveBeenCalledOnce());
    view.unmount();
    expect(stopResize).toHaveBeenCalledOnce();
  });

  it("hides desktop window controls when viewed in a browser", () => {
    desktop.mockReturnValue(false);
    mount({ screen: "home" });
    expect(screen.queryByRole("group", { name: "Window controls" })).toBeNull();
  });
});
