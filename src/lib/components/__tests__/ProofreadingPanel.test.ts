import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { get } from "svelte/store";

const api = vi.hoisted(() => ({
  proofreadingStatus: vi.fn(), proofreadingStart: vi.fn(), proofreadingPause: vi.fn(), proofreadingCancel: vi.fn(),
  proofreadingPreflight: vi.fn(), proofreadingSetReference: vi.fn(), proofreadingReport: vi.fn(),
  proofreadingRows: vi.fn(), proofreadingExport: vi.fn(), pickFolder: vi.fn(), pickSavePath: vi.fn(),
  openPath: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: api }));

import ProofreadingPanel from "../ProofreadingPanel.svelte";
import { proofreadingRunning, stopProofreading } from "../../proofreading";
import type {
  ProofreadingBook, ProofreadingPreflight, ProofreadingReport, ProofreadingRow, ProofreadingSnapshot,
} from "../../types/proofreading";

function book(bookId: string, overrides: Partial<ProofreadingBook> = {}): ProofreadingBook {
  return { bookId, bookName: bookId.toUpperCase(), path: `/p/${bookId}`, state: "pending", elapsedSeconds: null,
    findings: 0, bySeverity: {}, chunksDone: 0, chunksTotal: 0, usage: {}, error: null, note: null,
    completedAt: null, ...overrides };
}

function snapshot(overrides: Partial<ProofreadingSnapshot> = {}): ProofreadingSnapshot {
  return { jobId: "", state: "idle", paused: false, stage: "", halted: false, collectionPath: "/p/rut",
    reference: "", totalBooks: 3, completedBooks: 0, percent: 0, currentBook: null,
    books: [book("rut"), book("mat"), book("jhn")], findings: 0, usage: {}, elapsedSeconds: 0,
    estimatedRemainingSeconds: null, error: null, createdAt: null, finishedAt: null, ...overrides };
}

function preflight(overrides: Partial<ProofreadingPreflight> = {}): ProofreadingPreflight {
  const estimate = { requests: 3, inputTokens: 40000, outputTokens: 4000, cachedInputTokens: 0, estimatedCostUSD: 0.5 };
  return {
    aiReady: true, planUsage: false, model: "gpt-test", haltReason: "",
    reference: { path: "C:/bibles/esv", label: "esv", origin: "proofreading", kind: "usfm", files: "66", error: "" },
    language: { code: "ml", label: "Malayalam" },
    profile: { name: "Any language (generic profile)", code: "generic", status: "Generic" },
    toolkit: { name: "bible-qa-universal", fingerprint: "abc", pipeline: 1 }, paratextLinked: false,
    books: [
      { bookId: "rut", bookName: "Ruth", path: "/p/rut", supported: true, estimate, previous: null },
      { bookId: "mat", bookName: "Matthew", path: "/p/mat", supported: true, estimate,
        previous: { completedAt: "2026-11-24T10:00:00Z", findings: 4 } },
      { bookId: "jhn", bookName: "John", path: "/p/jhn", supported: true, estimate, previous: null },
    ],
    running: false, checkRunning: false, ...overrides,
  };
}

function finding(id: string, overrides: Partial<ProofreadingRow> = {}): ProofreadingRow {
  return { id, book: "RUT", chapter: "1", verse: "1", issueType: "Possible typo", category: "Typo",
    severity: "Low", confidence: "Medium", original: "ഒരു വാക്ക്", suggested: "", explanation: "Because.",
    referenceNote: "RUT 1:1", decisionNeeded: "No", location: "Verse text", anchor: "RUT 1:1", ...overrides };
}

const REPORT: ProofreadingReport = {
  books: [
    { bookId: "rut", bookName: "Ruth", state: "done", completedAt: "2026-11-25T08:00:00Z", findings: 3,
      bySeverity: { High: 1, Medium: 0, Low: 2 }, byIssueType: { "Possible typo": 2, "Source comparison": 1 },
      reference: "esv", model: "gpt-test", reported: 4, unplaced: 1, overlapping: 0, notes: [], hasReference: true },
    { bookId: "mat", bookName: "Matthew", state: "notRun" },
  ],
  booksRead: 1, totalBooks: 2, findings: 3, bySeverity: { High: 1, Medium: 0, Low: 2 },
  byIssueType: { "Possible typo": 2, "Source comparison": 1 },
  usage: { calls: 2, totalTokens: 2200, estimatedCostUSD: 0.12 },
  outputFolder: "C:/data/proofreading/out", files: { runReport: "C:/data/proofreading/out/QA_Run_Report.xlsx" },
  note: "Every row is a proposal. No Scripture was changed.",
};

const proofreadButton = () => screen.getByRole("button", { name: "Proofread" });
const startButton = () => screen.getByRole("button", { name: "Start" });

// #505: one control bar under Collection QA. Idle: the summary, a Proofread
// button that opens the start dialog and, once a book has been read, a report
// button. Active: progress with Pause and Cancel.
describe("ProofreadingPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.proofreadingStatus.mockResolvedValue(snapshot());
    api.proofreadingPreflight.mockResolvedValue(preflight());
    api.proofreadingReport.mockResolvedValue(REPORT);
    api.proofreadingRows.mockResolvedValue({ bookId: "rut", files: { workbook: "C:/out/RUT/RUT_QA_Report.xlsx" }, rows: [
      finding("a", { severity: "High", issueType: "Source comparison", original: "ആദ്യം", suggested: "ആദിയിൽ" }),
      finding("b", { verse: "2" }),
      finding("c", { chapter: "Intro", verse: "", location: "Introduction" }),
    ] });
  });
  afterEach(() => { stopProofreading(); });

  it("says it has never run and offers only Proofread", async () => {
    render(ProofreadingPanel, { props: { bookCount: 3, projectName: "IRV" } });
    const bar = await screen.findByRole("region", { name: "Proofreading" });
    await waitFor(() => expect(within(bar).getByText("never run")).toBeInTheDocument());
    expect(proofreadButton()).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Proofreading report" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(get(proofreadingRunning)).toBe(false);
  });

  it("summarises the books already read and offers their report", async () => {
    api.proofreadingStatus.mockResolvedValue(snapshot({ books: [
      book("rut", { state: "done", findings: 3, completedAt: "2026-11-25T08:00:00Z" }),
      book("mat", { state: "done", findings: 1200, completedAt: "2026-11-24T08:00:00Z" }), book("jhn"),
    ] }));
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    expect(await screen.findByText(/2 of 3 books proofread · 1,203 findings · last run /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Proofreading report" })).toBeEnabled();
  });

  it("shows what a run needs and costs, and starts every book", async () => {
    api.proofreadingStart.mockResolvedValue(snapshot({ jobId: "prj-1", state: "running", stage: "Preparing the text" }));
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    const dialog = await screen.findByRole("dialog", { name: "Proofread" });
    expect(await within(dialog).findByText(/gpt-test · your API key/)).toBeInTheDocument();
    expect(within(dialog).getByText("esv")).toBeInTheDocument();
    expect(within(dialog).getByText(/no reviewed rule profile for this language/)).toBeInTheDocument();
    // Three books at 3 requests, 44k tokens and $0.50 each, labelled as an estimate.
    expect(within(dialog).getByText("3 books")).toBeInTheDocument();
    expect(within(dialog).getByText("about 9 requests")).toBeInTheDocument();
    expect(within(dialog).getByText("~132k tokens")).toBeInTheDocument();
    expect(within(dialog).getByText("about $1.50")).toBeInTheDocument();
    expect(within(dialog).getByText(/estimate; 1 already read is skipped if unchanged/)).toBeInTheDocument();
    expect(within(dialog).getByText(/no Scripture is changed/)).toBeInTheDocument();
    expect(api.proofreadingStart).not.toHaveBeenCalled();  // nothing is sent by opening the dialog
    await fireEvent.click(startButton());
    await waitFor(() => expect(api.proofreadingStart).toHaveBeenCalledWith(null, false));
    await waitFor(() => expect(get(proofreadingRunning)).toBe(true));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("starts only the chosen part, and reads unchanged books again when asked", async () => {
    api.proofreadingStart.mockResolvedValue(snapshot({ jobId: "prj-1", state: "running" }));
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    const dialog = await screen.findByRole("dialog", { name: "Proofread" });
    await fireEvent.click(await within(dialog).findByRole("radio", { name: "New Testament" }));
    expect(within(dialog).getByText("2 books")).toBeInTheDocument();
    await fireEvent.click(within(dialog).getByRole("checkbox", { name: /Also read books unchanged/ }));
    expect(within(dialog).queryByText(/skipped if unchanged/)).toBeNull();
    await fireEvent.click(startButton());
    await waitFor(() => expect(api.proofreadingStart).toHaveBeenCalledWith(["mat", "jhn"], true));
  });

  it("lets single books be chosen, and will not start with none", async () => {
    api.proofreadingStart.mockResolvedValue(snapshot({ jobId: "prj-1", state: "running" }));
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    const dialog = await screen.findByRole("dialog", { name: "Proofread" });
    await fireEvent.click(await within(dialog).findByRole("radio", { name: "Choose books" }));
    expect(startButton()).toBeDisabled();
    expect(within(dialog).getByRole("status")).toHaveTextContent("Choose at least one book");
    await fireEvent.click(within(dialog).getByRole("checkbox", { name: /Ruth/ }));
    await fireEvent.click(startButton());
    await waitFor(() => expect(api.proofreadingStart).toHaveBeenCalledWith(["rut"], false));
  });

  it("will not start without a reference Bible, and takes one from a folder", async () => {
    api.proofreadingPreflight.mockResolvedValueOnce(preflight({
      reference: { path: "", label: "", origin: "none", kind: "", files: "0", error: "No reference Bible is chosen." } }));
    api.pickFolder.mockResolvedValue("C:/bibles/esv");
    api.proofreadingSetReference.mockResolvedValue(preflight().reference);
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    const dialog = await screen.findByRole("dialog", { name: "Proofread" });
    expect(await within(dialog).findByText("No reference Bible chosen")).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
    expect(within(dialog).getByRole("status")).toHaveTextContent("Choose a reference Bible");
    await fireEvent.click(within(dialog).getByRole("button", { name: "Choose folder" }));
    await waitFor(() => expect(api.proofreadingSetReference).toHaveBeenCalledWith("C:/bibles/esv"));
    expect(await within(dialog).findByText("esv")).toBeInTheDocument();
    await waitFor(() => expect(startButton()).toBeEnabled());
  });

  it("will not start without an AI provider, while another check runs, or past a plan limit", async () => {
    api.proofreadingPreflight.mockResolvedValueOnce(preflight({ aiReady: false }));
    const first = render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    expect(await screen.findByText(/Not set up\. Sign in or add a key/)).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
    first.unmount();

    const second = render(ProofreadingPanel, { props: { bookCount: 3, checkRunning: true } });
    await fireEvent.click(proofreadButton());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("A check is already running"));
    expect(startButton()).toBeDisabled();
    second.unmount();

    api.proofreadingPreflight.mockResolvedValueOnce(preflight({ planUsage: true, haltReason: "Your ChatGPT plan limit has been reached." }));
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    expect(await screen.findByText("Your ChatGPT plan limit has been reached.")).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
  });

  it("says a ChatGPT sign-in uses plan allowance, not dollars", async () => {
    api.proofreadingPreflight.mockResolvedValue(preflight({ planUsage: true }));
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    const dialog = await screen.findByRole("dialog", { name: "Proofread" });
    expect(await within(dialog).findByText(/gpt-test · your ChatGPT sign-in/)).toBeInTheDocument();
    expect(within(dialog).getByText("uses your ChatGPT plan allowance")).toBeInTheDocument();
    expect(within(dialog).queryByText(/about \$/)).toBeNull();
  });

  it("shows the book being read and what is being done, with Pause and Cancel", async () => {
    const running = snapshot({ jobId: "prj-1", state: "running", stage: "Reading chapters 4 to 6", completedBooks: 1,
      percent: 33, findings: 12, elapsedSeconds: 200, estimatedRemainingSeconds: 400,
      books: [book("rut", { state: "done", findings: 12 }), book("mat", { state: "running", bookName: "Matthew" }), book("jhn")] });
    api.proofreadingStatus.mockResolvedValue(running);
    api.proofreadingPause.mockResolvedValue({ ...running, paused: true });
    api.proofreadingCancel.mockResolvedValue({ ...running, state: "cancelling" });
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    expect(await screen.findByText(
      "Matthew: Reading chapters 4 to 6 · 1/3 books · 12 findings so far · 3 min 20 s elapsed · about 6 min 40 s left",
    )).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Proofread" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Pause after this book" }));
    await waitFor(() => expect(api.proofreadingPause).toHaveBeenCalledWith(true));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(api.proofreadingCancel).toHaveBeenCalled());
  });

  it("says why a run stopped at a plan limit and that the books read are kept", async () => {
    api.proofreadingStatus.mockResolvedValue(snapshot({ jobId: "prj-1", state: "failed", halted: true,
      error: "Your ChatGPT plan limit has been reached.", books: [book("rut", { state: "done", findings: 3 }), book("mat")] }));
    render(ProofreadingPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText(/Your ChatGPT plan limit has been reached\. The books already read are kept/)).toBeInTheDocument();
    expect(proofreadButton()).toBeEnabled();
  });

  it("opens the report: totals, the first book's findings, filters, export and the workbook", async () => {
    api.proofreadingStatus.mockResolvedValue(snapshot({ books: [book("rut", { state: "done", findings: 3 }), book("mat")] }));
    api.pickSavePath.mockResolvedValue("C:/out/findings.csv");
    api.proofreadingExport.mockResolvedValue({ written: true, path: "C:/out/findings.csv", rows: 3, format: "csv" });
    render(ProofreadingPanel, { props: { bookCount: 2, projectName: "IRV Malayalam" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Proofreading report" }));
    const dialog = await screen.findByRole("dialog", { name: "Proofreading report · IRV Malayalam" });
    expect(await within(dialog).findByText("Every row is a proposal. No Scripture was changed.")).toBeInTheDocument();
    expect(within(dialog).getByText(/2 requests · 2\.2k tokens · about \$0\.12 \(estimate\)/)).toBeInTheDocument();
    // The first book with findings is opened; a book not read is listed as such.
    await waitFor(() => expect(api.proofreadingRows).toHaveBeenCalledWith("rut"));
    expect(within(dialog).getByText("not read")).toBeInTheDocument();
    expect(await within(dialog).findByText("ആദ്യം")).toBeInTheDocument();
    expect(within(dialog).getByText("ആദിയിൽ")).toBeInTheDocument();
    expect(within(dialog).getByText(/The reader reported 4; 1 could not be found in the text/)).toBeInTheDocument();
    expect(within(dialog).getByText("3 of 3")).toBeInTheDocument();
    expect(within(dialog).getByText("Intro")).toBeInTheDocument();

    await fireEvent.change(within(dialog).getByRole("combobox", { name: "Severity" }), { target: { value: "High" } });
    expect(within(dialog).getByText("1 of 3")).toBeInTheDocument();
    expect(within(dialog).queryByText("Intro")).toBeNull();

    await fireEvent.click(within(dialog).getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(api.proofreadingExport).toHaveBeenCalledWith("C:/out/findings.csv", "csv", null));
    expect(api.pickSavePath).toHaveBeenCalledWith("IRV-Malayalam-proofreading.csv");
    expect(await within(dialog).findByText(/Exported 3 findings to C:\/out\/findings\.csv/)).toBeInTheDocument();
    await fireEvent.click(within(dialog).getByRole("button", { name: "Export this book" }));
    await waitFor(() => expect(api.proofreadingExport).toHaveBeenLastCalledWith("C:/out/findings.csv", "csv", ["rut"]));

    await fireEvent.click(within(dialog).getByRole("button", { name: "Open workbook" }));
    expect(api.openPath).toHaveBeenCalledWith("C:/out/RUT/RUT_QA_Report.xlsx");
    await fireEvent.click(within(dialog).getByRole("button", { name: "Excel report" }));
    expect(api.openPath).toHaveBeenLastCalledWith("C:/data/proofreading/out/QA_Run_Report.xlsx");

    await fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows nothing it cannot vouch for when the re-read after a new reference fails", async () => {
    // The reference was changed in the engine, then the re-read failed: the
    // old reference must not stay on screen with Start enabled.
    api.proofreadingPreflight
      .mockResolvedValueOnce(preflight())
      .mockRejectedValueOnce(new Error("The engine did not answer."))
      .mockResolvedValueOnce(preflight({
        reference: { path: "C:/bibles/niv", label: "niv", origin: "proofreading", kind: "usfm", files: "66", error: "" } }));
    api.pickFolder.mockResolvedValue("C:/bibles/niv");
    api.proofreadingSetReference.mockResolvedValue({});
    render(ProofreadingPanel, { props: { bookCount: 3 } });
    await fireEvent.click(proofreadButton());
    const dialog = await screen.findByRole("dialog", { name: "Proofread" });
    expect(await within(dialog).findByText("esv")).toBeInTheDocument();
    await fireEvent.click(within(dialog).getByRole("button", { name: "Change" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The engine did not answer.");
    expect(within(dialog).queryByText("esv")).toBeNull();
    expect(startButton()).toBeDisabled();
    await fireEvent.click(startButton());
    expect(api.proofreadingStart).not.toHaveBeenCalled();
    // A re-read that works shows what the engine now holds.
    await fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(await within(dialog).findByText("niv")).toBeInTheDocument();
    await waitFor(() => expect(startButton()).toBeEnabled());
  });
});
