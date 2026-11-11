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
import TopBarMenusFixture from "./fixtures/TopBarMenusFixture.svelte";
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

// #488: View, Check and Bookmarks sit right of the name, in the editor only.
describe("TopBar menus slot (#488)", () => {
  beforeEach(() => {
    engineInfo.mockResolvedValue({ bridgeVersion: "0.9.7", companionSchemaVersion: 15 });
    openBook(["1", "2"]);
    currentChapter.set("1");
  });

  it("shows the menus right after the name on the editor screen, then the project's name", async () => {
    const onGoToDashboard = vi.fn();
    const { container } = render(TopBarMenusFixture, { props: { screen: "editor", onGoToDashboard } });
    const menus = screen.getByRole("group", { name: "Menus" });
    expect(menus).toContainElement(screen.getByRole("button", { name: "View" }));
    const brand = container.querySelector(".brand") as HTMLElement;
    const name = screen.getByRole("button", { name: "Philippians" });
    expect(brand.compareDocumentPosition(menus) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(menus.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The project's name opens the project page.
    expect(name).toHaveAttribute("title", "Philippians: open the project page");
    await fireEvent.click(name);
    expect(onGoToDashboard).toHaveBeenCalledOnce();
  });

  // 2026-11-11, third round: the chapter picker and Go to are in the editor
  // panel's header; Export and Settings are in the File menu.
  it("has no breadcrumb, chapter picker, Go to, Export button or Settings gear on the editor screen", () => {
    render(TopBarMenusFixture, { props: { screen: "editor" } });
    expect(screen.queryByRole("navigation", { name: "Navigation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Projects" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Chapter navigation" })).toBeNull();
    expect(screen.queryByPlaceholderText("Go to 1:4")).toBeNull();
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Settings" })).toBeNull();
  });

  it("keeps the breadcrumb on the dashboard", () => {
    render(TopBarMenusFixture, { props: { screen: "dashboard" } });
    expect(screen.getByRole("navigation", { name: "Navigation" })).toContainElement(screen.getByRole("button", { name: "Projects" }));
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("shows no menus off the editor screen", () => {
    render(TopBarMenusFixture, { props: { screen: "dashboard" } });
    expect(screen.queryByRole("group", { name: "Menus" })).toBeNull();
  });
});
