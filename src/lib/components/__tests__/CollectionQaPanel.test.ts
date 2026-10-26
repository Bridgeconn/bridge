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
import { collectionQaCollapsed } from "../../editorPrefs";
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
    collectionQaCollapsed.set(false);
  });

  // #380: folded by default. The store is made when the module loads, so the
  // default is read from a fresh copy of the module against an empty storage,
  // and a saved choice from one against storage that holds it.
  describe("starts folded unless the device remembered otherwise (#380)", () => {
    const KEY = "bridge.dashboard.collectionQaCollapsed.v1";
    async function freshStore() {
      vi.resetModules();
      const prefs = await import("../../editorPrefs");
      return get(prefs.collectionQaCollapsed);
    }

    it("defaults to folded on a fresh profile", async () => {
      localStorage.removeItem(KEY);
      expect(await freshStore()).toBe(true);
    });

    it("keeps a saved open choice", async () => {
      localStorage.setItem(KEY, "false");
      expect(await freshStore()).toBe(false);
    });

    it("shows the slim folded row with the summary and the Run button, no table", async () => {
      collectionQaCollapsed.set(true);
      render(CollectionQaPanel, { props: { bookCount: 2 } });
      expect(await screen.findByText(/2 books · 1 done · last run/)).toBeInTheDocument();
      expect(screen.queryByRole("table")).toBeNull();
      expect(screen.getByRole("region", { name: "Collection QA" }).classList.contains("folded")).toBe(true);
      expect(screen.getByRole("button", { name: "Run QA on all 2 books" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Run all again" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Expand Collection QA" }).getAttribute("aria-expanded")).toBe("false");
    });

    it("refolds after a run only if it was folded before", async () => {
      collectionQaCollapsed.set(true);
      collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "running", currentBook: "rut",
        books: [book("rut", { state: "running" }), book("gen")] }));
      render(CollectionQaPanel, { props: { bookCount: 2 } });
      expect(await screen.findByRole("table")).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Collection QA" }).classList.contains("folded")).toBe(false);
      collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "succeeded",
        books: [book("rut", { state: "done" }), book("gen", { state: "skipped" })] }));
      await waitFor(() => expect(get(collectionQaRunning)).toBe(false), { timeout: 3000 });
      await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
      expect(get(collectionQaCollapsed)).toBe(true);
    });
  });

  it("folds to its header, remembers it, and still offers a run", async () => {
    collectionQaCollapsed.set(false);
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await screen.findByText("languageQa 3");
    await fireEvent.click(screen.getByRole("button", { name: "Collapse Collection QA" }));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(/2 books · 1 done · last run/)).toBeInTheDocument();
    expect(localStorage.getItem("bridge.dashboard.collectionQaCollapsed.v1")).toBe("true");
    expect(screen.getByRole("button", { name: "Run QA on all 2 books" })).toBeEnabled();
    await fireEvent.click(screen.getByRole("button", { name: "Expand Collection QA" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("opens itself while a run is in progress, whatever was chosen", async () => {
    collectionQaCollapsed.set(true);
    collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "running", currentBook: "rut",
      books: [book("rut", { state: "running" }), book("gen")] }));
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse Collection QA" })).toBeDisabled();
  });

  it("shows each book's last recorded run and offers a run, never starting one itself", async () => {
    collectionQaCollapsed.set(false);
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    expect(await screen.findByText("languageQa 3")).toBeInTheDocument();
    expect(screen.getByText("85")).toBeInTheDocument();
    expect(collectionRunChecks).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Run QA on all 2 books" })).toBeEnabled();
  });

  it("starts a run, holds the app read-only while it runs, and releases it when it ends", async () => {
    collectionQaCollapsed.set(false);
    collectionRunChecks.mockResolvedValue(snapshot({ jobId: "j1", state: "running", currentBook: "rut",
      books: [book("rut", { state: "running" }), book("gen")] }));
    render(CollectionQaPanel, { props: { bookCount: 2 } });
    await fireEvent.click(await screen.findByRole("button", { name: "Run QA on all 2 books" }));
    expect(collectionRunChecks).toHaveBeenCalledWith(["tN", "tW", "alignment", "text", "languageQa", "greekroom"], false);
    await waitFor(() => expect(get(collectionQaRunning)).toBe(true));
    expect(screen.getByRole("button", { name: "Pause after this book" })).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: "Open book" })) expect(button).toBeDisabled();
    collectionQaStatus.mockResolvedValue(snapshot({ jobId: "j1", state: "succeeded",
      books: [book("rut", { state: "done" }), book("gen", { state: "skipped" })] }));
    await waitFor(() => expect(get(collectionQaRunning)).toBe(false), { timeout: 3000 });
    expect(screen.getByText("Unchanged")).toBeInTheDocument();
  });
});
