// #400: opening a never-opened book of a collection prepares it chapter by
// chapter on a worker (#210), and project.open reports each chapter through
// bridgeClient.openProject's onProgress. The book switch in App.svelte showed
// that in its "Opening X…" strip; the Home screen's open and the open after an
// import did not pass the callback at all, so the reader saw a still sentence
// for the whole prepare. This store is how a caller outside App.svelte puts its
// prepare into that same strip.
import { writable } from "svelte/store";
import type { ImportJobSnapshot } from "./types/finding";

export interface PrepareProgress {
  /** The book or project being opened, as the strip names it. */
  name: string;
  /** "preparing chapter 3 of 50", "preparing", or "" once prepared. */
  detail: string;
}

/** The prepare in progress from a Home-screen open, or null. App.svelte's
 *  "Opening …" strip reads it beside its own book switch. */
export const prepareProgress = writable<PrepareProgress | null>(null);

/** One wording for a prepare snapshot, shared with the book switch. */
export function prepareDetail(snapshot: ImportJobSnapshot): string {
  if (snapshot.chapter && snapshot.chapterCount) return `preparing chapter ${snapshot.chapter} of ${snapshot.chapterCount}`;
  return snapshot.state === "succeeded" ? "" : "preparing";
}

/** The onProgress callback for `bridge.openProject` that shows `name` in the
 *  strip while the book is prepared. Clear it with `clearPrepare()` when the
 *  open has returned, whichever way. */
export function trackPrepare(name: string): (snapshot: ImportJobSnapshot) => void {
  return (snapshot) => prepareProgress.set({ name, detail: prepareDetail(snapshot) });
}

export function clearPrepare(): void {
  prepareProgress.set(null);
}
