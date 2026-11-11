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
import { sidePanels, setSidePanel, resetPanelLayout } from "../../editorPrefs";
beforeEach(() => { vi.clearAllMocks(); resetPanelLayout(); project.set({ path: "A", bookId: "gen" } as never); mocks.window.mockResolvedValue(undefined); mocks.emit.mockResolvedValue(undefined); });
it("settles after startup instead of scheduling itself indefinitely, and closes/redocks only the chosen panel", async () => {
  render(Host, { onNavigate: vi.fn(), onRefresh: vi.fn(), onSettings: vi.fn() });
  await waitFor(() => expect(mocks.emit).toHaveBeenCalledTimes(5));
  await new Promise(resolve => setTimeout(resolve, 10)); expect(mocks.emit).toHaveBeenCalledTimes(5);
  setSidePanel("languageQa", { open: true, detached: true });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("languageQa", "open"));
  await waitFor(() => expect(mocks.emit).toHaveBeenCalledWith("panel-languageQa", "panel-context-languageQa", expect.objectContaining({ open: true })));
  expect(mocks.emit).toHaveBeenCalledWith("panel-source", "panel-context-source", expect.objectContaining({ open: false }));
  mocks.receive!({ kind: "close", id: "languageQa", path: "A" });
  await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("languageQa", "hide"));
  expect(get(sidePanels).languageQa.detached).toBe(true);
  setSidePanel("languageQa", { open: true });
  mocks.receive!({ kind: "dock", id: "languageQa", path: "A" });
  expect(get(sidePanels).languageQa.detached).toBe(false);
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
it("recovers to the in-app panel if the OS window cannot open", async () => {
  mocks.window.mockRejectedValueOnce(new Error("Window unavailable"));
  render(Host, { onNavigate: vi.fn(), onRefresh: vi.fn(), onSettings: vi.fn() });
  setSidePanel("reference", { open: true, detached: true });
  await screen.findByRole("alert"); expect(get(sidePanels).reference.detached).toBe(false);
});
