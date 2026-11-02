import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const {
  paratextReviewQueue, paratextReviewPreview, paratextReviewDecide, paratextReviewSaveState,
  paratextReviewRevertLatest, paratextReviewExportCsv, paratextReviewReport, paratextReviewLatestReport,
  paratextResolveThread, pickSavePath,
} = vi.hoisted(() => ({
  paratextReviewQueue: vi.fn(), paratextReviewPreview: vi.fn(), paratextReviewDecide: vi.fn(),
  paratextReviewSaveState: vi.fn(), paratextReviewRevertLatest: vi.fn(), paratextReviewExportCsv: vi.fn(),
  paratextReviewReport: vi.fn(), paratextReviewLatestReport: vi.fn(), paratextResolveThread: vi.fn(),
  pickSavePath: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    paratextReviewQueue, paratextReviewPreview, paratextReviewDecide, paratextReviewSaveState,
    paratextReviewRevertLatest, paratextReviewExportCsv, paratextReviewReport, paratextReviewLatestReport,
    paratextResolveThread, pickSavePath,
  },
}));
const { askConfirmation } = vi.hoisted(() => ({ askConfirmation: vi.fn() }));
vi.mock("../../confirmAction", () => ({ askConfirmation }));

import ParatextReviewQueue from "../ParatextReviewQueue.svelte";
import type { ParatextProposal, ParatextReviewItem, ParatextReviewQueue as Queue } from "../../types/paratext";

function proposal(overrides: Partial<ParatextProposal> = {}): ParatextProposal {
  return {
    proposalId: "p1", commentIndex: 0, block: 0, route: "literal", operation: "replace", region: "body",
    pass: "R2", topic: "Sandhi", category: "Sandhi / word-joining", categoryKnown: true,
    original: "beta", suggested: "BETA", reason: "The words join.", location: "", reference: "",
    severity: "low", confidence: "0.93", reviewerDecision: false, anchorWarning: false, historical: false,
    outstanding: true, alternatives: [], structural: null, diagnostics: [], author: "QA", date: "2026-10-20",
    ...overrides,
  };
}

function item(overrides: Partial<ParatextReviewItem> = {}): ParatextReviewItem {
  return {
    proposalId: "p1", threadId: "T1", book: "TIT", chapter: "1", verse: "1", verseRef: "TIT 1:1",
    threadResolved: false, selectedText: "", contextBefore: "", contextAfter: "", proposal: proposal(),
    threadOutstanding: 1, decision: null, draft: null, thread: { complete: false, blocking: ["p1: undecided"] },
    ...overrides,
  };
}

function queue(items: ParatextReviewItem[], overrides: Partial<Queue> = {}): Queue {
  const counts = { total: items.length, undecided: items.filter((i) => !i.decision).length,
    applied: 0, rejected: 0, manual: 0, deferred: 0, reverted: 0 };
  return {
    indexState: "ready", status: "unresolved", book: "TIT", items, counts,
    state: { status: "unresolved", position: "", drafts: {}, sessionStartedAt: "2026-11-02T00:00:00Z" },
    presets: [
      { id: "accepted", label: "Accepted", text: "Accepted as suggested." },
      { id: "retained", label: "Existing wording retained", text: "The existing wording is retained." },
    ],
    reviewer: "Joel", ...overrides,
  };
}

const okPreview = { proposalId: "p1", plain: "alpha beta gamma", found: 1, ok: true, reason: "",
  after: "alpha BETA gamma", span: { plainStart: 6, plainEnd: 10 }, matches: [] };

describe("ParatextReviewQueue (#428, #432, #433, #434)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    paratextReviewSaveState.mockImplementation(async (state) => ({ state: { status: "unresolved", position: "", drafts: {}, sessionStartedAt: "x", ...state } }));
    paratextReviewPreview.mockResolvedValue(okPreview);
    askConfirmation.mockResolvedValue(true);
  });
  afterEach(() => vi.useRealTimers());

  it("shows the first undecided proposal with its source fields, the located span and the after text", async () => {
    paratextReviewQueue.mockResolvedValue(queue([
      item({ proposalId: "p0", decision: { decision: "rejected" } as never }),
      item(),
    ]));
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });

    const dialog = await screen.findByRole("dialog", { name: "Paratext review queue" });
    await waitFor(() => expect(within(dialog).getByText("Literal correction")).toBeTruthy());
    expect(within(dialog).getByText("The words join.")).toBeTruthy();
    await waitFor(() => expect(within(dialog).getByText("alpha BETA gamma")).toBeTruthy());
    expect(dialog.querySelector("mark")?.textContent).toBe("beta");
    expect(within(dialog).getByText(/2 of 2/)).toBeTruthy();
    const apply = within(dialog).getByRole("button", { name: "Apply and next" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);
    expect((within(dialog).getByLabelText(/Replacement/) as HTMLInputElement).value).toBe("BETA");
  });

  it("Apply and next sends the replacement and comment, then moves on; a preset only fills the comment", async () => {
    const second = item({ proposalId: "p2", threadId: "T2", verseRef: "TIT 1:2", proposal: proposal({ proposalId: "p2", original: "gamma", suggested: "GAMMA" }) });
    const first = item();
    paratextReviewQueue
      .mockResolvedValueOnce(queue([first, second]))
      .mockResolvedValue(queue([{ ...first, decision: { decision: "applied", verified: true, replacement: "BETA", comment: "Accepted as suggested.", decidedAt: "2026-11-02T01:00:00Z" } as never }, second]));
    paratextReviewDecide.mockResolvedValue({ decision: { decision: "applied", verified: true, verseRef: "TIT 1:1" },
      item: { ...first, decision: { decision: "applied", verified: true } as never, thread: { complete: true, blocking: [] } } });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Apply and next" })).toBeTruthy());

    await fireEvent.click(within(dialog).getByRole("button", { name: "Accepted" }));
    expect((within(dialog).getByLabelText("Comment") as HTMLTextAreaElement).value).toBe("Accepted as suggested.");
    expect(paratextReviewDecide).not.toHaveBeenCalled();

    await fireEvent.click(within(dialog).getByRole("button", { name: "Apply and next" }));
    await waitFor(() => expect(paratextReviewDecide).toHaveBeenCalledWith("p1", "applied",
      { comment: "Accepted as suggested.", replacement: "BETA", confirmDelete: false, writeParatext: false }));
    await waitFor(() => expect(within(dialog).getByText("Applied and verified.")).toBeTruthy());
    await waitFor(() => expect(within(dialog).getByText("TIT 1:2", { selector: "strong" })).toBeTruthy());
    expect(askConfirmation).not.toHaveBeenCalled();
  });

  it("Reject needs a comment, a deletion asks first, and an unlocatable Original disables Apply", async () => {
    const deletion = item({ proposal: proposal({ operation: "delete", suggested: "(delete)", category: "Addition not in source", route: "review" }) });
    paratextReviewQueue.mockResolvedValue(queue([deletion]));
    paratextReviewDecide.mockResolvedValue({ decision: { decision: "rejected" }, item: deletion });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    const reject = await within(dialog).findByRole("button", { name: "Reject and next" });

    await fireEvent.click(reject);
    expect(within(dialog).getByText("Say why in the comment first.")).toBeTruthy();
    expect(paratextReviewDecide).not.toHaveBeenCalled();

    askConfirmation.mockResolvedValueOnce(false);
    await fireEvent.click(within(dialog).getByRole("button", { name: "Delete and next" }));
    await waitFor(() => expect(askConfirmation).toHaveBeenCalledTimes(1));
    expect(askConfirmation.mock.calls[0][0].title).toContain("Delete “beta” from TIT 1:1?");
    expect(paratextReviewDecide).not.toHaveBeenCalled();
  });

  it("an Original the engine cannot locate once disables Apply and shows the reason", async () => {
    paratextReviewQueue.mockResolvedValue(queue([item()]));
    paratextReviewPreview.mockResolvedValue({ ...okPreview, ok: false, span: null, after: "", reason: "The exact Original was not found in this verse." });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("The exact Original was not found in this verse.")).toBeTruthy());
    expect((within(dialog).getByRole("button", { name: "Apply and next" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("offers Resolve in Paratext only once the thread is complete, through the outbox", async () => {
    const done = item({ decision: { decision: "manual", comment: "ok", decidedAt: "2026-11-02T01:00:00Z" } as never,
      thread: { complete: true, blocking: [] } });
    paratextReviewQueue.mockResolvedValue(queue([done]));
    paratextResolveThread.mockResolvedValue({ item: { status: "queued", lastError: "Paratext is offline" } });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    const resolve = await within(dialog).findByRole("button", { name: "Resolve thread in Paratext" });
    await fireEvent.click(resolve);
    await waitFor(() => expect(paratextResolveThread).toHaveBeenCalledWith("T1", "note", "T1"));
    expect(await within(dialog).findByText(/Resolve queued for Paratext\. Paratext is offline/)).toBeTruthy();
  });

  it("the Reports tab saves a session report, shows the latest one, exports CSV through a save dialog and reverts with confirmation", async () => {
    paratextReviewQueue.mockResolvedValue(queue([item({ decision: { decision: "applied", verified: false, unverifiedReason: "read-back differed" } as never })]));
    paratextReviewReport.mockResolvedValue({ written: true, path: "C:/p/report-1.html", html: "<p>report</p>", count: 1 });
    paratextReviewLatestReport.mockResolvedValue({ path: "C:/p/report-1.html", html: "<p>report</p>" });
    pickSavePath.mockResolvedValue("C:/out/decisions.csv");
    paratextReviewExportCsv.mockResolvedValue({ written: true, path: "C:/out/decisions.csv", count: 3 });
    paratextReviewRevertLatest.mockResolvedValue({ decision: { verseRef: "TIT 1:1", revertVerified: true } });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    await fireEvent.click(await within(dialog).findByRole("tab", { name: /Reports \/ recovery/ }));

    expect(within(dialog).getByText(/applied but not verified/)).toBeTruthy();
    await fireEvent.click(within(dialog).getByRole("button", { name: "Save session report" }));
    await waitFor(() => expect(within(dialog).getByText(/C:\/p\/report-1\.html/)).toBeTruthy());
    expect(dialog.querySelector("iframe")?.getAttribute("srcdoc")).toBe("<p>report</p>");

    await fireEvent.click(within(dialog).getByRole("button", { name: "Export decisions as CSV…" }));
    await waitFor(() => expect(paratextReviewExportCsv).toHaveBeenCalledWith("C:/out/decisions.csv"));
    expect(await within(dialog).findByText(/Wrote 3 decisions/)).toBeTruthy();

    await fireEvent.click(within(dialog).getByRole("button", { name: "Revert latest verified correction…" }));
    await waitFor(() => expect(paratextReviewRevertLatest).toHaveBeenCalledTimes(1));
    expect(askConfirmation).toHaveBeenCalledTimes(1);
    expect(await within(dialog).findByText("Reverted TIT 1:1 and verified.")).toBeTruthy();
  });

  it("keeps the draft when moving between proposals and saves it with the position", async () => {
    const a = item();
    const b = item({ proposalId: "p2", threadId: "T2", verseRef: "TIT 1:2", proposal: proposal({ proposalId: "p2", original: "gamma", suggested: "GAMMA" }) });
    paratextReviewQueue.mockResolvedValue(queue([a, b]));
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("button", { name: "Apply and next" });
    await fireEvent.input(within(dialog).getByLabelText("Comment"), { target: { value: "thinking" } });
    await fireEvent.click(within(dialog).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(paratextReviewSaveState).toHaveBeenCalledWith({ drafts: { p1: { replacement: "BETA", comment: "thinking" } } }));
    await waitFor(() => expect(paratextReviewSaveState).toHaveBeenCalledWith({ position: "p2" }));
    expect(paratextReviewDecide).not.toHaveBeenCalled();
  });
});
