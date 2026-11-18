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
      ...overrides,
    },
  });
}

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

  it("shows an instant hint on each window button, not a delayed native title", async () => {
    mount({ screen: "home" });
    for (const [name, hint] of [["Minimize window", "Minimize"], ["Maximize window", "Maximize"], ["Close window", "Close"]]) {
      const button = screen.getByRole("button", { name });
      expect(button).not.toHaveAttribute("title");
      await fireEvent.mouseEnter(button);
      expect(screen.getByRole("tooltip")).toHaveTextContent(hint);
      await fireEvent.mouseLeave(button);
      expect(screen.queryByRole("tooltip")).toBeNull();
    }
  });

  it("keeps settings accessible, hides the sync indicator, and releases its resize listener", async () => {
    const onOpenSettings = vi.fn();
    const onOpenConnections = vi.fn();
    const view = mount({ screen: "home", onOpenSettings, onOpenConnections });
    await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    // No current verse to follow on the home screen or the dashboard, so no
    // sync indicator there; it is on the editor, review and validation screens.
    expect(screen.queryByRole("button", { name: /Sync/ })).toBeNull();
    expect(onOpenConnections).not.toHaveBeenCalled();
    expect(screen.queryByRole("navigation")).toBeNull();
    await waitFor(() => expect(onResized).toHaveBeenCalledOnce());
    view.unmount();
    expect(stopResize).toHaveBeenCalledOnce();
  });

  it("shows the sync indicator on the screens that have a current verse", async () => {
    for (const where of ["editor", "review", "validation"] as const) {
      const onOpenConnections = vi.fn();
      const view = mount({ screen: where, onOpenConnections });
      await fireEvent.click(screen.getByRole("button", { name: /Sync/ }));
      expect(onOpenConnections).toHaveBeenCalledOnce();
      view.unmount();
    }
    mount({ screen: "dashboard" });
    expect(screen.queryByRole("button", { name: /Sync/ })).toBeNull();
  });

  it("hides desktop window controls when viewed in a browser", () => {
    desktop.mockReturnValue(false);
    mount({ screen: "home" });
    expect(screen.queryByRole("group", { name: "Window controls" })).toBeNull();
  });
});

// 2026-11-13: the editor's bar is the name, the breadcrumb, then Sync, Export
// and Settings. Its menus moved to the left rail (ActivityBar.svelte).
describe("TopBar on the editor screen", () => {
  beforeEach(() => {
    desktop.mockReturnValue(false);
    engineInfo.mockResolvedValue({ bridgeVersion: "0.9.7", companionSchemaVersion: 15 });
    openBook(["1", "2"]);
    currentChapter.set("1");
  });

  it("shows Projects, the project and the open book, with a button that closes the editor", async () => {
    const onGoToDashboard = vi.fn();
    const onGoHome = vi.fn();
    const { container } = mount({ projectName: "IRV Tamil", onGoToDashboard, onGoHome });
    const crumbs = screen.getByRole("navigation", { name: "Navigation" });
    const name = screen.getByRole("button", { name: "IRV Tamil" });
    expect(crumbs).toContainElement(screen.getByRole("button", { name: "Projects" }));
    expect(crumbs).toContainElement(name);
    expect(crumbs.querySelector(".crumb.current")).toHaveTextContent("Philippians");
    expect(screen.queryByRole("group", { name: "Menus" })).toBeNull();
    // No version number on the editor screen.
    await tick();
    expect(container.querySelector(".version")).toBeNull();
    expect(name).toHaveAttribute("title", "IRV Tamil: open the project page");
    await fireEvent.click(name);
    expect(onGoToDashboard).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    expect(onGoToDashboard).toHaveBeenCalledTimes(2);
    await fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(onGoHome).toHaveBeenCalledOnce();
  });

  it("a collection's book is a searchable picker; a single book is its name as text", async () => {
    const onBookChange = vi.fn();
    project.update((info) => ({ ...(info as ProjectInfo), importedProjects: [
      { path: "C:/projects/php", bookId: "php", bookName: "Philippians" },
      { path: "C:/projects/col", bookId: "col", bookName: "Colossians" },
      { path: "C:/projects/phm", bookId: "phm", bookName: "Philemon" },
    ] }) as ProjectInfo);
    const view = mount({ onBookChange });
    const trigger = screen.getByRole("button", { name: "Book: Philippians" });
    expect(screen.queryByRole("listbox")).toBeNull();
    await fireEvent.click(trigger);
    const search = screen.getByRole("combobox", { name: "Search books" });
    await waitFor(() => expect(document.activeElement).toBe(search));
    expect(screen.getAllByRole("option").map((item) => item.querySelector(".label")?.textContent)).toEqual(["Philippians", "Colossians", "Philemon"]);
    expect(screen.getByRole("option", { name: /Philippians/ })).toHaveAttribute("aria-selected", "true");
    // Filters as typed, by name or by book code.
    await fireEvent.input(search, { target: { value: "phi" } });
    expect(screen.getAllByRole("option").map((item) => item.querySelector(".label")?.textContent)).toEqual(["Philippians", "Philemon"]);
    await fireEvent.input(search, { target: { value: "zzz" } });
    expect(screen.queryByRole("option")).toBeNull();
    expect(screen.getByText(/No book matches/)).toBeInTheDocument();
    await fireEvent.input(search, { target: { value: "COL" } });
    await fireEvent.keyDown(search, { key: "Enter" });
    expect(onBookChange).toHaveBeenCalledWith("C:/projects/col");
    expect(screen.queryByRole("listbox")).toBeNull();
    // Arrow keys move the mark; the open book chosen again changes nothing.
    await fireEvent.click(trigger);
    await fireEvent.keyDown(screen.getByRole("combobox", { name: "Search books" }), { key: "ArrowDown" });
    await fireEvent.keyDown(screen.getByRole("combobox", { name: "Search books" }), { key: "ArrowUp" });
    await fireEvent.keyDown(screen.getByRole("combobox", { name: "Search books" }), { key: "Enter" });
    expect(onBookChange).toHaveBeenCalledOnce();
    await fireEvent.click(trigger);
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    view.unmount();
    openBook(["1"]);
    mount();
    expect(screen.queryByRole("button", { name: /^Book:/ })).toBeNull();
    expect(screen.getByText("Philippians", { selector: ".crumb.current" })).toBeInTheDocument();
  });

  it("has Settings and Export project on the bar, and no chapter picker or Go to", async () => {
    const onExport = vi.fn();
    const onOpenSettings = vi.fn();
    mount({ onExport, onOpenSettings });
    await fireEvent.click(screen.getByRole("button", { name: "Export project" }));
    expect(onExport).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(screen.queryByRole("group", { name: "Chapter navigation" })).toBeNull();
    expect(screen.queryByPlaceholderText("Go to 1:4")).toBeNull();
  });

  it("keeps the breadcrumb and the version on the dashboard, with no Export there", async () => {
    const { container } = mount({ screen: "dashboard", onExport: vi.fn() });
    expect(screen.getByRole("navigation", { name: "Navigation" })).toContainElement(screen.getByRole("button", { name: "Projects" }));
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export project" })).toBeNull();
    await waitFor(() => expect(container.querySelector(".version")).toHaveTextContent("0.9.7"));
  });
});
