import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import ProjectDashboard from "../ProjectDashboard.svelte";
import { collectionQa, stopCollectionQa } from "../../collectionQa";
import { checkingProgress } from "../../stores";
import type { ExceptionQueueRow, ProjectReport } from "../../types/finding";
import type { CollectionQaSnapshot } from "../../types/collectionQa";

const books = [{
  path: "/projects/rut",
  bookId: "rut",
  bookName: "Ruth",
  missing: false,
  lazy: false,
  progress: {
    chapterCount: 4,
    checkedChapterCount: 2,
    verseCount: 85,
    reviewedVerseCount: 10,
    alignedVerseCount: 7,
    alignedKnownVerseCount: 40,
    languageQaCheckedVerseCount: 40,
    languageQaCleanVerseCount: 31,
    updatedAt: "",
  },
}] as never;

function row(overrides: Partial<ExceptionQueueRow> = {}): ExceptionQueueRow {
  return {
    chapter: "1", verse: "1", critical: 0, high: 0, medium: 0,
    cache: "missing", wordAlignment: "valid", invalidChecks: 0, discussions: 0,
    finalState: "", summary: "",
    localFindings: [], helpsFindings: [],
    ...overrides,
  };
}

function report(rows: ExceptionQueueRow[]): ProjectReport {
  return {
    project: "Ruth", bookId: "rut",
    exceptionQueue: rows,
    qaSeverityCounts: {},
    needsDiscussion: [],
    publicationGate: {
      readyForHumanPublicationSignoff: true, criticalFindings: 0,
      highFindings: 0, staleAIReviews: 0, openDiscussions: 0,
    } as never,
    coverage: {
      verses: {
        counts: { PASS: 1, ISSUE: 0, REVIEW_REQUIRED: 0, NOT_CHECKED: 0 },
        totalVerses: 1, checkedPercent: 100,
      } as never,
      resources: {},
    },
  };
}

function mount(rows: ExceptionQueueRow[] = []) {
  return render(ProjectDashboard, {
    props: {
      projectName: "Ruth", books, loading: false, error: "",
      onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: report(rows), reportLoading: false, reportError: "",
    },
  });
}

describe("ProjectDashboard", () => {
  it("keeps a checked book's four meters behind the Progress toggle", async () => {
    mount();
    expect(screen.queryByText(/chapters checked/)).toBeNull();
    expect(screen.queryByText("Checked 2/4 chapters")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Show progress of Ruth" }));
    expect(screen.getByText("Checked 2/4 chapters")).toBeInTheDocument();
    expect(screen.getByText("Reviewed 10/85")).toBeInTheDocument();
    expect(screen.getByText("Aligned 7/40")).toBeInTheDocument();
    expect(screen.getByText("Language QA clean 31/40")).toBeInTheDocument();
  });

  // Third pass (2026-10-30): a row is not clickable. Its first icon is the
  // book's QA state -- View QA report once something has checked it, Run QA
  // before -- then Assign and Open.
  it("offers View QA report on a checked book, which previews and never runs a check", async () => {
    const onRunBookQa = vi.fn();
    const onPreviewBook = vi.fn();
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books, loading: false, error: "", onSelectBook: () => {}, onPreviewBook, onRetry: () => {},
      report: null, reportLoading: false, reportError: "", onRunBookQa,
    } });
    expect(screen.getByRole("button", { name: "Open" }).classList.contains("ui-icon-btn")).toBe(true);
    expect(screen.queryByRole("button", { name: "Assign…" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run QA" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open" }).closest(".book-row")?.getAttribute("role")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "View QA report" }));
    expect(onPreviewBook).toHaveBeenCalledWith("/projects/rut");
    expect(onRunBookQa).not.toHaveBeenCalled();
  });

  const checkedBook = (books as unknown as { progress: Record<string, unknown> }[])[0];
  const unchecked = [{ ...checkedBook, progress: { ...checkedBook.progress, checkedChapterCount: 0 } }] as never;

  it("offers Run QA on a book nothing has checked", async () => {
    const onRunBookQa = vi.fn();
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books: unchecked, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: null, reportLoading: false, reportError: "", onRunBookQa,
    } });
    expect(screen.queryByRole("button", { name: "View QA report" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Run QA" }));
    expect(onRunBookQa).toHaveBeenCalledWith("/projects/rut");
  });

  it("disables Run QA while a job runs", () => {
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books: unchecked, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: null, reportLoading: false, reportError: "", qaBusy: true,
    } });
    expect(screen.getByRole("button", { name: "Run QA" })).toBeDisabled();
  });

  it("offers Run QA, not a report, on a never-opened book, and says so in the report card", async () => {
    const onRunBookQa = vi.fn();
    const lazy = [{ path: "/projects/gen", bookId: "gen", bookName: "Genesis", missing: false, lazy: true, progress: null }] as never;
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books: lazy, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: null, reportLoading: false, reportError: "", openBookName: "Genesis", openBookPath: "/projects/gen", onRunBookQa,
    } });
    expect(screen.getByText("Not yet opened")).toBeInTheDocument();
    expect(screen.getByText("Genesis has not been checked yet.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Run QA on Genesis" }));
    expect(onRunBookQa).toHaveBeenCalledWith("/projects/gen");
    await fireEvent.click(screen.getByRole("button", { name: "Run QA" }));
    expect(onRunBookQa).toHaveBeenCalledTimes(2);
  });

  it("shows the dashboard's own check job in the report card, with Cancel, and spins the row", async () => {
    const onCancelQa = vi.fn();
    checkingProgress.set({ running: true, percent: 40, label: "tN · tW · 2:3", jobId: "j1", state: "running", error: "", scope: "book" });
    try {
      render(ProjectDashboard, { props: {
        projectName: "Ruth", books, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
        report: report([]), reportLoading: false, reportError: "", qaBusy: true, qaRunningPath: "/projects/rut", onCancelQa,
      } });
      expect(screen.getByText("Checking Ruth…")).toBeInTheDocument();
      expect(screen.getByText("tN · tW · 2:3 · 40%")).toBeInTheDocument();
      expect(screen.queryByText("Verses needing attention")).toBeNull();
      expect(screen.getByRole("status", { name: "Checking Ruth" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "View QA report" })).toBeNull();
      await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      expect(onCancelQa).toHaveBeenCalledTimes(1);
    } finally {
      checkingProgress.set({ running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter" });
    }
  });

  it("shows a book being opened in the report card, not the old report", () => {
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: report([]), reportLoading: false, reportError: "", qaBusy: true, openingPath: "/projects/rut", openingDetail: "preparing chapter 2 of 4",
    } });
    expect(screen.getByText("Opening Ruth…")).toBeInTheDocument();
    expect(screen.getByText("preparing chapter 2 of 4")).toBeInTheDocument();
    expect(screen.queryByText("Verses needing attention")).toBeNull();
    expect(screen.getByRole("status", { name: "Opening Ruth" })).toBeInTheDocument();
  });

  it("keeps a failed dashboard job on the card with Run QA again", async () => {
    const onRunBookQa = vi.fn();
    checkingProgress.set({ running: false, percent: 40, label: "", jobId: "j1", state: "failed", error: "sidecar died", scope: "book" });
    try {
      render(ProjectDashboard, { props: {
        projectName: "Ruth", books, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
        report: null, reportLoading: false, reportError: "", qaRunningPath: "/projects/rut", onRunBookQa,
      } });
      expect(screen.getByText("sidecar died")).toBeInTheDocument();
      await fireEvent.click(screen.getByRole("button", { name: "Run QA again" }));
      expect(onRunBookQa).toHaveBeenCalledWith("/projects/rut");
    } finally {
      checkingProgress.set({ running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter" });
    }
  });

  it("shows when the report was built, with Rebuild and Run QA again as icons", async () => {
    const onLoadReport = vi.fn();
    const onRunBookQa = vi.fn();
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: report([]), reportLoading: false, reportError: "", reportBuiltAt: "2026-10-29T08:03:00Z", onLoadReport, onRunBookQa,
      openBookPath: "/projects/rut",
    } });
    expect(screen.getByText(/^built /)).toBeInTheDocument();
    const rebuild = screen.getByRole("button", { name: "Rebuild" });
    expect(rebuild.classList.contains("ui-icon-btn")).toBe(true);
    await fireEvent.click(rebuild);
    expect(onLoadReport).toHaveBeenCalledTimes(1);
    await fireEvent.click(screen.getByRole("button", { name: "Run QA again" }));
    expect(onRunBookQa).toHaveBeenCalledWith("/projects/rut");
  });

  it("filters the queue by chapter from a dropdown, and clears it", async () => {
    mount([
      row({ chapter: "1", verse: "1", critical: 1 }),
      row({ chapter: "2", verse: "1", high: 1 }),
      row({ chapter: "2", verse: "5", high: 1 }),
    ]);
    expect(screen.getAllByText(/RUT \d:\d/)).toHaveLength(3);
    await fireEvent.click(screen.getByRole("button", { name: "All chapters" }));
    await fireEvent.click(screen.getByRole("option", { name: "2" }));
    expect(screen.getAllByText(/RUT \d:\d/)).toHaveLength(2);
    expect(screen.queryByText("RUT 1:1")).toBeNull();
    expect(screen.getByRole("button", { name: "Chapter 2" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "critical 1" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Clear chapter filter" }));
    expect(screen.getAllByText(/RUT \d:\d/)).toHaveLength(3);
  });

  it("filters the queue by what a row carries and pages the filtered list", async () => {
    mount([
      row({ chapter: "1", verse: "1", critical: 2 }),
      row({ chapter: "1", verse: "2", high: 1 }),
      row({ chapter: "1", verse: "3", high: 1, discussions: 1 }),
    ]);
    expect(screen.getByText("Verses needing attention").nextElementSibling).toHaveTextContent("3");
    await fireEvent.click(screen.getByRole("button", { name: "high 2" }));
    expect(screen.getAllByText(/RUT 1:\d/)).toHaveLength(2);
    expect(screen.queryByText("RUT 1:1")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "high 2" }));
    expect(screen.getAllByText(/RUT 1:\d/)).toHaveLength(3);
  });

  it("shows the open counts as tiles", () => {
    const base = report([]);
    base.publicationGate = { ...base.publicationGate, readyForHumanPublicationSignoff: false, checkHighFindings: 18705, openDiscussions: 2 } as never;
    render(ProjectDashboard, { props: {
      projectName: "Ruth", books, loading: false, error: "", onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: base, reportLoading: false, reportError: "",
    } });
    expect(screen.getByText("18.7k")).toBeInTheDocument();
    expect(screen.getByText("Check findings")).toBeInTheDocument();
    expect(screen.getByText("Discussions")).toBeInTheDocument();
  });

  // The Collection QA table is gone (dashboard restyle, 2026-10-28): each
  // book's last result sits on its own row, from the same store the bar reads.
  it("shows a book's last Collection QA result on its row", () => {
    const snapshot: CollectionQaSnapshot = {
      jobId: "", state: "idle", paused: false, collectionPath: "/projects", checks: [], totalBooks: 1, completedBooks: 0,
      percent: 0, currentBook: null, finalStage: null, elapsedSeconds: 0, estimatedRemainingSeconds: null,
      error: null, createdAt: null, finishedAt: null,
      books: [{ bookId: "rut", bookName: "Ruth", path: "/projects/rut", state: "done", elapsedSeconds: 40, jobId: null,
        findingsByCategory: { languageQa: 3, alignment: 1 }, checkedVerses: 85, error: null, completedAt: "2026-09-24T10:00:00Z" }],
    };
    collectionQa.set(snapshot);
    try {
      mount();
      expect(screen.getByRole("button", { name: "Open" }).closest(".book-row")).toHaveTextContent(/QA done · 4 findings/);
    } finally {
      stopCollectionQa();
    }
  });

  it("labels the checked-chapters bar without the AI prefix", async () => {
    mount();
    await fireEvent.click(screen.getByRole("button", { name: "Show progress of Ruth" }));
    expect(screen.getByText("Checked 2/4 chapters")).toBeInTheDocument();
    expect(screen.queryByText(/AI-checked/)).not.toBeInTheDocument();
  });

  it("counts tN and tW problems on the verse row", () => {
    mount([row({
      helpsFindings: [
        {
          tool: "translationNotes", category: "translation_note", severity: "medium",
          checkType: "TC_PENDING", groupId: "figs-metaphor",
          explanation: "Review the figure of speech.",
        },
        {
          tool: "translationWords", category: "translation_word", severity: "high",
          checkType: "TC_INVALIDATED", groupId: "faith",
          explanation: "faith / tw-1 is invalidated.",
        },
      ],
    })]);
    expect(screen.getByText("1 tN")).toBeInTheDocument();
    expect(screen.getByText("1 tW")).toBeInTheDocument();
  });

  it("expands Greek Room and tN/tW findings together, colour-keyed by source", async () => {
    mount([row({
      localFindings: [{
        engine: "wildebeest", severity: "high", checkType: "wildebeest.script.mixed",
        explanation: "Mixed script in token.",
      }],
      helpsFindings: [{
        tool: "translationNotes", category: "translation_note", severity: "medium",
        checkType: "TC_PENDING", groupId: "figs-metaphor",
        explanation: "Review the figure of speech.",
      }],
    })]);

    await fireEvent.click(screen.getByRole("button", { name: /2 finding/ }));

    const greekRoom = screen.getByText("Mixed script in token.").closest(".local-finding-row");
    const note = screen.getByText("Review the figure of speech.").closest(".local-finding-row");
    expect(greekRoom?.className).toContain("source-gr");
    expect(note?.className).toContain("source-tn");
  });

  it("offers no expander when a row has nothing to detail", () => {
    mount([row({ high: 1 })]);
    expect(screen.queryByRole("button", { name: /finding/ })).not.toBeInTheDocument();
  });

  describe("the exception queue is pageable, not a dead count (#144)", () => {
    const many = (n: number) =>
      Array.from({ length: n }, (_, i) => row({ chapter: "1", verse: String(i + 1), high: 1 }));

    it("caps the first page and says how much is hidden", () => {
      mount(many(60));
      expect(screen.getByText("showing 25 of 60")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Show 25 more" })).toBeInTheDocument();
    });

    it("reveals the next page on click, and the last page asks for only what is left", async () => {
      mount(many(60));

      await fireEvent.click(screen.getByRole("button", { name: "Show 25 more" }));
      expect(screen.getByText("showing 50 of 60")).toBeInTheDocument();

      // 10 left, not another 25 — the label must not promise rows that do not exist.
      await fireEvent.click(screen.getByRole("button", { name: "Show 10 more" }));
      expect(screen.queryByText(/showing \d+ of 60/)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Show \d+ more/ })).not.toBeInTheDocument();
    });

    it("offers no control when everything already fits", () => {
      mount(many(25));
      expect(screen.queryByRole("button", { name: /Show \d+ more/ })).not.toBeInTheDocument();
      expect(screen.queryByText(/showing/)).not.toBeInTheDocument();
    });
  });

  describe("the report is asked for, not built on open", () => {
    function mountWithoutReport(props: Record<string, unknown> = {}) {
      const onLoadReport = vi.fn();
      const utils = render(ProjectDashboard, {
        props: {
          projectName: "Hindi IRV", books, loading: false, error: "",
          onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
          report: null, reportLoading: false, reportError: "",
          openBookName: "Genesis", onLoadReport,
          ...props,
        },
      });
      return { ...utils, onLoadReport };
    }

    it("explains the row icons instead of building a report nobody asked for", () => {
      const { onLoadReport } = mountWithoutReport();
      expect(onLoadReport).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: /Build the QA report/ })).not.toBeInTheDocument();
      expect(screen.getByText("Pick a book on the left to see its QA report.")).toBeInTheDocument();
      expect(screen.getByRole("list", { name: "What the book icons do" })).toHaveTextContent(/Run QA.*View QA report.*Open/);
      expect(screen.getByText(/takes a couple of minutes/)).toBeInTheDocument();
    });

    it("counts the build against its estimate while it builds, and says it is one", () => {
      mountWithoutReport({ reportLoading: true, reportEstimateSeconds: 90 });
      expect(screen.getByText("Building the QA report for Genesis…")).toBeInTheDocument();
      expect(screen.getByText("0 s elapsed · about 1 min 30 s left")).toBeInTheDocument();
      expect(screen.getByText(/an estimate from the book's length \(about 1 min 30 s in all\)/)).toBeInTheDocument();
      expect(screen.getByText(/the rest of the app waits for it/)).toBeInTheDocument();
    });

    it("lets a failed report be retried rather than stranding the panel", async () => {
      const { onLoadReport } = mountWithoutReport({
        reportError: "sidecar request 'project.report' timed out",
      });
      expect(screen.getByText(/timed out/)).toBeInTheDocument();

      await fireEvent.click(screen.getByRole("button", { name: "Try again" }));

      expect(onLoadReport).toHaveBeenCalledTimes(1);
    });
  });

  // #322 asked that a key on a row's button never also preview the row; the
  // row is no longer clickable at all (2026-10-30), so only the buttons act.
  describe("keyboard on a book row (#322)", () => {
    function mountRow(canAssign = false) {
      const onSelectBook = vi.fn();
      const onPreviewBook = vi.fn();
      const onAssign = vi.fn();
      render(ProjectDashboard, {
        props: {
          projectName: "Ruth", books, loading: false, error: "",
          onSelectBook, onPreviewBook, onRetry: () => {},
          report: null, reportLoading: false, reportError: "",
          canAssign, onAssign,
        },
      });
      return { onSelectBook, onPreviewBook, onAssign };
    }

    // jsdom does not turn Enter on a button into a click, so do what a browser
    // does: click only if the keydown was not cancelled on its way up.
    async function pressEnter(button: HTMLElement) {
      button.focus();
      const notCancelled = await fireEvent.keyDown(button, { key: "Enter" });
      if (notCancelled) await fireEvent.click(button);
      return notCancelled;
    }

    it("Enter on Open opens the book, not a preview", async () => {
      const { onSelectBook, onPreviewBook } = mountRow();
      expect(await pressEnter(screen.getByRole("button", { name: "Open" }))).toBe(true);
      expect(onSelectBook).toHaveBeenCalledWith("/projects/rut");
      expect(onPreviewBook).not.toHaveBeenCalled();
    });

    it("Enter on Assign… assigns, not a preview", async () => {
      const { onAssign, onPreviewBook } = mountRow(true);
      expect(await pressEnter(screen.getByRole("button", { name: "Assign…" }))).toBe(true);
      expect(onAssign).toHaveBeenCalledWith("/projects/rut");
      expect(onPreviewBook).not.toHaveBeenCalled();
    });

    it("a click or key on the row itself does nothing", async () => {
      const { onSelectBook, onPreviewBook } = mountRow();
      const bookRow = screen.getByRole("button", { name: "Open" }).closest(".book-row") as HTMLElement;
      await fireEvent.click(bookRow);
      await fireEvent.keyDown(bookRow, { key: "Enter" });
      expect(onPreviewBook).not.toHaveBeenCalled();
      expect(onSelectBook).not.toHaveBeenCalled();
    });
  });
});

// #337: the advisory gate's three states. A tick only when every verse is
// checked and nothing blocking is open; unchecked verses are counted, never
// folded into "no blocking issues"; an open high check finding blocks.
describe("ProjectDashboard publication gate (#337)", () => {
  function mountGate(gate: Partial<ProjectReport["publicationGate"]>, notChecked = 0) {
    const base = report([]);
    base.publicationGate = { ...base.publicationGate, ...gate };
    base.coverage.verses = {
      counts: { PASS: 3 - notChecked, ISSUE: 0, REVIEW_REQUIRED: 0, NOT_CHECKED: notChecked },
      totalVerses: 3, checkedPercent: Math.round((100 * (3 - notChecked)) / 3),
    } as never;
    return render(ProjectDashboard, {
      props: {
        projectName: "Ruth", books, loading: false, error: "",
        onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
        report: base, reportLoading: false, reportError: "",
      },
    });
  }

  it("reads 'Not checked (n of m verses)' while any verse is unchecked, even with nothing open", () => {
    mountGate({ readyForHumanPublicationSignoff: false, status: "not_checked", uncheckedVerses: 3, totalVerses: 3 }, 3);
    expect(screen.getByText(/Not checked \(3 of 3 verses\) in RUT/)).toBeInTheDocument();
    expect(screen.queryByText(/No blocking issues/)).not.toBeInTheDocument();
    expect(screen.queryByText(/✓/)).not.toBeInTheDocument();
  });

  it("blocks on an open high check finding from any engine, with the count in the line", () => {
    mountGate({ readyForHumanPublicationSignoff: false, status: "blocked", uncheckedVerses: 0, totalVerses: 3,
                checkCriticalFindings: 0, checkHighFindings: 2 });
    expect(screen.getByText(/2 high\/critical check finding\(s\)/)).toBeInTheDocument();
    expect(screen.queryByText(/✓/)).not.toBeInTheDocument();
  });

  it("ticks only when every verse is checked and nothing blocking is open", () => {
    mountGate({ readyForHumanPublicationSignoff: true, status: "ready", uncheckedVerses: 0, totalVerses: 3 });
    expect(screen.getByText(/✓ Every verse checked, no blocking issues open in RUT/)).toBeInTheDocument();
  });
});
