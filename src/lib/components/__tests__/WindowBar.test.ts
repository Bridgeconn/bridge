import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";

const { minimize, toggleMaximize, closeWindow, isMaximized, onResized } = vi.hoisted(() => ({
  minimize: vi.fn(), toggleMaximize: vi.fn(), closeWindow: vi.fn(), isMaximized: vi.fn(), onResized: vi.fn(),
}));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ minimize, toggleMaximize, close: closeWindow, isMaximized, onResized }),
}));

import WindowBar from "../WindowBar.svelte";
import { SIDE_PANEL_ORDER } from "../../editorPrefs";

// Vitest runs from the repo root.
const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

// 2026-11-14 (Joel): every separate window has the app's own title bar, with
// one Close, and no native one.
describe("the separate windows' title bar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isMaximized.mockResolvedValue(false);
    onResized.mockResolvedValue(() => {});
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  });
  afterEach(() => { delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

  it("shows the window's name and the three window buttons; Close asks the main window", async () => {
    const onClose = vi.fn();
    render(WindowBar, { props: { title: "Paratext notes", onClose } });
    expect(screen.getByText("Paratext notes")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Minimize window" }));
    expect(minimize).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "Maximize window" }));
    expect(toggleMaximize).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "Close window" }));
    expect(onClose).toHaveBeenCalledOnce();
    // The window is hidden by the main window, never closed from here.
    expect(closeWindow).not.toHaveBeenCalled();
  });

  it("does not close while the window's work is being saved", async () => {
    render(WindowBar, { props: { title: "Alignment", onClose: vi.fn(), closeDisabled: true } });
    expect(screen.getByRole("button", { name: "Close window" })).toBeDisabled();
  });

  it("has no window buttons in a browser", () => {
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    render(WindowBar, { props: { title: "Review", onClose: vi.fn() } });
    expect(screen.queryByRole("group", { name: "Window controls" })).toBeNull();
  });

  it("every separate window has no native title bar and may use the window buttons", () => {
    const config = JSON.parse(read("src-tauri/tauri.conf.json")) as { app: { windows: { label?: string; decorations?: boolean }[] } };
    const separate = config.app.windows.filter((entry) => entry.label && entry.label !== "splash");
    // One declared window per side panel, the added reference tabs among them
    // (#519): a panel with no declared window could not be shown separately.
    expect(SIDE_PANEL_ORDER).toEqual(["source", "reference", "reference2", "reference3", "reference4", "paratext", "review"]);
    expect(separate.map((entry) => entry.label)).toEqual(["review-queue", "alignment", ...SIDE_PANEL_ORDER.map((id) => `panel-${id}`)]);
    for (const entry of separate) expect(entry.decorations, entry.label).toBe(false);
    const capability = JSON.parse(read("src-tauri/capabilities/main-window-controls.json")) as { windows: string[]; permissions: string[] };
    expect(capability.windows).toEqual(expect.arrayContaining(["main", "alignment", "review-queue", "panel-*"]));
    expect(capability.permissions).toEqual(expect.arrayContaining([
      "core:window:allow-start-dragging", "core:window:allow-minimize", "core:window:allow-toggle-maximize", "core:window:allow-is-maximized",
    ]));
  });

  it("each window page draws the bar", () => {
    for (const file of ["AlignmentWindow", "PanelWindow", "ReviewQueueWindow"]) {
      expect(read(`src/lib/components/${file}.svelte`), file).toContain("<WindowBar ");
    }
  });
});
