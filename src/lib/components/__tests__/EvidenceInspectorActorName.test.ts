import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";

const { usersList } = vi.hoisted(() => ({ usersList: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: { usersList } }));

import EvidenceInspector from "../EvidenceInspector.svelte";
import { userNames } from "../../userNames";
import { staleConfirmed } from "./fixtures";
import type { QaFindingDetail } from "../../types/qaReview";

const KNOWN = "04592b9d-9d9b-4232-aac1-03b353afedd1";
const UNKNOWN = "9143bbc0-b361-4d9b-a51e-de0f59348478";

function withActor(actorId: string): QaFindingDetail {
  const base = staleConfirmed();
  return { ...base, history: base.history.map((row) => ({ ...row, actorId })) };
}

describe("EvidenceInspector history names the reviewer (#313)", () => {
  beforeEach(() => {
    userNames.set({});
    usersList.mockReset();
    usersList.mockResolvedValue({
      currentUserId: KNOWN,
      users: [{
        userId: KNOWN, displayName: "Benz", role: "reviewer", active: true,
        createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z", current: true,
      }],
    });
  });

  it("shows a known actor id as the user's name, the id kept as its tooltip", async () => {
    const { container } = render(EvidenceInspector, { props: { detail: withActor(KNOWN) } });
    await waitFor(() => expect(container.querySelector(".history .actor")).toHaveTextContent("Benz"));
    expect(container.querySelector(".history .actor")).toHaveAttribute("title", KNOWN);
    expect(usersList).toHaveBeenCalled();
  });

  it("shows an id this device does not know as the id", async () => {
    const { container } = render(EvidenceInspector, { props: { detail: withActor(UNKNOWN) } });
    await waitFor(() => expect(usersList).toHaveBeenCalled());
    expect(container.querySelector(".history .actor")).toHaveTextContent(UNKNOWN);
  });

  it("keeps legacy:human and the id when the users list cannot be read", async () => {
    usersList.mockRejectedValue(new Error("engine down"));
    const { container, unmount } = render(EvidenceInspector, { props: { detail: withActor("human") } });
    await waitFor(() => expect(usersList).toHaveBeenCalled());
    expect(container.querySelector(".history .actor")).toHaveTextContent("legacy:human");
    unmount();
    render(EvidenceInspector, { props: { detail: withActor(KNOWN) } });
    await waitFor(() => expect(screen.getByText(KNOWN)).toBeInTheDocument());
  });
});
