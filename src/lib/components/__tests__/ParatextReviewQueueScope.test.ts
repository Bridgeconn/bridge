// #429 / #431 / #432 / #434 / #435: the review queue across books, the
// regions Bridge keeps no copy of, reconciliation and the reports list.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const {
  paratextReviewQueue, paratextReviewPreview, paratextReviewDecide, paratextReviewSaveState,
  paratextReviewRevertLatest, paratextReviewExportCsv, paratextReviewReport, paratextReviewLatestReport,
  paratextResolveThread, pickSavePath, paratextReviewReports, paratextReviewReconcile, paratextFlushOutbox,
  paratextSetReference, openPath,
} = vi.hoisted(() => ({
  paratextReviewQueue: vi.fn(), paratextReviewPreview: vi.fn(), paratextReviewDecide: vi.fn(),
  paratextReviewSaveState: vi.fn(), paratextReviewRevertLatest: vi.fn(), paratextReviewExportCsv: vi.fn(),
  paratextReviewReport: vi.fn(), paratextReviewLatestReport: vi.fn(), paratextResolveThread: vi.fn(),
  pickSavePath: vi.fn(), paratextReviewReports: vi.fn(), paratextReviewReconcile: vi.fn(), paratextFlushOutbox: vi.fn(),
  paratextSetReference: vi.fn(), openPath: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    paratextReviewQueue, paratextReviewPreview, paratextReviewDecide, paratextReviewSaveState,
    paratextReviewRevertLatest, paratextReviewExportCsv, paratextReviewReport, paratextReviewLatestReport,
    paratextResolveThread, pickSavePath, paratextReviewReports, paratextReviewReconcile, paratextFlushOutbox,
    paratextSetReference, openPath,
  },
}));
const { askConfirmation } = vi.hoisted(() => ({ askConfirmation: vi.fn() }));
vi.mock("../../confirmAction", () => ({ askConfirmation }));

import ParatextReviewQueue from "../ParatextReviewQueue.svelte";
import { project } from "../../stores";
import type { ParatextProposal, ParatextReviewItem, ParatextReviewQueue as Queue, ParatextReviewReports } from "../../types/paratext";

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
    openBook: true, wrapped: false, ...overrides,
  };
}

function queue(items: ParatextReviewItem[], overrides: Partial<Queue> = {}): Queue {
  const counts = { total: items.length, undecided: items.filter((i) => !i.decision).length,
    applied: 0, rejected: 0, manual: 0, deferred: 0, reverted: 0 };
  return {
    indexState: "ready", status: "unresolved", book: "TIT", items, counts,
    state: { status: "unresolved", scope: { books: ["TIT"], startBook: "TIT" }, position: "", drafts: {},
      sessionStartedAt: "2026-11-02T00:00:00Z" },
    presets: [{ id: "accepted", label: "Accepted", text: "Accepted as suggested." }],
    reviewer: "Joel", bridgeUser: { userId: "u1", displayName: "Joel" },
    books: [{ book: "TIT", bookId: "tit", path: "C:/p/tit", lazy: false, open: true },
            { book: "PHM", bookId: "phm", path: "C:/p/phm", lazy: true, open: false }],
    scanned: [{ book: "TIT", threads: items.length, unreadable: 0, proposals: items.length }],
    booksInScope: ["TIT"], wraparound: { occurs: false, books: [], count: 0 }, staleDraftsDropped: [],
    uncertain: [], pendingResolves: [], ...overrides,
  };
}

const okPreview = { proposalId: "p1", region: "body" as const, plain: "alpha beta gamma", found: 1, ok: true, reason: "",
  after: "alpha BETA gamma", span: { plainStart: 6, plainEnd: 10 }, matches: [], paratextOnly: false };
const okReports: ParatextReviewReports = { reports: [], interrupted: [], folder: "C:/p", pendingResolves: [], uncertain: [] };

describe("ParatextReviewQueue scope, regions and recovery (#429, #431, #432, #434)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "C:/p/tit", bookId: "tit", bookName: "Titus", targetLanguage: "Tamil", tcVersion: "", chapters: ["1"], checkTypes: {} });
    paratextReviewSaveState.mockImplementation(async (state) => ({ state: { status: "unresolved", scope: { books: ["TIT"], startBook: "TIT" }, position: "", drafts: {}, sessionStartedAt: "x", ...state } }));
    paratextReviewPreview.mockResolvedValue(okPreview);
    paratextReviewReports.mockResolvedValue(okReports);
    askConfirmation.mockResolvedValue(true);
  });
  afterEach(() => project.set(null));

  it("the Books picker scans several books from a starting book and says where the queue wraps around", async () => {
    const tit = item();
    const phm = item({ proposalId: "p2", threadId: "T2", book: "PHM", verseRef: "PHM 1:1", openBook: false,
      proposal: proposal({ proposalId: "p2", original: "PHM", suggested: "Philemon" }) });
    paratextReviewQueue
      .mockResolvedValueOnce(queue([tit]))
      .mockResolvedValueOnce(queue([phm, { ...tit, wrapped: true }], {
        booksInScope: ["TIT", "PHM"], wraparound: { occurs: true, books: ["TIT"], count: 1 },
        state: { status: "unresolved", scope: { books: ["TIT", "PHM"], startBook: "PHM" }, position: "", drafts: {}, sessionStartedAt: "x" },
      }));
    const onNavigate = vi.fn().mockResolvedValue(undefined);
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate });
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("button", { name: "Apply and next" });

    await fireEvent.click(within(dialog).getByRole("button", { name: "Books…" }));
    await fireEvent.click(within(dialog).getByLabelText(/PHM \(not opened yet\)/));
    await fireEvent.change(within(dialog).getByLabelText("Start at"), { target: { value: "PHM" } });
    await fireEvent.click(within(dialog).getByRole("button", { name: "Apply scope" }));
    await waitFor(() => expect(paratextReviewQueue).toHaveBeenLastCalledWith("unresolved", { books: ["TIT", "PHM"], startBook: "PHM" }));
    expect(await within(dialog).findByText(/After PHM the queue wraps around to TIT/)).toBeTruthy();

    // The PHM proposal is read-only until its book is open; Apply stays off and "Open PHM" navigates.
    await waitFor(() => expect(within(dialog).getByText(/This proposal is in PHM, which is not open/)).toBeTruthy());
    expect((within(dialog).getByRole("button", { name: "Apply and next" }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(within(dialog).getByRole("button", { name: "Open PHM" }));
    expect(onNavigate).toHaveBeenCalledWith("PHM", "1", "1");
    expect(paratextReviewPreview).not.toHaveBeenCalledWith("p2", expect.anything());
  });

  it("an introduction correction needs 'Also write to Paratext' and is sent with it; Show in Paratext moves the scroll group", async () => {
    const intro = item({ proposal: proposal({ region: "introduction", original: "says beta", suggested: "says BETA" }) });
    paratextReviewQueue.mockResolvedValue(queue([intro]));
    paratextReviewPreview.mockResolvedValue({ ...okPreview, region: "introduction", ok: false, paratextOnly: true, span: null,
      plain: "says beta", after: "says BETA", reason: "Bridge keeps no copy of the book introduction; tick \"Also write to Paratext\"." });
    paratextReviewDecide.mockResolvedValue({ decision: { decision: "applied", verified: true, verseRef: "TIT 1:1",
      paratext: { status: "sent", verified: true, lastError: "" } }, item: { ...intro, thread: { complete: true, blocking: [] } } });
    paratextSetReference.mockRejectedValue(new Error("The active Paratext window is not in a scroll/sync group."));
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    const apply = await within(dialog).findByRole("button", { name: "Apply and next" }) as HTMLButtonElement;
    await waitFor(() => expect(within(dialog).getByText(/in Paratext only/)).toBeTruthy());
    expect(apply.disabled).toBe(true);
    await fireEvent.click(within(dialog).getByLabelText(/Also write to Paratext \(required/));
    // The preview reports ok=false for a Paratext-only region; the engine locates it there.
    paratextReviewPreview.mockResolvedValue({ ...okPreview, region: "introduction", ok: true, paratextOnly: true, span: null, plain: "says beta", after: "says BETA" });
    await fireEvent.change(within(dialog).getByLabelText(/Replacement/), { target: { value: "says BETA" } });
    await waitFor(() => expect((within(dialog).getByRole("button", { name: "Apply and next" }) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(within(dialog).getByRole("button", { name: "Apply and next" }));
    await waitFor(() => expect(paratextReviewDecide).toHaveBeenCalledWith("p1", "applied",
      { comment: "", replacement: "says BETA", confirmDelete: false, writeParatext: true }));
    expect(await within(dialog).findByText(/Written to Paratext and read back/)).toBeTruthy();

    await fireEvent.click(within(dialog).getByRole("button", { name: "Show in Paratext" }));
    await waitFor(() => expect(paratextSetReference).toHaveBeenCalledWith("TIT 1:1"));
    expect(await within(dialog).findByText(/not in a scroll\/sync group/)).toBeTruthy();
  });

  it("the Reports tab reconciles an interrupted apply, retries a saved resolve and opens a saved report in the browser", async () => {
    const applied = item({ decision: { decision: "applied", verified: false, proposalId: "p1", verseRef: "TIT 1:1" } as never });
    paratextReviewQueue.mockResolvedValue(queue([applied], { uncertain: ["p1"] }));
    paratextReviewReports.mockResolvedValue({
      folder: "C:/p", interrupted: ["report-1.html.tmp"],
      reports: [{ path: "C:/p/report-2.html", name: "report-2.html", size: 10, modifiedAt: "2026-11-02T10:00:00Z" }],
      pendingResolves: [{ messageId: "m1", threadId: "T9", status: "queued", attempts: 2, lastError: "Paratext is offline", createdAt: "", reference: "TIT 1:2" }],
      uncertain: [{ decision: applied.decision!, classified: "verified", observed: "alpha BETA gamma", paratextPending: "" }],
    });
    paratextReviewReconcile.mockResolvedValue({ decision: { ...applied.decision, verified: true }, classified: "verified" });
    paratextFlushOutbox.mockResolvedValue({});
    paratextReviewLatestReport.mockResolvedValue({ path: "C:/p/report-2.html", html: "<p>r2</p>" });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    await fireEvent.click(await within(dialog).findByRole("tab", { name: /Reports \/ recovery/ }));

    expect(await within(dialog).findByText(/1 interrupted report generation was cleared/)).toBeTruthy();
    expect(within(dialog).getByText(/the text now reads as the apply intended/)).toBeTruthy();
    await fireEvent.click(within(dialog).getByRole("button", { name: "Mark verified" }));
    await waitFor(() => expect(paratextReviewReconcile).toHaveBeenCalledWith("p1", "verified"));
    await waitFor(() => expect(within(dialog).getByText("Marked verified from the current text.")).toBeTruthy());

    expect(within(dialog).getByText(/TIT 1:2 · queued · Paratext is offline/)).toBeTruthy();
    await waitFor(() => expect((within(dialog).getByRole("button", { name: "Retry sending" }) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(within(dialog).getByRole("button", { name: "Retry sending" }));
    await waitFor(() => expect(paratextFlushOutbox).toHaveBeenCalledTimes(1));

    const openButtons = within(dialog).getAllByRole("button", { name: "Open in browser" });
    await fireEvent.click(openButtons[0]);
    await waitFor(() => expect(openPath).toHaveBeenCalledWith("C:/p/report-2.html"));
    await fireEvent.click(within(dialog).getByRole("button", { name: "View" }));
    await waitFor(() => expect(paratextReviewLatestReport).toHaveBeenCalledWith("C:/p/report-2.html"));
    expect(dialog.querySelector("iframe")?.getAttribute("srcdoc")).toBe("<p>r2</p>");
  });

  it("Alt+A applies from the keyboard and Save report as… asks for a destination", async () => {
    const one = item();
    paratextReviewQueue.mockResolvedValue(queue([one]));
    paratextReviewDecide.mockResolvedValue({ decision: { decision: "applied", verified: true, verseRef: "TIT 1:1" },
      item: { ...one, decision: { decision: "applied", verified: true } as never, thread: { complete: true, blocking: [] } } });
    pickSavePath.mockResolvedValue("D:/out/report-x.html");
    paratextReviewReport.mockResolvedValue({ written: true, path: "D:/out/report-x.html", html: "<p>x</p>", count: 1 });
    render(ParatextReviewQueue, { onClose: vi.fn(), onNavigate: null });
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("button", { name: "Apply and next" });
    await waitFor(() => expect((within(dialog).getByRole("button", { name: "Apply and next" }) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.keyDown(window, { key: "a", altKey: true });
    await waitFor(() => expect(paratextReviewDecide).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(dialog).getByText("Applied and verified.")).toBeTruthy());

    await fireEvent.click(within(dialog).getByRole("tab", { name: /Reports \/ recovery/ }));
    await fireEvent.click(await within(dialog).findByRole("button", { name: "Save report as…" }));
    await waitFor(() => expect(paratextReviewReport).toHaveBeenCalledWith({ cumulative: false, outputPath: "D:/out/report-x.html" }));
    expect(await within(dialog).findByText(/D:\/out\/report-x\.html/)).toBeTruthy();
  });
});
