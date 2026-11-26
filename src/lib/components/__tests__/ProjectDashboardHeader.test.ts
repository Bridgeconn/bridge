import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/svelte";

const { paratextLinkStatus, collectionQaStatus, proofreadingStatus } = vi.hoisted(() => ({
  paratextLinkStatus: vi.fn(), collectionQaStatus: vi.fn(), proofreadingStatus: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { paratextLinkStatus, paratextRelink: vi.fn(), paratextRefresh: vi.fn(), pickFolder: vi.fn(), collectionQaStatus,
    proofreadingStatus },
}));

import ProjectDashboard from "../ProjectDashboard.svelte";
import { stopCollectionQa } from "../../collectionQa";
import { stopProofreading } from "../../proofreading";
import type { BookProgressEntry, ProjectReport } from "../../types/finding";

function book(bookId: string, bookName: string): BookProgressEntry {
  return { path: `/projects/${bookId}`, bookId, bookName, missing: false, lazy: true, progress: null };
}

const report = {
  project: "Ruth", bookId: "rut", exceptionQueue: [], qaSeverityCounts: {}, needsDiscussion: [],
  publicationGate: { readyForHumanPublicationSignoff: true, criticalFindings: 0, highFindings: 0, staleAIReviews: 0, openDiscussions: 0 },
  coverage: { verses: { counts: { PASS: 1, ISSUE: 0, REVIEW_REQUIRED: 0, NOT_CHECKED: 0 }, totalVerses: 1, checkedPercent: 100 }, resources: {} },
} as unknown as ProjectReport;

function mount(books: BookProgressEntry[]) {
  return render(ProjectDashboard, {
    props: {
      projectName: "IRV Tamil", subtitle: "Tamil · 66 books", books, loading: false, error: "",
      onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report, reportLoading: false, reportError: "", openBookName: "ரூத்",
    },
  });
}

// The dashboard restyle (2026-10-28): one header card carries the name, the
// language and book count as chips, the Paratext link as a chip, and the
// Collection QA bar for a collection. The old fold (#374) is gone with the
// second row it folded.
describe("ProjectDashboard header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    paratextLinkStatus.mockResolvedValue({
      state: "linked", folder: "C:/PT/TSTP", guid: "abc", name: "TSTP", fullName: "Synthetic", versification: "eng",
      encoding: "65001", booksPresent: ["RUT"], linkedAt: "",
      files: { notes: { count: 2, users: [] }, bookNames: true, commentTags: false, userAccess: false,
        termRenderings: false, errorDenials: false, spellingStatus: false, checkingStatus: false, progress: false },
      notesIndex: { state: "ready", threads: 5, builtAt: "", buildSeconds: 0, source: "files", error: "" },
    });
    proofreadingStatus.mockResolvedValue({ jobId: "", state: "idle", paused: false, stage: "", halted: false,
      collectionPath: "", reference: "", totalBooks: 2, completedBooks: 0, percent: 0, currentBook: null, books: [],
      findings: 0, usage: {}, elapsedSeconds: 0, estimatedRemainingSeconds: null, error: null, createdAt: null,
      finishedAt: null });
    collectionQaStatus.mockResolvedValue({ jobId: "", state: "idle", paused: false, collectionPath: "", checks: [],
      totalBooks: 2, completedBooks: 0, percent: 0, currentBook: null, books: [], finalStage: null,
      elapsedSeconds: 0, estimatedRemainingSeconds: null, error: null, createdAt: null, finishedAt: null });
  });

  it("names the project once, with its language and book count as chips, and the Paratext link beside them", async () => {
    mount([book("rut", "ரூத்")]);
    expect(screen.getByRole("heading", { level: 1, name: "IRV Tamil" })).toBeInTheDocument();
    expect(screen.getByText("Tamil")).toBeInTheDocument();
    expect(screen.getByText("66 books")).toBeInTheDocument();
    const paratext = await screen.findByTestId("paratext-link-status");
    expect(within(paratext).getByText(/Paratext · TSTP · linked/)).toBeInTheDocument();
    expect(within(paratext).getByText("2 notes files · 5 note threads")).toBeInTheDocument();
    expect(within(paratext).getByRole("button", { name: "Refresh" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /project details/ })).toBeNull();
    expect(screen.queryByText("PROJECT")).toBeNull();
  });

  it("offers Relink when the Paratext folder has moved", async () => {
    paratextLinkStatus.mockResolvedValue({ state: "folderMoved", folder: "C:/old", candidate: "C:/new", name: "TSTP", guid: "abc",
      files: { notes: { count: 0, users: [] } }, notesIndex: null });
    mount([book("rut", "ரூத்")]);
    const paratext = await screen.findByTestId("paratext-link-status");
    expect(within(paratext).getByText(/folder moved/)).toBeInTheDocument();
    expect(within(paratext).getByRole("button", { name: "Relink" })).toBeEnabled();
    expect(within(paratext).getByRole("button", { name: "Choose folder…" })).toBeEnabled();
  });

  // 2026-11-26 (Joel): a project of one book has both bars too; the engine
  // runs the open book alone. No bar before the book list has loaded.
  it("hosts both bars for a single book, and neither before the books are listed", async () => {
    const empty = mount([]);
    expect(screen.queryByRole("region", { name: "Collection QA" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Proofreading" })).toBeNull();
    empty.unmount();

    mount([book("rut", "ரூத்")]);
    const collectionBar = await screen.findByRole("region", { name: "Collection QA" });
    const bar = await screen.findByRole("region", { name: "Proofreading" });
    expect(collectionBar.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(collectionBar).getByRole("button", { name: "Check" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Proofread" })).toBeInTheDocument();
    stopCollectionQa();
    stopProofreading();
  });

  it("hosts the Collection QA bar for a collection", async () => {
    mount([book("rut", "ரூத்"), book("gen", "ஆதியாகமம்")]);
    const bar = await screen.findByRole("region", { name: "Collection QA" });
    expect(within(bar).getByRole("button", { name: "Check" })).toBeInTheDocument();
    expect(within(bar).queryByRole("button", { name: /^Checks/ })).toBeNull();
    expect(screen.getByRole("main", { name: "QA report" })).toBeInTheDocument();
    stopCollectionQa();
  });

  // #505: the proofreading run has its own bar, straight under Collection QA.
  it("hosts the Proofreading bar under Collection QA for a collection", async () => {
    mount([book("rut", "ரூத்"), book("gen", "ஆதியாகமம்")]);
    const collectionBar = await screen.findByRole("region", { name: "Collection QA" });
    const bar = await screen.findByRole("region", { name: "Proofreading" });
    expect(collectionBar.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(bar).getByRole("button", { name: "Proofread" })).toBeInTheDocument();
    // Nothing has been read yet, so there is no report to open.
    expect(within(bar).queryByRole("button", { name: "Proofreading report" })).toBeNull();
    expect(await within(bar).findByText("never run")).toBeInTheDocument();
    stopCollectionQa();
    stopProofreading();
  });

  it("names the previewed book in the report card's heading", () => {
    mount([book("rut", "ரூத்")]);
    expect(screen.getByRole("heading", { level: 2, name: "QA Report" })).toBeInTheDocument();
    expect(screen.getByTitle("ரூத்")).toBeInTheDocument();
  });
});
