import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { paratextLinkStatus, paratextRelink, paratextRefresh, pickFolder } = vi.hoisted(() => ({
  paratextLinkStatus: vi.fn(),
  paratextRelink: vi.fn(),
  paratextRefresh: vi.fn(),
  pickFolder: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { paratextLinkStatus, paratextRelink, paratextRefresh, pickFolder },
}));

import ParatextLinkStatus from "../ParatextLinkStatus.svelte";
import type { ParatextLinkStatus as Status } from "../../types/paratext";

function status(overrides: Partial<Status> = {}): Status {
  return {
    state: "linked", folder: "C:/PT/TSTP", guid: "abc", name: "TSTP", fullName: "Synthetic", versification: "eng",
    encoding: "65001", booksPresent: ["TIT"], linkedAt: "2026-10-22T00:00:00+00:00",
    files: {
      notes: { count: 2, users: ["User A", "User B"] }, bookNames: true, commentTags: true, userAccess: false,
      termRenderings: false, errorDenials: false, spellingStatus: false, checkingStatus: false, progress: false,
    },
    ...overrides,
  };
}

describe("ParatextLinkStatus (#356)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows nothing for a book that was not imported from Paratext", async () => {
    paratextLinkStatus.mockResolvedValue(status({ state: "notParatext" }));
    render(ParatextLinkStatus, { props: { projectKey: "a" } });
    await waitFor(() => expect(paratextLinkStatus).toHaveBeenCalled());
    expect(screen.queryByTestId("paratext-link-status")).toBeNull();
  });

  it("shows a linked project and refreshes it", async () => {
    paratextLinkStatus.mockResolvedValue(status());
    paratextRefresh.mockResolvedValue(status({ files: { ...status().files, notes: { count: 3, users: [] } } }));
    render(ParatextLinkStatus, { props: { projectKey: "a" } });
    const line = await screen.findByTestId("paratext-link-status");
    expect(line).toHaveTextContent("Paratext TSTP · linked · 2 notes files");

    await fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(line).toHaveTextContent("3 notes files"));
  });

  it("offers the moved folder and relinks to it", async () => {
    paratextLinkStatus.mockResolvedValue(status({ state: "folderMoved", candidate: "C:/PT/TSTP-new" }));
    paratextRelink.mockResolvedValue(status({ folder: "C:/PT/TSTP-new" }));
    render(ParatextLinkStatus, { props: { projectKey: "a" } });
    await screen.findByText(/the same project is at C:\/PT\/TSTP-new/);

    await fireEvent.click(screen.getByRole("button", { name: "Relink" }));
    expect(paratextRelink).toHaveBeenCalledWith("C:/PT/TSTP-new");
    await waitFor(() => expect(screen.getByTestId("paratext-link-status")).toHaveTextContent("linked"));
  });

  it("relinks a missing folder to the one the reviewer picks, and shows a refusal", async () => {
    paratextLinkStatus.mockResolvedValue(status({ state: "folderMissing" }));
    pickFolder.mockResolvedValue("C:/elsewhere/TSTP");
    paratextRelink.mockRejectedValue(new Error("holds the Paratext project OTHER"));
    render(ParatextLinkStatus, { props: { projectKey: "a" } });
    await screen.findByText(/not found \(C:\/PT\/TSTP\)/);

    await fireEvent.click(screen.getByRole("button", { name: "Relink…" }));
    await waitFor(() => expect(paratextRelink).toHaveBeenCalledWith("C:/elsewhere/TSTP"));
    expect(await screen.findByRole("alert")).toHaveTextContent("holds the Paratext project OTHER");
  });

  it("does nothing when the folder picker is cancelled", async () => {
    paratextLinkStatus.mockResolvedValue(status({ state: "guidMismatch" }));
    pickFolder.mockResolvedValue(null);
    render(ParatextLinkStatus, { props: { projectKey: "a" } });
    await screen.findByText(/now holds a different Paratext project/);
    await fireEvent.click(screen.getByRole("button", { name: "Relink…" }));
    await waitFor(() => expect(pickFolder).toHaveBeenCalled());
    expect(paratextRelink).not.toHaveBeenCalled();
  });
});
