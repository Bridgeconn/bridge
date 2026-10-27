/**
 * #372: a chapter or book AI review asks first, in the app, and a declined
 * answer stops it. The old `if (!window.confirm(…)) return` read the dialog
 * plugin's Promise as true in the installed app, so one click on Chapter
 * started a paid run over the whole chapter.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { startAIReview, known } = vi.hoisted(() => ({
  startAIReview: vi.fn(),
  known: {} as Record<string, unknown>,
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: new Proxy(known, {
    get: (target, name: string) => {
      if (name === "startAIReview") return startAIReview;
      if (name === "runVerseChecks") return vi.fn().mockResolvedValue([]);
      if (!(name in target)) target[name] = vi.fn().mockResolvedValue({ items: [] });
      return target[name];
    },
  }),
}));

import ReviewPanel from "../ReviewPanel.svelte";
import { currentChapter, project, selectedVerse } from "../../stores";
import { aiReviewRequest } from "../../aiReviewUi";
import { answerConfirmation, confirmRequest } from "../../confirmAction";

const snapshot = {
  jobId: "job-1", scope: "chapter", mode: "basic", projectPath: "/p", state: "running",
  chapters: ["1"], chapterVerses: { "1": ["1"] }, skippedCurrentVerses: 0, resumeOf: "",
  totalVerses: 1, completedVerses: 0, failedVerses: 0, percent: 0,
  currentChapter: "1", currentVerse: "1", currentStage: "Preparing AI review",
  results: {}, latestResult: null, error: null, createdAt: "", finishedAt: null,
};

describe("ReviewPanel asks before a chapter or book AI review (#372)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "gen" } as never);
    currentChapter.set("1");
    selectedVerse.set("1");
    startAIReview.mockResolvedValue(snapshot);
  });

  afterEach(() => {
    answerConfirmation(false);
    selectedVerse.set(null);
  });

  async function pause(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  it("Chapter asks, starts nothing until answered, and a declined answer stops it", async () => {
    // A Promise-returning window.confirm, the installed app's: the action
    // must never consult it, let alone read it as true.
    const stale = vi.spyOn(window, "confirm").mockImplementation((() => Promise.resolve(false)) as never);
    try {
      render(ReviewPanel);
      await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
      await fireEvent.click(screen.getByRole("button", { name: "Chapter" }));
      expect(get(confirmRequest)?.title).toBe("Run AI review for this chapter?");
      expect(get(confirmRequest)?.body).toMatch(/API charges/);
      await pause();
      expect(startAIReview).not.toHaveBeenCalled();
      answerConfirmation(false);
      await pause();
      expect(startAIReview).not.toHaveBeenCalled();
      expect(stale).not.toHaveBeenCalled();
      expect(get(confirmRequest)).toBeNull();
    } finally {
      stale.mockRestore();
    }
  });

  it("a confirmed Book runs the book; a verse review asks nothing", async () => {
    render(ReviewPanel);
    await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
    await fireEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(get(confirmRequest)?.confirmLabel).toBe("Run for the book");
    answerConfirmation(true);
    await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("book", "1", "1", "basic"));

    startAIReview.mockClear();
    aiReviewRequest.set({ chapter: "1", verse: "1", scope: "verse" });
    await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("verse", "1", "1", "basic"));
    expect(get(confirmRequest)).toBeNull();
  });

  it("the verse-row menu's Chapter request asks the same question", async () => {
    render(ReviewPanel);
    aiReviewRequest.set({ chapter: "1", verse: "1", scope: "chapter" });
    await waitFor(() => expect(get(confirmRequest)?.title).toBe("Run AI review for this chapter?"));
    await pause();
    expect(startAIReview).not.toHaveBeenCalled();
    answerConfirmation(true);
    await waitFor(() => expect(startAIReview).toHaveBeenCalledWith("chapter", "1", "1", "basic"));
  });
});
