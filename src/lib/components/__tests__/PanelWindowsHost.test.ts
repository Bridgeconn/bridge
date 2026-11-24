import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { PanelMessage } from "../../panelWindow";
const mocks = vi.hoisted(() => ({ window: vi.fn(), emit: vi.fn(), stop: vi.fn(), receive: null as ((m: PanelMessage) => void) | null }));
vi.mock("../../panelWindow", () => ({
  panelDesktop: () => true, panelLabel: (id: string) => `panel-${id}`, panelWindow: mocks.window,
  onPanelMessage: async (handler: (m: PanelMessage) => void) => { mocks.receive = handler; return mocks.stop; },
}));
vi.mock("@tauri-apps/api/event", () => ({ emitTo: mocks.emit }));
import Host from "../PanelWindowsHost.svelte";
import { project } from "../../stores";
import { SIDE_PANEL_ORDER, sidePanels, setSidePanel, resetPanelLayout } from "../../editorPrefs";
beforeEach(() => { vi.clearAllMocks(); resetPanelLayout(); project.set({ path: "A", bookId: "gen" } as never); mocks.window.mockResolvedValue(undefined); mocks.emit.mockResolvedValue(undefined); });
it("settles after startup instead of scheduling itself indefinitely, and closes/redocks only the chosen panel", async () => {
  render(Host, { onNavigate: vi.fn(), onRefresh: vi.fn(), onSettings: vi.fn() });
  // One per window of the four panels. The three added reference tabs (#519)
  // have windows too, but one that is not open separately is sent nothing.
  expect(SIDE_PANEL_ORDER).toHaveLength(7);
  await waitFor(() => expect(mocks.emit).toHaveBeenCalledTimes(4));
  await new Promise(resolve => setTimeout(resolve, 10)); expect(mocks.emit).toHaveBeenCalledTimes(4);
  expect(mocks.emit.mock.calls.map((call) => call[0]).sort()).toEqual(["panel-paratext", "panel-reference", "panel-review", "panel-source"]);
  setSidePanel("paratext", { open: true, detached: true });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("paratext", "open"));
  await waitFor(() => expect(mocks.emit).toHaveBeenCalledWith("panel-paratext", "panel-context-paratext", expect.objectContaining({ open: true })));
  expect(mocks.emit).toHaveBeenCalledWith("panel-source", "panel-context-source", expect.objectContaining({ open: false }));
  mocks.receive!({ kind: "close", id: "paratext", path: "A" });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("paratext", "hide"));
  // Closed from its own window: no longer "separate", so it opens as a tab next time.
  expect(get(sidePanels).paratext).toMatchObject({ open: false, detached: false });
  setSidePanel("paratext", { open: true, detached: true });
  mocks.receive!({ kind: "dock", id: "paratext", path: "A" });
  expect(get(sidePanels).paratext.detached).toBe(false);
});
it("ignores a stale detached window after a project switch", async () => {
  const navigate = vi.fn(), refresh = vi.fn();
  render(Host, { onNavigate: navigate, onRefresh: refresh, onSettings: vi.fn() });
  setSidePanel("source", { open: true, detached: true });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("source", "open"));
  project.set({ path: "B", bookId: "exo" } as never);
  mocks.receive!({ kind: "navigate", id: "source", path: "A", verse: "3-4" });
  mocks.receive!({ kind: "changed", id: "source", path: "A" });
  mocks.receive!({ kind: "close", id: "source", path: "A" });
  expect(navigate).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled(); expect(get(sidePanels).source.open).toBe(true);
});
// #519: an added reference tab keeps its folder in the main window's panel
// state, so a folder chosen in its own window is sent here and comes back
// with the next context.
it("keeps the folder an added reference tab was given in its own window, and sends it back", async () => {
  render(Host, { onNavigate: vi.fn(), onRefresh: vi.fn(), onSettings: vi.fn() });
  setSidePanel("reference2", { open: true, detached: true, folder: undefined });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("reference2", "open"));
  mocks.receive!({ kind: "referenceFolder", id: "reference2", path: "A", folder: "D:/bibles/esv" });
  expect(get(sidePanels).reference2).toMatchObject({ open: true, detached: true, folder: "D:/bibles/esv" });
  await waitFor(() => expect(mocks.emit).toHaveBeenCalledWith("panel-reference2", "panel-context-reference2",
    expect.objectContaining({ open: true, panels: expect.objectContaining({ reference2: expect.objectContaining({ folder: "D:/bibles/esv" }) }) })));
  // Not from another project's window, not for the project's own reference, not without a folder.
  mocks.receive!({ kind: "referenceFolder", id: "reference2", path: "B", folder: "D:/other" });
  mocks.receive!({ kind: "referenceFolder", id: "reference2", path: "A" });
  setSidePanel("reference", { open: true, detached: true });
  mocks.receive!({ kind: "referenceFolder", id: "reference", path: "A", folder: "D:/other" });
  expect(get(sidePanels).reference2.folder).toBe("D:/bibles/esv");
  expect(get(sidePanels).reference.folder).toBeUndefined();
  // Closed: its window is told once, hidden, and then left alone.
  setSidePanel("reference2", { open: false, detached: false });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("reference2", "hide"));
  expect(mocks.emit).toHaveBeenCalledWith("panel-reference2", "panel-context-reference2", expect.objectContaining({ open: false }));
  const sent = mocks.emit.mock.calls.filter((call) => call[0] === "panel-reference2").length;
  setSidePanel("source", { open: true });
  await waitFor(() => expect(mocks.emit).toHaveBeenCalledWith("panel-source", "panel-context-source", expect.objectContaining({ panels: expect.objectContaining({ source: expect.objectContaining({ open: true }) }) })));
  expect(mocks.emit.mock.calls.filter((call) => call[0] === "panel-reference2").length).toBe(sent);
  setSidePanel("reference2", { folder: undefined }); setSidePanel("source", { open: false }); setSidePanel("reference", { open: false, detached: false });
});
it("recovers to the in-app panel if the OS window cannot open", async () => {
  mocks.window.mockRejectedValueOnce(new Error("Window unavailable"));
  render(Host, { onNavigate: vi.fn(), onRefresh: vi.fn(), onSettings: vi.fn() });
  setSidePanel("reference", { open: true, detached: true });
  await screen.findByRole("alert"); expect(get(sidePanels).reference.detached).toBe(false);
});
