/**
 * #511. Four things the Review panel did around an AI review:
 *
 * - a finished review can have written the verse's alignment, and nothing told
 *   the rest of the app, so an open Word alignment tab kept the old one;
 * - the AI explanation lived only in the panel and was gone after a verse
 *   change, although the engine kept it;
 * - the Verse button ran an up-to-date review again without a word;
 * - saving an edit to a verse with a saved issue started a review by itself.
 *
 * jsdom shows the signals sent, the stores updated and the questions asked.
 * That the alignment tab then redraws on screen needs the desktop app.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { startAIReview, aiReviewStatus, listChecksForVerse, getAlignment, runVerseChecks, getSettings, known, hooks } = vi.hoisted(() => ({
  startAIReview: vi.fn(),
  aiReviewStatus: vi.fn(),
  listChecksForVerse: vi.fn(),
  getAlignment: vi.fn(),
  runVerseChecks: vi.fn(),
  getSettings: vi.fn(),
  known: {} as Record<string, unknown>,
  hooks: {} as { saved?: (saved: Record<string, unknown>) => void },
}));

vi.mock("../../api/bridgeClient", () => ({
  // Everything else the panel calls on mount resolves to an empty answer.
  bridge: new Proxy(known, {
    get: (target, name: string) => {
      const named: Record<string, unknown> = {
        startAIReview, aiReviewStatus, listChecksForVerse, getAlignment, runVerseChecks, getSettings,
      };
      if (name in named) return named[name];
      if (!(name in target)) target[name] = vi.fn().mockResolvedValue({ items: [] });
      return target[name];
    },
  }),
}));

// The hook the panel registers for "a verse edit was saved" is captured, so a
// test can fire it without driving the whole edit and recheck.
vi.mock("../../verseEditor", async (original) => ({
  ...(await original<typeof import("../../verseEditor")>()),
  setVerseEditSavedHook: (hook: (saved: Record<string, unknown>) => void) => { hooks.saved = hook; },
}));

import ReviewPanel from "../ReviewPanel.svelte";
import { alignmentRevisionByVerse, alignmentStatusByVerse, currentChapter, project, selectedVerse } from "../../stores";
import { aiReviewRequest } from "../../aiReviewUi";
import { answerConfirmation, confirmRequest } from "../../confirmAction";
import type { AIReviewJobSnapshot } from "../../types/finding";

function snapshot(overrides: Partial<AIReviewJobSnapshot>): AIReviewJobSnapshot {
  return {
    jobId: "job-1", scope: "verse", mode: "basic", projectPath: "/p", state: "running",
    chapters: ["1"], chapterVerses: { "1": ["1"] }, skippedCurrentVerses: 0, resumeOf: "",
    totalVerses: 1, completedVerses: 0, failedVerses: 0, percent: 0,
    currentChapter: "1", currentVerse: "1", currentStage: "Preparing AI review",
    results: {}, latestResult: null, error: null, createdAt: "", finishedAt: null,
    ...overrides,
  };
}

const verseResult = (chapter: string, verse: string, status: "succeeded" | "failed" = "succeeded") => ({
  chapter, verse, status, summary: "", appliedCount: 0, skippedCount: 0, usage: {},
  error: status === "failed" ? "The provider refused." : null,
});

const stored = (state: "missing" | "current" | "stale", summary = "") => ({
  chapter: "1", verse: "1", checks: [], state: "ready", retryAfterMs: 0, message: "",
  aiReviewState: state, aiReviews: [], aiQaIssues: [], aiSummary: summary,
});

async function pause(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("ReviewPanel after an AI review (#511)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.saved = undefined;
    project.set({ path: "/p", bookId: "gen" } as never);
    currentChapter.set("1");
    selectedVerse.set("1");
    alignmentRevisionByVerse.set({});
    alignmentStatusByVerse.set({});
    listChecksForVerse.mockResolvedValue(stored("missing"));
    getAlignment.mockResolvedValue({ status: "complete" });
    runVerseChecks.mockResolvedValue([]);
    getSettings.mockResolvedValue({ aiReady: true, hasApiKey: true });
    startAIReview.mockResolvedValue(snapshot({}));
  });

  afterEach(() => {
    answerConfirmation(false);
    selectedVerse.set(null);
  });

  describe("tells the rest of the app that the verse's alignment may have changed", () => {
    it("signals once, reads the new alignment status and rechecks the alignment findings", async () => {
      alignmentStatusByVerse.set({ "1:1": "partial" } as never);
      const results = { "1:1": verseResult("1", "1") };
      aiReviewStatus
        .mockResolvedValueOnce(snapshot({ results }))
        .mockResolvedValue(snapshot({ results, state: "succeeded", percent: 100, completedVerses: 1 }));
      render(ReviewPanel);
      aiReviewRequest.set({ chapter: "1", verse: "1", scope: "verse" });

      await waitFor(() => expect(get(alignmentRevisionByVerse)["1:1"]).toBe(1));
      await waitFor(() => expect(get(alignmentStatusByVerse)["1:1"]).toBe("complete"));
      await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "1", ["alignment"]));
      // The same verse on the next poll is not signalled a second time.
      await waitFor(() => expect(aiReviewStatus).toHaveBeenCalledTimes(2), { timeout: 3000 });
      await pause();
      expect(get(alignmentRevisionByVerse)["1:1"]).toBe(1);
      expect(getAlignment).toHaveBeenCalledTimes(1);
    });

    it("covers every verse that finished between two polls, and not one that failed", async () => {
      alignmentStatusByVerse.set({ "1:1": "partial", "1:2": "partial", "1:3": "partial" } as never);
      aiReviewStatus.mockResolvedValue(snapshot({
        scope: "book", state: "failed", percent: 100, totalVerses: 4, completedVerses: 3, failedVerses: 1,
        results: {
          "1:1": verseResult("1", "1"), "1:2": verseResult("1", "2"),
          "1:3": verseResult("1", "3", "failed"),
          // A verse of a chapter that is not loaded: signalled, not fetched.
          "2:1": verseResult("2", "1"),
        },
        // Only the newest verse ever rides on latestResult.
        latestResult: null,
      }));
      render(ReviewPanel);
      aiReviewRequest.set({ chapter: "1", verse: "1", scope: "verse" });

      await waitFor(() => expect(get(alignmentRevisionByVerse)).toEqual({ "1:1": 1, "1:2": 1, "2:1": 1 }));
      await waitFor(() => expect(getAlignment).toHaveBeenCalledTimes(2));
      expect(getAlignment.mock.calls.map(([chapter, verse]) => `${chapter}:${verse}`).sort()).toEqual(["1:1", "1:2"]);
      expect(get(alignmentStatusByVerse)["1:3"]).toBe("partial");
    });

    it("says nothing for a job that belongs to another project", async () => {
      alignmentStatusByVerse.set({ "1:1": "partial" } as never);
      startAIReview.mockResolvedValue(snapshot({ projectPath: "/other" }));
      aiReviewStatus.mockResolvedValue(snapshot({
        projectPath: "/other", state: "succeeded", percent: 100, results: { "1:1": verseResult("1", "1") },
      }));
      render(ReviewPanel);
      aiReviewRequest.set({ chapter: "1", verse: "1", scope: "verse" });
      await waitFor(() => expect(aiReviewStatus).toHaveBeenCalled());
      await pause();
      expect(get(alignmentRevisionByVerse)).toEqual({});
      expect(getAlignment).not.toHaveBeenCalled();
    });
  });

  describe("keeps the AI explanation", () => {
    it("shows the stored summary again after another verse was selected, without usage figures", async () => {
      listChecksForVerse.mockImplementation(async (_chapter: string, verse: string) => verse === "1"
        ? { ...stored("current", "Stored summary for verse one."),
            aiQaIssues: [{ severity: "medium", title: "Tense", detail: "The verb is past in the source." }] }
        : stored("missing"));
      render(ReviewPanel);
      await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));

      expect(await screen.findByText("Stored summary for verse one.")).toBeInTheDocument();
      expect(screen.getByText("The verb is past in the source.")).toBeInTheDocument();
      expect(document.querySelector(".ai-cost")).toBeNull();
      expect(document.querySelector("[data-ai-stale]")).toBeNull();

      selectedVerse.set("2");
      expect(await screen.findByText(/No AI explanation yet for this verse/)).toBeInTheDocument();
      selectedVerse.set("1");
      expect(await screen.findByText("Stored summary for verse one.")).toBeInTheDocument();
    });

    it("marks a stored review that is out of date", async () => {
      listChecksForVerse.mockResolvedValue(stored("stale", "Summary from before the edit."));
      render(ReviewPanel);
      await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
      expect(await screen.findByText("Summary from before the edit.")).toBeInTheDocument();
      expect(document.querySelector("[data-ai-stale]")).toHaveTextContent("out of date");
    });

    it("leaves a run that has just finished on screen with its own figures", async () => {
      // Out of date to begin with, so the Verse run starts without a question.
      listChecksForVerse.mockResolvedValue(stored("stale", "The stored copy of the same review."));
      aiReviewStatus.mockResolvedValue(snapshot({
        state: "succeeded", percent: 100, completedVerses: 1, results: { "1:1": verseResult("1", "1") },
        latestResult: { key: "1:1", result: {
          chapter: "1", verse: "1", status: "succeeded", summary: "Live summary of this run.",
          checkReviews: [], qaIssues: [], appliedSelections: [], skippedSelections: [],
          alignmentProposal: null, alignmentWasAIProposed: false,
          usage: { totalTokens: 1234, estimatedCostUSD: 0.01 },
        } as never },
      }));
      render(ReviewPanel);
      await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
      // Stored first (nothing has run yet), then the run replaces it.
      expect(await screen.findByText("The stored copy of the same review.")).toBeInTheDocument();
      listChecksForVerse.mockResolvedValue(stored("missing"));
      aiReviewRequest.set({ chapter: "1", verse: "1", scope: "verse" });

      expect(await screen.findByText("Live summary of this run.")).toBeInTheDocument();
      await waitFor(() => expect(document.querySelector(".ai-cost")).toHaveTextContent("1,234 tokens"));
      // Translation helps re-reads the verse when the job ends; that read must
      // not swap the live result for the stored copy.
      listChecksForVerse.mockResolvedValue(stored("current", "The stored copy of the same review."));
      await pause();
      expect(screen.getByText("Live summary of this run.")).toBeInTheDocument();
      expect(screen.queryByText("The stored copy of the same review.")).toBeNull();
    });
  });

  describe("asks before spending again", () => {
    it("the Verse button asks when the stored review is up to date, and a declined answer starts nothing", async () => {
      listChecksForVerse.mockResolvedValue(stored("current", "Up to date."));
      render(ReviewPanel);
      await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
      await screen.findByText("Up to date.");

      await fireEvent.click(screen.getByRole("button", { name: "Verse" }));
      await waitFor(() => expect(get(confirmRequest)?.title).toBe("Run the AI review again for this verse?"));
      expect(get(confirmRequest)?.body).toMatch(/up to date/);
      expect(startAIReview).not.toHaveBeenCalled();
      answerConfirmation(false);
      await pause();
      expect(startAIReview).not.toHaveBeenCalled();
      // The explanation is still there: nothing was cleared for a run that did not start.
      expect(screen.getByText("Up to date.")).toBeInTheDocument();

      await fireEvent.click(screen.getByRole("button", { name: "Verse" }));
      await waitFor(() => expect(get(confirmRequest)).not.toBeNull());
      answerConfirmation(true);
      await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("verse", "1", "1", "basic"));
    });

    it("the Verse button asks nothing when the review is missing or out of date", async () => {
      for (const state of ["missing", "stale"] as const) {
        startAIReview.mockClear();
        listChecksForVerse.mockResolvedValue(stored(state, state === "stale" ? "Old." : ""));
        const view = render(ReviewPanel);
        await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
        await waitFor(() => expect(listChecksForVerse).toHaveBeenCalled());
        await fireEvent.click(screen.getByRole("button", { name: "Verse" }));
        await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("verse", "1", "1", "basic"));
        expect(get(confirmRequest)).toBeNull();
        view.unmount();
      }
    });

    it("the review after a verse edit asks first, and Not now starts nothing", async () => {
      // "current" on purpose: the edit makes it out of date, so once the
      // reviewer agrees the run must not ask a second question.
      listChecksForVerse.mockResolvedValue(stored("current", "Before the edit."));
      render(ReviewPanel);
      await waitFor(() => expect(hooks.saved).toBeTypeOf("function"));

      hooks.saved?.({ chapter: "1", verse: "1", issueResolutionsNeedingRecheck: 2 });
      await waitFor(() => expect(get(confirmRequest)?.title).toBe("Run the AI review for 1:1 now?"));
      expect(get(confirmRequest)?.body).toMatch(/2 saved issues/);
      expect(get(confirmRequest)?.cancelLabel).toBe("Not now");
      answerConfirmation(false);
      await pause();
      expect(startAIReview).not.toHaveBeenCalled();

      hooks.saved?.({ chapter: "1", verse: "1", issueResolutionsNeedingRecheck: 1 });
      await waitFor(() => expect(get(confirmRequest)?.body).toMatch(/A saved issue/));
      answerConfirmation(true);
      await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("verse", "1", "1", "basic"));
      expect(get(confirmRequest)).toBeNull();
    });

    it("an edit with no saved issue offers nothing", async () => {
      render(ReviewPanel);
      await waitFor(() => expect(hooks.saved).toBeTypeOf("function"));
      hooks.saved?.({ chapter: "1", verse: "1", issueResolutionsNeedingRecheck: 0 });
      await pause();
      expect(get(confirmRequest)).toBeNull();
      expect(startAIReview).not.toHaveBeenCalled();
    });

    it("with no AI set up there is no question: the start fails as before and says why", async () => {
      getSettings.mockResolvedValue({ aiReady: false, hasApiKey: false });
      startAIReview.mockRejectedValue(new Error("No OpenAI-compatible API key is configured."));
      render(ReviewPanel);
      await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
      await waitFor(() => expect(hooks.saved).toBeTypeOf("function"));

      hooks.saved?.({ chapter: "1", verse: "1", issueResolutionsNeedingRecheck: 1 });

      await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("verse", "1", "1", "basic"));
      expect(get(confirmRequest)).toBeNull();
      expect(await screen.findAllByText(/No OpenAI-compatible API key is configured/)).not.toHaveLength(0);
    });
  });
});
