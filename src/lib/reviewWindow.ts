import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import type { ProjectInfo } from "./types/finding";
import type { ParatextReviewDecision } from "./types/paratext";

export const REVIEW_WINDOW = "review-queue";
export interface ReviewContext { project: ProjectInfo | null; open: boolean; revision: number }
export type ReviewMessage =
  | { kind: "ready" }
  | { kind: "dock" | "close"; path: string }
  | { kind: "navigate"; path: string; book: string; chapter: string; verse: string }
  | { kind: "saved"; path: string; decision: ParatextReviewDecision };

export const desktopReviewAvailable = () => "__TAURI_INTERNALS__" in window;
export const openReviewWindow = () => invoke<void>("review_window", { action: "open" });
export const hideReviewWindow = () => invoke<void>("review_window", { action: "hide" });
export const sendReviewContext = (context: ReviewContext) => emitTo(REVIEW_WINDOW, "review-context", context);
export const sendReviewMessage = (message: ReviewMessage) => emitTo("main", "review-message", message);
export const onReviewMessage = (handler: (message: ReviewMessage) => void) => listen<ReviewMessage>("review-message", (e) => handler(e.payload));
export const onReviewContext = (handler: (context: ReviewContext) => void) => listen<ReviewContext>("review-context", (e) => handler(e.payload));
export const reviewWindowError = (message: string) => emitTo(REVIEW_WINDOW, "review-error", message);
export const onReviewError = (handler: (message: string) => void) => listen<string>("review-error", (e) => handler(e.payload));
