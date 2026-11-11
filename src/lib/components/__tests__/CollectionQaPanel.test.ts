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
import { collectionChecks } from "../../editorPrefs";
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

// The dashboard restyle (2026-10-28) made this one control bar; #490 made its
// idle side one Check button that opens a dialog (the checks, the re-check
// option, the read-only note, Start and Cancel). Progress with Pause and
// Cancel while a run is active. Each book's result is drawn on its dashboard
// row, not here.
const ALL = ["tN", "tW", "alignment", "text", "languageQa", "greekroom"];
const checkButton = () => screen.getByRole("button", { name: "Check" });
const startButton = () => screen.getByRole("button", { name: "Start" });

describe("CollectionQaPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    collectionChecks.set([...ALL]);
    collectionQaStatus.mockResolvedValue(snapshot({
      books: [book("rut", { state: "done", completedAt: "2026-09-24T10:00:00Z", checkedVerses: 85,
        findingsByCategory: { languageQa: 3 } }), book("gen")],
    }));
  });
  afterEach(() => {
    stopCollectionQa();
  });

  it("is one bar: the last runs' summary and one Check button, no dropdown, no table", async () => {
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText(/1 of 2 books checked · last run/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(checkButton()).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^Checks/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Run QA on all/ })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(collectionRunChecks).not.toHaveBeenCalled();
  });

  it("Check opens a dialog with the current selection, the re-check option and the read-only note", async () => {
    collectionChecks.set(["alignment", "languageQa"]);
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await screen.findByText(/1 of 2 books checked/);
    await fireEvent.click(checkButton());
    const dialog = screen.getByRole("dialog", { name: "Check all 2 books" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Checks to run" })).toBeInTheDocument();
    expect(screen.getByLabelText("Alignment")).toBeChecked();
    expect(screen.getByLabelText("Language QA")).toBeChecked();
    expect(screen.getByLabelText("Greek Room")).not.toBeChecked();
    expect(screen.getByLabelText("Also re-check books unchanged since their last run")).not.toBeChecked();
    expect(screen.getByText(/meant to be left alone/)).toBeInTheDocument();
    expect(startButton()).toBeEnabled();
    expect(collectionRunChecks).not.toHaveBeenCalled();
  });

  it("Start runs with the ticked checks, saves them and closes the dialog", async () => {
    collectionRunChecks.mockResolvedValue(snapshot());
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await screen.findByText(/1 of 2 books checked/);
    await fireEvent.click(checkButton());
    await fireEvent.click(screen.getByLabelText("Greek Room"));
    await fireEvent.click(screen.getByLabelText("Translation Words"));
    await fireEvent.click(screen.getByLabelText("Also re-check books unchanged since their last run"));
    await fireEvent.click(startButton());
    expect(collectionRunChecks).toHaveBeenCalledWith(["tN", "alignment", "text", "languageQa"], true);
    expect(get(collectionChecks)).toEqual(["tN", "alignment", "text", "languageQa"]);
    expect(JSON.parse(localStorage.getItem("bridge.dashboard.collectionChecks.v1") ?? "[]")).toEqual(["tN", "alignment", "text", "languageQa"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Cancel and Escape close the dialog without starting or saving, and focus returns to Check", async () => {
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await screen.findByText(/1 of 2 books checked/);
    checkButton().focus();
    await fireEvent.click(checkButton());
    await fireEvent.click(screen.getByLabelText("Greek Room"));
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(get(collectionChecks)).toEqual(ALL);
    expect(document.activeElement).toBe(checkButton());
    await fireEvent.click(checkButton());
    expect(screen.getByLabelText("Greek Room")).toBeChecked();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(collectionRunChecks).not.toHaveBeenCalled();
  });

  it("disables Start with no check ticked", async () => {
    collectionChecks.set(["languageQa"]);
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await screen.findByText(/1 of 2 books checked/);
    await fireEvent.click(checkButton());
    await fireEvent.click(screen.getByLabelText("Language QA"));
    expect(startButton()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Tick at least one check");
    await fireEvent.click(startButton());
    expect(collectionRunChecks).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByLabelText("Alignment"));
    expect(startButton()).toBeEnabled();
  });

  it("disables Start while another check is running", async () => {
    render(CollectionQaPanel, { props: { bookCount: 2, checkRunning: true } });
    await screen.findByText(/1 of 2 books checked/);
    await fireEvent.click(checkButton());
    expect(startButton()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("A check is already running");
  });

  it("says never run when no book has a recorded run", async () => {
    collectionQaStatus.mockResolvedValue(snapshot());
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText("never run")).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: "Check" })).toBeNull();
  });

  it("starts a run, holds the app read-only while it runs, and releases it when it ends", async () => {
    collectionRunChecks.mockResolvedValue(snapshot({ jobId: "j1", state: "running", currentBook: "rut",
      books: [book("rut", { state: "running" }), book("gen")] }));
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await fireEvent.click(await screen.findByRole("button", { name: "Check" }));
    await fireEvent.click(startButton());
    expect(collectionRunChecks).toHaveBeenCalledWith(ALL, false);
    await waitFor(() => expect(get(collectionQaRunning)).toBe(true));
    expect(screen.getByRole("button", { name: "Pause after this book" })).toBeInTheDocument();
    collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "succeeded",
      books: [book("rut", { state: "done", completedAt: "2026-09-24T10:00:00Z" }), book("gen", { state: "skipped" })] }));
    await waitFor(() => expect(get(collectionQaRunning)).toBe(false), { timeout: 3000 });
    expect(await screen.findByText(/2 of 2 books checked · last run/)).toBeInTheDocument();
    expect(checkButton()).toBeEnabled();
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
