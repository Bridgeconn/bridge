import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const api = vi.hoisted(() => ({
  hubStatus: vi.fn(), hubJoin: vi.fn(), hubLeave: vi.fn(), hubLink: vi.fn(),
  hubSyncNow: vi.fn(), hubConflicts: vi.fn(), hubResolveConflict: vi.fn(),
  hubStart: vi.fn(), hubStop: vi.fn(), hubProbe: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: api }));

import TeamPane from "../TeamPane.svelte";
import type { HubConflict, HubServer, HubStatus } from "../../types/finding";

function server(overrides: Partial<HubServer> = {}): HubServer {
  return {
    state: "stopped", pid: null, host: "", port: 8765, url: "http://127.0.0.1:8765", lanUrl: "http://bridge-a:8765",
    dataDir: "C:/Users/x/AppData/Local/Bridge/hub", adminJoinCode: null, portInUse: false, startedAt: null,
    error: null, autostart: false, ...overrides,
  };
}

function status(overrides: Partial<HubStatus> = {}): HubStatus {
  return {
    joined: true, url: "http://team-hub:8765", identity: { displayName: "Revant", role: "project_admin" },
    linkedHubProjectId: "p-1", sync: { pullCursor: 3, lastPushAt: null, lastPullAt: "2026-10-14T09:00:00Z", lastError: null },
    openConflicts: 0, syncing: false, server: server(), ...overrides,
  };
}

const notJoined = (overrides: Partial<HubServer> = {}) =>
  status({ joined: false, url: "", linkedHubProjectId: "", sync: null, server: server(overrides) });

const running = { state: "running" as const, pid: 4321, host: "0.0.0.0", adminJoinCode: "1A2B-3C4D-5E6F", autostart: true };

const conflict: HubConflict = {
  id: 7, eventId: "e-1", table: "human_decisions", rowKey: "r-1", baseRevision: 1, localRevision: 2,
  reason: "revision_mismatch", theirActorId: "u-2", theirActorName: "Rina", theirCreatedAt: "2026-10-14T09:00:00Z",
  theirPayload: { decision: "ignored" }, receivedAt: "", resolvedAt: null, resolution: null,
};

describe("TeamPane (#80)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.hubConflicts.mockResolvedValue({ hubProjectId: "p-1", conflicts: [] });
    api.hubProbe.mockResolvedValue({ url: "", reachable: false, status: null, error: "refused" });
  });

  it("joins a hub with a code and a name", async () => {
    api.hubStatus.mockResolvedValueOnce(status({ joined: false, url: "", linkedHubProjectId: "" }))
      .mockResolvedValue(status({ linkedHubProjectId: "" }));
    api.hubJoin.mockResolvedValue(status());
    render(TeamPane);
    expect(screen.queryByLabelText("Hub address")).not.toBeInTheDocument();
    await fireEvent.click(await screen.findByRole("button", { name: "Join a hub" }));
    await fireEvent.input(await screen.findByLabelText("Hub address"), { target: { value: " http://team-hub:8765 " } });
    await fireEvent.input(screen.getByLabelText("Join code"), { target: { value: "1A2B-3C4D-5E6F" } });
    await fireEvent.input(screen.getByLabelText("Your name on the team"), { target: { value: "Revant" } });
    await fireEvent.click(screen.getByRole("button", { name: "Join" }));
    await waitFor(() => expect(api.hubJoin).toHaveBeenCalledWith("http://team-hub:8765", "1A2B-3C4D-5E6F", "Revant"));
    await screen.findByText("Joined the hub.");
    expect(screen.getByRole("button", { name: "Link this book" })).toBeInTheDocument();
  });

  it("shows sync state, syncs on request and keeps mine on a conflict", async () => {
    api.hubStatus.mockResolvedValue(status({ openConflicts: 1 }));
    api.hubConflicts.mockResolvedValueOnce({ hubProjectId: "p-1", conflicts: [conflict] })
      .mockResolvedValue({ hubProjectId: "p-1", conflicts: [] });
    api.hubSyncNow.mockResolvedValue(status());
    api.hubResolveConflict.mockResolvedValue({ hubProjectId: "p-1", conflicts: [] });
    render(TeamPane);
    await screen.findByText("Conflicts (1)");
    expect(screen.getByText(/Rina/)).toBeInTheDocument();
    expect(screen.getByText(/ignored/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    await waitFor(() => expect(api.hubResolveConflict).toHaveBeenCalledWith(7, "kept-mine"));
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await waitFor(() => expect(api.hubSyncNow).toHaveBeenCalled());
  });

  it("names a Language QA overrides conflict by what the other device switched off (#277)", async () => {
    api.hubStatus.mockResolvedValue(status({ openConflicts: 1 }));
    api.hubConflicts.mockResolvedValue({ hubProjectId: "p-1", conflicts: [{
      ...conflict, table: "project_state",
      theirPayload: { version: 1, pack: "hi-irv", document: { rules: { "hi.lex.unknown": { enabled: false } } } },
    }] });
    render(TeamPane);
    expect(await screen.findByText(/Language QA checker settings \(hi-irv\): switched off hi\.lex\.unknown/)).toBeInTheDocument();
  });

  it("shows the last error without blocking anything", async () => {
    api.hubStatus.mockResolvedValue(status({ sync: { pullCursor: 0, lastPushAt: null, lastPullAt: null, lastError: "The hub at http://team-hub:8765 could not be reached (refused)." } }));
    render(TeamPane);
    await screen.findByText(/Last attempt: The hub at http:\/\/team-hub:8765 could not be reached/);
    expect(screen.getByText("never")).toBeInTheDocument();
  });
});

describe("TeamPane: Start a hub / Join a hub (#46)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.hubConflicts.mockResolvedValue({ hubProjectId: "", conflicts: [] });
    api.hubProbe.mockResolvedValue({ url: "", reachable: false, status: null, error: "refused" });
  });

  it("offers both when no hub runs, and follows a start until the hub runs", async () => {
    api.hubStatus.mockResolvedValueOnce(notJoined())
      .mockResolvedValueOnce(notJoined({ state: "starting", pid: 4321 }))
      .mockResolvedValue(notJoined(running));
    api.hubStart.mockResolvedValue(notJoined({ state: "starting", pid: 4321 }));
    render(TeamPane);
    const start = await screen.findByRole("button", { name: "Start a hub" });
    expect(start).toBeEnabled();
    expect(screen.getByRole("button", { name: "Join a hub" })).toBeEnabled();
    await fireEvent.click(start);
    await waitFor(() => expect(api.hubStart).toHaveBeenCalled());
    await screen.findByText("Starting the hub…");
    expect(screen.getByRole("button", { name: "Start a hub" })).toBeDisabled();
    await screen.findByText("running on this machine", {}, { timeout: 3000 });
    expect(screen.getByText("http://bridge-a:8765")).toBeInTheDocument();
    expect(screen.getByText("1A2B-3C4D-5E6F")).toBeInTheDocument();
  });

  it("disables Start while a hub runs here, keeps Join, and joins this hub with its code", async () => {
    api.hubStatus.mockResolvedValue(notJoined(running));
    api.hubJoin.mockResolvedValue(status({ server: server(running) }));
    render(TeamPane);
    expect(await screen.findByRole("button", { name: "Start a hub" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Join a hub" })).toBeEnabled();
    await fireEvent.click(screen.getByRole("button", { name: "Join this hub" }));
    await waitFor(() => expect(api.hubJoin).toHaveBeenCalledWith("http://127.0.0.1:8765", "1A2B-3C4D-5E6F", ""));
  });

  it("stops the hub it runs", async () => {
    api.hubStatus.mockResolvedValueOnce(notJoined(running)).mockResolvedValue(notJoined());
    api.hubStop.mockResolvedValue(notJoined());
    render(TeamPane);
    await fireEvent.click(await screen.findByRole("button", { name: "Stop the hub" }));
    await waitFor(() => expect(api.hubStop).toHaveBeenCalled());
    await screen.findByText("Hub stopped.");
    expect(screen.getByRole("button", { name: "Start a hub" })).toBeEnabled();
  });

  it("disables Start when something already answers on the port here", async () => {
    api.hubStatus.mockResolvedValue(notJoined({ portInUse: true }));
    render(TeamPane);
    expect(await screen.findByRole("button", { name: "Start a hub" })).toBeDisabled();
    expect(screen.getByText(/already answers on port 8765, probably a hub\. Join it instead\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join a hub" })).toBeEnabled();
  });

  it("disables Start when a hub answers at the address typed under Join a hub", async () => {
    api.hubStatus.mockResolvedValue(notJoined());
    api.hubProbe.mockResolvedValue({ url: "http://team-hub:8765", reachable: true, status: "ok", error: null });
    render(TeamPane);
    await fireEvent.click(await screen.findByRole("button", { name: "Join a hub" }));
    await fireEvent.input(await screen.findByLabelText("Hub address"), { target: { value: "http://team-hub:8765" } });
    await waitFor(() => expect(api.hubProbe).toHaveBeenCalledWith("http://team-hub:8765"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start a hub" })).toBeDisabled());
    expect(screen.getByText("A hub already answers at http://team-hub:8765. Join it instead.")).toBeInTheDocument();
  });

  it("does not probe an address that is not http(s) yet", async () => {
    api.hubStatus.mockResolvedValue(notJoined());
    render(TeamPane);
    await fireEvent.click(await screen.findByRole("button", { name: "Join a hub" }));
    await fireEvent.input(await screen.findByLabelText("Hub address"), { target: { value: "team-hub" } });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(api.hubProbe).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start a hub" })).toBeEnabled();
  });

  it("shows why a start failed and offers Start again", async () => {
    api.hubStatus.mockResolvedValue(notJoined({ state: "failed", error: "ModuleNotFoundError: No module named 'uvicorn'" }));
    render(TeamPane);
    expect(await screen.findByText(/No module named 'uvicorn'/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start a hub" })).toBeEnabled();
  });

  it("shows the hub it hosts beside the joined view, without Join this hub", async () => {
    api.hubStatus.mockResolvedValue(status({ server: server(running) }));
    render(TeamPane);
    await screen.findByText("running on this machine");
    expect(screen.getByRole("button", { name: "Stop the hub" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join this hub" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a hub" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave the hub" })).toBeInTheDocument();
  });
});
