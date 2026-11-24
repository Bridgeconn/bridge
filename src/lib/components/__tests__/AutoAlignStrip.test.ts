/**
 * The strip above the text for a run of "Align with AI" (2026-11-24). It took
 * over from AutoAlignChapterButton's strip: the estimate and the confirmation
 * moved into the dialog, and what is left here is the run's progress and its
 * result, there while the dialog is closed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

const { autoAlignStart, autoAlignStatus, autoAlignCancel } = vi.hoisted(() => ({
  autoAlignStart: vi.fn(), autoAlignStatus: vi.fn(), autoAlignCancel: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { autoAlignStart, autoAlignStatus, autoAlignCancel },
}));

import AutoAlignStrip from "../AutoAlignStrip.svelte";
import { autoAlignRun, resetAutoAlignRunForTests, startRun } from "../../autoAlignRun";
import { project } from "../../stores";
import type { AutoAlignJobStatus } from "../../types/finding";

function snapshot(overrides: Partial<AutoAlignJobStatus> = {}): AutoAlignJobStatus {
  return {
    jobId: "aaj-1", scope: "chapter", apply: true, state: "running", stage: "",
    chapters: ["2", "3"], chapterWindows: { "2": 2, "3": 1 },
    windowsTotal: 3, windowsDone: 0, windowsFailed: 0, percent: 0,
    currentWindow: null, currentPass: null, windowResult: null,
    verdictCounts: {}, verdicts: {}, results: {},
    usage: { calls: 0, totalTokens: 0, estimatedCostUSD: 0 },
    error: null, unavailable: null, resumeOf: "", createdAt: "", finishedAt: null,
    ...overrides,
  };
}

const done = (chapter: string, verses: string[]) => ({ chapter, verses, status: "succeeded" as const, error: null });
const text = () => document.querySelector(".auto-strip")?.textContent?.replace(/\s+/g, " ").trim() ?? "";

async function run(start: AutoAlignJobStatus, then: AutoAlignJobStatus, chapters = ["2", "3"]) {
  autoAlignStart.mockResolvedValue(start);
  autoAlignStatus.mockResolvedValue(then);
  await startRun(chapters);
  await vi.advanceTimersByTimeAsync(1100);
}

describe("AutoAlignStrip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    resetAutoAlignRunForTests();
    project.set({ path: "/p", bookId: "php", chapters: ["1", "2", "3"] } as never);
  });

  afterEach(() => {
    resetAutoAlignRunForTests();
    vi.useRealTimers();
  });

  it("draws nothing while there is no run", () => {
    const { container } = render(AutoAlignStrip);
    expect(container.querySelector(".auto-strip")).toBeNull();
  });

  it("shows where a run over several chapters is, and Show opens the dialog", async () => {
    const onOpen = vi.fn();
    render(AutoAlignStrip, { props: { onOpen } });
    await run(snapshot(), snapshot({
      currentWindow: { chapter: "2", verses: ["3", "4", "5"] }, windowsDone: 1, results: { "2:1-3": done("2", ["1", "2", "3"]) },
    }));
    expect(screen.getByRole("status")).toHaveTextContent("Aligning with AI · ch. 2 v.3–5 · 1/3 windows");
    await fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("for one chapter leaves the chapter out of the progress, as the old strip did", async () => {
    render(AutoAlignStrip);
    const one = { chapters: ["2"], chapterWindows: { "2": 2 }, windowsTotal: 2 };
    await run(snapshot(one), snapshot({ ...one, currentWindow: { chapter: "2", verses: ["7", "8", "9"] } }), ["2"]);
    expect(screen.getByRole("status")).toHaveTextContent("Aligning with AI · v.7–9 · 0/2 windows");
  });

  it("Cancel asks the engine to stop and waits for it", async () => {
    autoAlignCancel.mockResolvedValue(snapshot({ state: "cancelling" }));
    render(AutoAlignStrip);
    await run(snapshot(), snapshot());
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(autoAlignCancel).toHaveBeenCalledWith("aaj-1");
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Cancelling…");
  });

  it("shows the result, opens the review on the first chapter that needs it, and can be dismissed", async () => {
    const onOpenReview = vi.fn();
    const onOpen = vi.fn();
    render(AutoAlignStrip, { props: { onOpen, onOpenReview } });
    await run(snapshot(), snapshot({
      state: "succeeded", windowsDone: 3,
      verdicts: { "2:1": "ALIGNED_CLEAN", "3:1": "NEEDS_REVIEW", "3:2": "NEEDS_REVIEW" },
      results: { "2:1-3": done("2", ["1", "2", "3"]), "2:3-5": done("2", ["3", "4", "5"]), "3:1-2": done("3", ["1", "2"]) },
    }));
    expect(screen.getByRole("status")).toHaveTextContent("2 chapters aligned: 1 verse clean, 2 need review.");
    expect(screen.getByRole("status")).toHaveClass("mixed");
    await fireEvent.click(screen.getByRole("button", { name: "Open review" }));
    expect(onOpenReview).toHaveBeenCalledWith("3", ["1", "2"]);
    await fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(onOpen).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(get(autoAlignRun).phase).toBe("idle");
    expect(document.querySelector(".auto-strip")).toBeNull();
  });

  it("names the chapter when the run was one chapter, and is not marked when everything is clean", async () => {
    render(AutoAlignStrip);
    const one = { chapters: ["2"], chapterWindows: { "2": 1 }, windowsTotal: 1 };
    await run(snapshot(one), snapshot({
      ...one, state: "succeeded", windowsDone: 1, verdicts: { "2:1": "ALIGNED_CLEAN", "2:2": "ALIGNED_CLEAN" },
      results: { "2:1-2": done("2", ["1", "2"]) },
    }), ["2"]);
    expect(screen.getByRole("status")).toHaveTextContent("Chapter 2 aligned: 2 verses clean, 0 need review.");
    expect(screen.getByRole("status")).not.toHaveClass("mixed");
    expect(screen.queryByRole("button", { name: "Open review" })).toBeNull();
  });

  it("says how far a cancelled run got", async () => {
    render(AutoAlignStrip);
    await run(snapshot(), snapshot({
      state: "cancelled", windowsDone: 1, verdicts: { "2:1": "NEEDS_REVIEW" }, results: { "2:1-3": done("2", ["1", "2", "3"]) },
    }));
    expect(screen.getByRole("status")).toHaveTextContent("Cancelled after 1 of 3 windows: 0 verses clean, 1 needs review.");
  });

  it("shows why a run stopped", async () => {
    render(AutoAlignStrip);
    await run(snapshot(), snapshot({ state: "failed", error: "Your ChatGPT plan limit has been reached. Try again later." }));
    expect(screen.getByRole("status")).toHaveTextContent("2 chapters: the run stopped.");
    expect(screen.getByRole("alert")).toHaveTextContent("Your ChatGPT plan limit has been reached. Try again later.");
  });

  it("offers no review for a run that belongs to another book", async () => {
    render(AutoAlignStrip);
    await run(snapshot(), snapshot({ state: "succeeded", verdicts: { "2:1": "NEEDS_REVIEW" } }));
    project.set({ path: "/other", bookId: "tit", chapters: ["1"] } as never);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.queryByRole("button", { name: "Open review" })).toBeNull();
    expect(screen.getByRole("button", { name: "Details" })).toBeInTheDocument();
  });
});
