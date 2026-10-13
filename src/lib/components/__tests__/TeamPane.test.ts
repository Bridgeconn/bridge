import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const api = vi.hoisted(() => ({
  hubStatus: vi.fn(), hubJoin: vi.fn(), hubLeave: vi.fn(), hubLink: vi.fn(),
  hubSyncNow: vi.fn(), hubConflicts: vi.fn(), hubResolveConflict: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: api }));

import TeamPane from "../TeamPane.svelte";
import type { HubConflict, HubStatus } from "../../types/finding";

function status(overrides: Partial<HubStatus> = {}): HubStatus {
  return {
    joined: true, url: "http://team-hub:8765", identity: { displayName: "Revant", role: "project_admin" },
    linkedHubProjectId: "p-1", sync: { pullCursor: 3, lastPushAt: null, lastPullAt: "2026-10-14T09:00:00Z", lastError: null },
    openConflicts: 0, syncing: false, ...overrides,
  };
}

const conflict: HubConflict = {
  id: 7, eventId: "e-1", table: "human_decisions", rowKey: "r-1", baseRevision: 1, localRevision: 2,
  reason: "revision_mismatch", theirActorId: "u-2", theirActorName: "Rina", theirCreatedAt: "2026-10-14T09:00:00Z",
  theirPayload: { decision: "ignored" }, receivedAt: "", resolvedAt: null, resolution: null,
};

describe("TeamPane (#80)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.hubConflicts.mockResolvedValue({ hubProjectId: "p-1", conflicts: [] });
  });

  it("joins a hub with a code and a name", async () => {
    api.hubStatus.mockResolvedValueOnce(status({ joined: false, url: "", linkedHubProjectId: "" }))
      .mockResolvedValue(status({ linkedHubProjectId: "" }));
    api.hubJoin.mockResolvedValue(status());
    render(TeamPane);
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

  it("shows the last error without blocking anything", async () => {
    api.hubStatus.mockResolvedValue(status({ sync: { pullCursor: 0, lastPushAt: null, lastPullAt: null, lastError: "The hub at http://team-hub:8765 could not be reached (refused)." } }));
    render(TeamPane);
    await screen.findByText(/Last attempt: The hub at http:\/\/team-hub:8765 could not be reached/);
    expect(screen.getByText("never")).toBeInTheDocument();
  });
});
