// AI review request, shared between ReviewPanel.svelte (which owns the AI
// review job/polling state and progress UI) and VerseList.svelte (the verse
// right-click menu, issue #69), so the menu can trigger a review without
// duplicating ReviewPanel's job-tracking state -- same reasoning as
// alignmentUi.ts and verseEditor.ts.
import { writable } from "svelte/store";

export type AIReviewScope = "verse" | "chapter" | "book";

export interface AIReviewRequest {
  chapter: string;
  verse: string;
  scope: AIReviewScope;
}

export const aiReviewRequest = writable<AIReviewRequest | null>(null);

/** Mirrors ReviewPanel's own `aiJobBusy` so other components can disable
 * their own "run AI review" controls without reaching into its state. */
export const aiJobActive = writable(false);

export function requestAIReview(chapter: string, verse: string, scope: AIReviewScope): void {
  aiReviewRequest.set({ chapter, verse, scope });
}

/** #502: what the AI tab says while several verses are in one request, e.g.
 * "Verses 1:4–7 are being reviewed together in one request". Empty for a
 * single-verse request, a finished job, or an engine that reports no window. */
export function aiWindowLabel(job: {
  state: string;
  currentChapter: string | null;
  currentWindow?: string[];
} | null | undefined): string {
  if (!job || (job.state !== "running" && job.state !== "queued")) return "";
  const verses = job.currentWindow ?? [];
  if (verses.length < 2) return "";
  const chapter = job.currentChapter ? `${job.currentChapter}:` : "";
  return `Verses ${chapter}${verses[0]}–${verses[verses.length - 1]} are being reviewed together in one request`;
}
