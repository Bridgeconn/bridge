/**
 * "Align with AI" (2026-11-24): the dialog that replaced "Align chapter with
 * AI". The reviewer picks one, several or all chapters, sees the cost before
 * anything is sent, starts, and can close the dialog while the run goes on.
 *
 * jsdom shows the selection, what is asked of the engine and what is said.
 * That the boxes reflow in a narrow window, that the grid scrolls and the
 * footer stays in view, needs the desktop app.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { autoAlignEstimate, autoAlignStart, autoAlignStatus, autoAlignCancel, autoAlignRetry, getSettings } = vi.hoisted(() => ({
  autoAlignEstimate: vi.fn(), autoAlignStart: vi.fn(), autoAlignStatus: vi.fn(), autoAlignCancel: vi.fn(),
  autoAlignRetry: vi.fn(), getSettings: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { autoAlignEstimate, autoAlignStart, autoAlignStatus, autoAlignCancel, autoAlignRetry, getSettings },
}));

import AutoAlignDialog from "../AutoAlignDialog.svelte";
import { autoAlignRun, resetAutoAlignRunForTests } from "../../autoAlignRun";
import { currentChapter, project } from "../../stores";
import type { AutoAlignEstimate, AutoAlignJobStatus } from "../../types/finding";

const CHAPTERS = ["1", "2", "3", "4", "5", "6"];

function estimate(chapter: string, overrides: Partial<AutoAlignEstimate> = {}): AutoAlignEstimate {
  return {
    scope: "chapter", chapters: [chapter], windows: 5, calls: 10,
    estimatedInputTokens: 40_000, estimatedOutputTokens: 15_000, estimatedCostUSD: 0.5,
    model: "gpt-test", hasApiKey: true, aiReady: true, planUsage: false, ...overrides,
  };
}

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

const done = (chapter: string, verses: string[], status: "succeeded" | "failed" = "succeeded") => ({
  chapter, verses, status, error: status === "failed" ? "The provider refused." : null,
});

const box = (chapter: string) => screen.getByRole("button", { name: new RegExp(`^Chapter ${chapter}( \\(open now\\))?$`) });
const pressed = () => CHAPTERS.filter((chapter) => box(chapter).getAttribute("aria-pressed") === "true");
const summary = () => document.querySelector("footer .summary")?.textContent?.replace(/\s+/g, " ").trim() ?? "";

function mount(props: Record<string, unknown> = {}) {
  const handlers = { onClose: vi.fn(), onOpenChapter: vi.fn(), onOpenReview: vi.fn() };
  render(AutoAlignDialog, { props: { ...handlers, ...props } });
  return handlers;
}

describe("AutoAlignDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetAutoAlignRunForTests();
    project.set({ path: "/p", bookId: "php", chapters: CHAPTERS } as never);
    currentChapter.set("2");
    autoAlignEstimate.mockImplementation(async (_scope: string, chapters: string[]) => estimate(chapters[0]));
  });

  afterEach(() => {
    resetAutoAlignRunForTests();
    vi.useRealTimers();
  });

  describe("choosing chapters", () => {
    it("opens with the open chapter selected and its cost worked out, and has sent nothing", async () => {
      mount();
      expect(screen.getByRole("heading", { name: "Align with AI" })).toBeInTheDocument();
      expect(CHAPTERS.map((chapter) => box(chapter).textContent)).toEqual(CHAPTERS);
      expect(pressed()).toEqual(["2"]);
      expect(box("2")).toHaveAccessibleName("Chapter 2 (open now)");
      expect(screen.getByText("1 of 6 selected")).toBeInTheDocument();
      await waitFor(() => expect(summary()).toBe("1 chapter 10 requests ~55k tokens about $0.50"));
      expect(autoAlignEstimate).toHaveBeenCalledWith("chapter", ["2"]);
      expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();
      expect(autoAlignStart).not.toHaveBeenCalled();
    });

    it("a click selects and deselects; Shift+click selects the range from the last click", async () => {
      mount();
      await fireEvent.click(box("2"));
      expect(pressed()).toEqual([]);
      expect(summary()).toBe("Select at least one chapter.");
      expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();

      await fireEvent.click(box("3"));
      await fireEvent.click(box("6"), { shiftKey: true });
      expect(pressed()).toEqual(["3", "4", "5", "6"]);
      // Backwards works the same way, and adds to what is selected.
      await fireEvent.click(box("1"), { shiftKey: true });
      expect(pressed()).toEqual(CHAPTERS);
      expect(screen.getByText("6 of 6 selected")).toBeInTheDocument();
    });

    it("has This chapter, Select all and Clear", async () => {
      mount();
      await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
      expect(pressed()).toEqual(CHAPTERS);
      await fireEvent.click(screen.getByRole("button", { name: "Clear" }));
      expect(pressed()).toEqual([]);
      expect(screen.getByRole("button", { name: "Clear" })).toBeDisabled();
      await fireEvent.click(screen.getByRole("button", { name: "This chapter" }));
      expect(pressed()).toEqual(["2"]);
    });

    it("is keyboard operable: arrows move, Home and End jump, Ctrl+A selects all", async () => {
      mount();
      const grid = screen.getByRole("group", { name: "Chapters" });
      // One Tab stop in the grid: the open chapter's box.
      expect(CHAPTERS.filter((chapter) => box(chapter).tabIndex === 0)).toEqual(["2"]);
      box("2").focus();
      await fireEvent.keyDown(grid, { key: "ArrowRight" });
      expect(document.activeElement).toBe(box("3"));
      await fireEvent.keyDown(grid, { key: "ArrowLeft" });
      await fireEvent.keyDown(grid, { key: "ArrowLeft" });
      expect(document.activeElement).toBe(box("1"));
      await fireEvent.keyDown(grid, { key: "ArrowLeft" });
      expect(document.activeElement).toBe(box("1"));
      await fireEvent.keyDown(grid, { key: "End" });
      expect(document.activeElement).toBe(box("6"));
      await fireEvent.keyDown(grid, { key: "Home" });
      expect(document.activeElement).toBe(box("1"));
      await fireEvent.keyDown(grid, { key: "a", ctrlKey: true });
      expect(pressed()).toEqual(CHAPTERS);
    });

    it("adds the cost up chapter by chapter, and works each chapter out once", async () => {
      mount();
      await waitFor(() => expect(summary()).toContain("about $0.50"));
      await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
      await waitFor(() => expect(summary()).toBe("6 chapters 60 requests ~330k tokens about $3.00"));
      // One call per chapter, in book order; chapter 2 was already known.
      expect(autoAlignEstimate.mock.calls.map(([, chapters]) => chapters[0])).toEqual(["2", "1", "3", "4", "5", "6"]);

      await fireEvent.click(screen.getByRole("button", { name: "Clear" }));
      await fireEvent.click(box("4"));
      await fireEvent.click(box("5"));
      expect(summary()).toBe("2 chapters 20 requests ~110k tokens about $1.00");
      expect(autoAlignEstimate).toHaveBeenCalledTimes(6);
    });

    it("says it is working the cost out, and keeps Start off until every chapter is known", async () => {
      let release: (value: AutoAlignEstimate) => void = () => {};
      autoAlignEstimate.mockImplementation((_scope: string, chapters: string[]) => chapters[0] === "3"
        ? new Promise<AutoAlignEstimate>((resolve) => { release = resolve; })
        : Promise.resolve(estimate(chapters[0])));
      mount();
      await waitFor(() => expect(summary()).toContain("about $0.50"));
      await fireEvent.click(box("3"));
      await waitFor(() => expect(summary()).toBe("Working out the cost… 1 of 2 chapters"));
      expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
      release(estimate("3"));
      await waitFor(() => expect(summary()).toBe("2 chapters 20 requests ~110k tokens about $1.00"));
      expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();
    });

    it("on a ChatGPT sign-in says the plan's allowance instead of dollars", async () => {
      autoAlignEstimate.mockImplementation(async (_scope: string, chapters: string[]) => estimate(chapters[0], { planUsage: true, estimatedCostUSD: 0 }));
      mount();
      await waitFor(() => expect(summary()).toBe("1 chapter 10 requests ~55k tokens uses your ChatGPT plan allowance"));
      expect(summary()).not.toContain("$");
    });

    it("says when the cost could not be worked out, and tries again on request", async () => {
      autoAlignEstimate.mockRejectedValueOnce(new Error("The engine did not answer."));
      mount();
      expect(await screen.findByText(/The cost could not be worked out: The engine did not answer\./)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
      await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      await waitFor(() => expect(summary()).toContain("about $0.50"));
    });

    // Joel, 2026-11-24: one main button. Start is the only one here; the x
    // is how the dialog is left without starting.
    it("has Start as its one button; the close button closes it and sends nothing", async () => {
      const handlers = mount();
      expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
      expect(screen.getByRole("button", { name: "Start" })).toHaveClass("ui-btn", "primary");
      await fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(handlers.onClose).toHaveBeenCalledOnce();
      expect(autoAlignStart).not.toHaveBeenCalled();
    });

    it("Escape closes it", async () => {
      const handlers = mount();
      await fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
      expect(handlers.onClose).toHaveBeenCalledOnce();
    });
  });

  describe("starting", () => {
    it("sends the selected chapters in book order, whatever order they were clicked in", async () => {
      autoAlignStart.mockResolvedValue(snapshot({ chapters: ["1", "3", "5"], chapterWindows: { "1": 1, "3": 1, "5": 1 } }));
      autoAlignStatus.mockResolvedValue(snapshot({ chapters: ["1", "3", "5"], chapterWindows: { "1": 1, "3": 1, "5": 1 } }));
      mount();
      await fireEvent.click(box("2"));
      await fireEvent.click(box("5"));
      await fireEvent.click(box("1"));
      await fireEvent.click(box("3"));
      await waitFor(() => expect(screen.getByRole("button", { name: "Start" })).toBeEnabled());
      await fireEvent.click(screen.getByRole("button", { name: "Start" }));
      await waitFor(() => expect(autoAlignStart).toHaveBeenCalledWith("chapter", ["1", "3", "5"]));
    });

    it("shows a refused start in the dialog and stays on the selection", async () => {
      autoAlignStart.mockRejectedValue(new Error("Automatic alignment job aaj-9 is already running."));
      mount();
      await waitFor(() => expect(screen.getByRole("button", { name: "Start" })).toBeEnabled());
      await fireEvent.click(screen.getByRole("button", { name: "Start" }));
      expect(await screen.findByText("Automatic alignment job aaj-9 is already running.")).toBeInTheDocument();
      expect(screen.getByRole("group", { name: "Chapters" })).toBeInTheDocument();
      // Changing the selection clears the message.
      await fireEvent.click(box("4"));
      expect(screen.queryByText("Automatic alignment job aaj-9 is already running.")).toBeNull();
    });
  });

  describe("while the run is under way", () => {
    async function running(job: AutoAlignJobStatus) {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      autoAlignStart.mockResolvedValue(snapshot());
      autoAlignStatus.mockResolvedValue(job);
      const handlers = mount();
      await fireEvent.click(box("3"));
      await waitFor(() => expect(screen.getByRole("button", { name: "Start" })).toBeEnabled());
      await fireEvent.click(screen.getByRole("button", { name: "Start" }));
      await vi.advanceTimersByTimeAsync(1100);
      return handlers;
    }

    it("turns the boxes into a progress map of the run's chapters", async () => {
      await running(snapshot({
        currentWindow: { chapter: "2", verses: ["3", "4"] }, windowsDone: 1,
        verdicts: { "2:1": "ALIGNED_CLEAN" }, results: { "2:1-3": done("2", ["1", "2", "3"]) },
      }));
      const map = screen.getByRole("group", { name: "Chapters of this run" });
      expect(Array.from(map.querySelectorAll(".cell")).map((cell) => [cell.textContent, cell.className.match(/running|waiting|clean|review|failed|partial/)?.[0]]))
        .toEqual([["2", "running"], ["3", "waiting"]]);
      expect(screen.getByRole("img", { name: "Chapter 2: in progress, 1 verse clean" })).toBeInTheDocument();
      expect(summary()).toBe("Chapter 2, verses 3–4 1 of 3 windows");
      expect(screen.getByRole("progressbar", { name: "Progress of the run" })).toHaveAttribute("value", "1");
      // No selecting while it runs.
      expect(screen.queryByRole("button", { name: "Select all" })).toBeNull();
    });

    it("Start's place is taken by Cancel; closing keeps the run going, Cancel asks the engine to stop", async () => {
      autoAlignCancel.mockResolvedValue(snapshot({ state: "cancelling" }));
      const handlers = await running(snapshot());
      expect(screen.queryByRole("button", { name: "Start" })).toBeNull();
      expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("ui-btn", "danger");
      await fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(handlers.onClose).toHaveBeenCalledOnce();
      expect(autoAlignCancel).not.toHaveBeenCalled();
      expect(get(autoAlignRun).phase).toBe("running");

      await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      expect(autoAlignCancel).toHaveBeenCalledWith("aaj-1");
      expect(await screen.findByRole("button", { name: "Cancelling…" })).toBeDisabled();
      expect(summary()).toContain("Cancelling after the request in flight…");
    });

    it("reopened during a run, it shows the progress and not the selection", async () => {
      await running(snapshot({
        currentWindow: { chapter: "3", verses: ["1", "2"] }, windowsDone: 2,
        results: { "2:1-3": done("2", ["1", "2", "3"]), "2:3-5": done("2", ["3", "4", "5"]) },
      }));
      document.body.innerHTML = "";
      mount();
      expect(screen.getByRole("group", { name: "Chapters of this run" })).toBeInTheDocument();
      expect(screen.queryByRole("group", { name: "Chapters" })).toBeNull();
      expect(summary()).toBe("Chapter 3, verses 1–2 2 of 3 windows");
    });
  });

  describe("when the run has ended", () => {
    async function finished(job: AutoAlignJobStatus) {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      autoAlignStart.mockResolvedValue(snapshot());
      autoAlignStatus.mockResolvedValue(job);
      const handlers = mount();
      await fireEvent.click(box("3"));
      await waitFor(() => expect(screen.getByRole("button", { name: "Start" })).toBeEnabled());
      await fireEvent.click(screen.getByRole("button", { name: "Start" }));
      await vi.advanceTimersByTimeAsync(1100);
      return handlers;
    }

    const allDone = {
      windowsDone: 3,
      verdicts: { "2:1": "ALIGNED_CLEAN", "2:2": "NEEDS_REVIEW", "2:3": "NEEDS_REVIEW", "2:4": "NEEDS_REVIEW", "2:5": "NEEDS_REVIEW", "3:1": "ALIGNED_CLEAN" } as AutoAlignJobStatus["verdicts"],
      results: { "2:1-3": done("2", ["1", "2", "3"]), "2:3-5": done("2", ["3", "4", "5"]), "3:1-2": done("3", ["1", "2"]) },
    };

    it("says what it did, and a chapter's box opens that chapter", async () => {
      const handlers = await finished(snapshot({ state: "succeeded", ...allDone }));
      expect(summary()).toBe("Aligned 2 chapters 2 verses clean · 4 need review");
      const needsReview = screen.getByRole("button", { name: /^Chapter 2: needs review, 1 verse clean, 4 verses to review\. Open this chapter$/ });
      expect(screen.getByRole("button", { name: /^Chapter 3: aligned, 1 verse clean\. Open this chapter$/ })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
      await fireEvent.click(needsReview);
      expect(handlers.onOpenChapter).toHaveBeenCalledWith("2");
      expect(handlers.onClose).toHaveBeenCalledOnce();
    });

    it("Open review goes to the first chapter that needs it, with its first three verses", async () => {
      const handlers = await finished(snapshot({ state: "succeeded", ...allDone }));
      await fireEvent.click(screen.getByRole("button", { name: "Open review" }));
      expect(handlers.onOpenReview).toHaveBeenCalledWith("2", ["2", "3", "4"]);
      expect(handlers.onClose).toHaveBeenCalledOnce();
    });

    it("after a cancel it says how far it got and offers Resume", async () => {
      autoAlignRetry.mockResolvedValue(snapshot({ jobId: "aaj-2", resumeOf: "aaj-1", chapterWindows: { "2": 1, "3": 1 }, windowsTotal: 2 }));
      await finished(snapshot({
        state: "cancelled", windowsDone: 1, verdicts: { "2:1": "ALIGNED_CLEAN" }, results: { "2:1-3": done("2", ["1", "2", "3"]) },
      }));
      expect(summary()).toBe("Cancelled after 1 of 3 windows 1 verse clean · 0 need review");
      expect(screen.getByRole("button", { name: "Chapter 2: not finished, 1 verse clean. Open this chapter" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Chapter 3: waiting. Open this chapter" })).toBeInTheDocument();
      await fireEvent.click(screen.getByRole("button", { name: "Resume" }));
      expect(autoAlignRetry).toHaveBeenCalledWith("aaj-1");
      await waitFor(() => expect(get(autoAlignRun).phase).toBe("running"));
      expect(await screen.findByRole("button", { name: "Cancel" })).toBeInTheDocument();
    });

    it("a run stopped at a plan limit shows the engine's reason and offers Resume", async () => {
      await finished(snapshot({
        state: "failed", error: "Your ChatGPT plan limit has been reached. Try again later.", windowsDone: 2, windowsFailed: 1,
        results: { "2:1-3": done("2", ["1", "2", "3"]), "2:3-5": done("2", ["3", "4", "5"], "failed") },
      }));
      expect(summary()).toBe("Stopped before the end 0 verses clean · 0 need review · 1 window failed");
      expect(screen.getByRole("alert")).toHaveTextContent("Your ChatGPT plan limit has been reached. Try again later.");
      expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    });

    it("Done clears the run and closes; Align more chapters goes back to the selection", async () => {
      const handlers = await finished(snapshot({ state: "succeeded", ...allDone }));
      await fireEvent.click(screen.getByRole("button", { name: "Align more chapters" }));
      expect(get(autoAlignRun).phase).toBe("idle");
      expect(await screen.findByRole("group", { name: "Chapters" })).toBeInTheDocument();
      expect(handlers.onClose).not.toHaveBeenCalled();
    });

    it("Done clears the run and closes", async () => {
      const handlers = await finished(snapshot({ state: "succeeded", ...allDone }));
      await fireEvent.click(screen.getByRole("button", { name: "Done" }));
      expect(get(autoAlignRun).phase).toBe("idle");
      expect(handlers.onClose).toHaveBeenCalledOnce();
    });

    it("a run that belongs to another book is shown, with nothing that would navigate this one", async () => {
      await finished(snapshot({ state: "succeeded", ...allDone }));
      project.set({ path: "/other", bookId: "tit", chapters: ["1", "2", "3"] } as never);
      expect(await screen.findByText(/This run belongs to another book/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Open this chapter/ })).toBeNull();
      expect(screen.queryByRole("button", { name: "Open review" })).toBeNull();
      expect(screen.getByRole("img", { name: /^Chapter 2: needs review/ })).toBeInTheDocument();
    });
  });
});
