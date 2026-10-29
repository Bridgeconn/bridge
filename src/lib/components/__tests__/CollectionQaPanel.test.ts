import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { collectionQaStatus, collectionRunChecks, collectionPauseChecks, collectionCancelChecks } = vi.hoisted(() => ({
  collectionQaStatus: vi.fn(),
  collectionRunChecks: vi.fn(),
  collectionPauseChecks: vi.fn(),
  collectionCancelChecks: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { collectionQaStatus, collectionRunChecks, collectionPauseChecks, collectionCancelChecks },
}));

import CollectionQaPanel from "../CollectionQaPanel.svelte";
import { collectionQaRunning, stopCollectionQa } from "../../collectionQa";
import type { CollectionQaBook, CollectionQaSnapshot } from "../../types/collectionQa";

function book(bookId: string, overrides: Partial<CollectionQaBook> = {}): CollectionQaBook {
  return { bookId, bookName: bookId.toUpperCase(), path: `/p/${bookId}`, state: "pending", elapsedSeconds: null,
    jobId: null, findingsByCategory: {}, checkedVerses: 0, error: null, completedAt: null, ...overrides };
}

function snapshot(overrides: Partial<CollectionQaSnapshot> = {}): CollectionQaSnapshot {
  return { jobId: "", state: "idle", paused: false, collectionPath: "/p/rut", checks: [], totalBooks: 2,
    completedBooks: 0, percent: 0, currentBook: null, books: [book("rut"), book("gen")], finalStage: null,
    elapsedSeconds: 0, estimatedRemainingSeconds: null, error: null, createdAt: null, finishedAt: null,
    ...overrides };
}

// The dashboard restyle (2026-10-28) made this one control bar: the summary,
// a Checks menu and Run idle; progress with Pause and Cancel while a run is
// active. Each book's result is drawn on its dashboard row, not here.
describe("CollectionQaPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    collectionQaStatus.mockResolvedValue(snapshot({
      books: [book("rut", { state: "done", completedAt: "2026-09-24T10:00:00Z", checkedVerses: 85,
        findingsByCategory: { languageQa: 3 } }), book("gen")],
    }));
  });
  afterEach(() => {
    stopCollectionQa();
  });

  it("is one bar: the last runs' summary, the Checks menu and the Run buttons, no table", async () => {
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText(/1 done · last run/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("button", { name: "Run QA on all 2 books" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run all again" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^Checks/ })).toHaveAttribute("aria-expanded", "false");
    expect(collectionRunChecks).not.toHaveBeenCalled();
  });

  it("opens the checks as a menu and keeps at least one ticked", async () => {
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await screen.findByText(/1 done/);
    await fireEvent.click(screen.getByRole("button", { name: /^Checks/ }));
    const menu = screen.getByRole("group", { name: "Checks to run" });
    expect(menu).toBeInTheDocument();
    expect(screen.getByLabelText("Greek Room")).toBeChecked();
    expect(screen.getByText(/meant to be left alone/)).toBeInTheDocument();
  });

  it("says never run when no book has a recorded run", async () => {
    collectionQaStatus.mockResolvedValue(snapshot());
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText("never run")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run all again" })).toBeNull();
  });

  it("shows the running book, the progress bar, Pause and Cancel while a run is active", async () => {
    collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "running", currentBook: "rut", percent: 40,
      completedBooks: 0, elapsedSeconds: 12, estimatedRemainingSeconds: 30,
      books: [book("rut", { state: "running" }), book("gen")] }));
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByRole("button", { name: "Pause after this book" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Collection QA" })).toHaveTextContent(/Checking RUT · 0\/2 books · 12 s elapsed · about 30 s left/);
    expect(screen.getByRole("button", { name: "Pause after this book" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Run QA/ })).toBeNull();
  });

  it("starts a run, holds the app read-only while it runs, and releases it when it ends", async () => {
    collectionRunChecks.mockResolvedValue(snapshot({ jobId: "j1", state: "running", currentBook: "rut",
      books: [book("rut", { state: "running" }), book("gen")] }));
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await fireEvent.click(await screen.findByRole("button", { name: "Run QA on all 2 books" }));
    expect(collectionRunChecks).toHaveBeenCalledWith(["tN", "tW", "alignment", "text", "languageQa", "greekroom"], false);
    await waitFor(() => expect(get(collectionQaRunning)).toBe(true));
    expect(screen.getByRole("button", { name: "Pause after this book" })).toBeInTheDocument();
    collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "succeeded",
      books: [book("rut", { state: "done", completedAt: "2026-09-24T10:00:00Z" }), book("gen", { state: "skipped" })] }));
    await waitFor(() => expect(get(collectionQaRunning)).toBe(false), { timeout: 3000 });
    expect(await screen.findByText(/1 done · 1 unchanged · last run/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run QA on all 2 books" })).toBeEnabled();
  });

  it("folds the whole-collection stage under the bar once it has run", async () => {
    collectionQaStatus.mockResolvedValue(snapshot({
      books: [book("rut", { state: "done", completedAt: "2026-09-24T10:00:00Z" }), book("gen", { state: "done", completedAt: "2026-09-24T10:05:00Z" })],
      finalStage: { completedAt: "2026-09-24T10:06:00Z", termbaseCoverage: [{ bookId: "rut", concepts: 4, issues: [1, 2] }],
        crossBookNames: { available: true, findings: [1] }, houseStylePropagation: { available: false, reason: "no house style" } },
    }));
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText(/Whole-collection checks/)).toBeInTheDocument();
    expect(screen.getByText(/2 concept issue\(s\) across 1 book\(s\)/)).toBeInTheDocument();
  });
});
