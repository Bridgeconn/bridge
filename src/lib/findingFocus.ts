// Landing on a finding's exact span (#402). One route for every entry point
// -- the Language QA panel's rows and F8, the Review panel's cards, a click
// on an inline mark -- so they cannot disagree about what "go to this
// finding" does: the mark is ringed (`focusedFindingId`, which the verse text
// matches by `data-finding-ids`), scrolled to the middle of the reader and
// flashed once. A finding whose mark is not drawn (null offsets, a heading or
// footnote finding, a verse whose findings have not arrived) falls back to
// what every click did before: the verse is selected, and nothing else is said.
import { tick } from "svelte";
import { focusedFindingId } from "./stores";
import type { QaFinding } from "./types/finding";
import type { LanguageQaFinding } from "./types/languageQa";

export interface FindingSpan {
  /** Raw-verse code-point offsets, as both finding types carry them. */
  start: number;
  end: number;
}

/**
 * Where a finding sits in the raw verse string, for either finding type, or
 * null when it cannot be located there: QaFinding offsets are nullable, and a
 * Language QA finding with a `context` is in a heading, the book introduction
 * or a footnote, none of which the verse editor's caret can reach.
 */
export function findingSpan(finding: QaFinding | LanguageQaFinding): FindingSpan | null {
  if ("start_offset" in finding) {
    return finding.start_offset === null || finding.end_offset === null
      ? null
      : { start: finding.start_offset, end: finding.end_offset };
  }
  if (finding.context) return null;
  return { start: finding.start, end: finding.end };
}

/** The drawn mark carrying this finding, if the reader shows one. */
export function markElement(findingId: string): HTMLElement | null {
  if (typeof document === "undefined") return null;
  return document.querySelector<HTMLElement>(`[data-finding-ids~="${CSS.escape(findingId)}"]`);
}

// The finding a reveal is scrolling to, while it is. VerseList reads it so its
// own scroll-the-verse-to-the-top does not run under the mark's scroll.
let pendingId: string | null = null;

/** The finding whose mark is about to be scrolled into view, or null. */
export function pendingReveal(): string | null {
  return pendingId;
}

const FLASH_CLASS = "reveal-flash";
const FLASH_MS = 1200;
// Findings can arrive a moment after the verses they are about (the chapter
// loads, then its checks and Language QA pass hydrate), so the mark is looked
// for a few times before giving up.
const LOOKUP_ATTEMPTS = 8;
const LOOKUP_WAIT_MS = 50;

export interface RevealOptions {
  /** Runs first (a navigation to the finding's verse); the mark is looked for after it settles. */
  navigate?: () => void | Promise<unknown>;
  /** False for a click on the mark itself: it is on screen already, and moving text under the pointer is what #179 forbids. */
  scroll?: boolean;
}

/**
 * Ring finding `id` in the verse text, scroll its mark to the middle of the
 * reader and flash it once. Resolves true when the mark was found. The ring
 * is set before `navigate` runs so the verse text can skip its own
 * scroll-to-top for the verse the mark is in. On a miss the ring stays set
 * (the Language QA walk keys its place on it) but nothing moves.
 */
export async function revealFinding(id: string, options: RevealOptions = {}): Promise<boolean> {
  const scroll = options.scroll ?? true;
  if (scroll) pendingId = id;
  focusedFindingId.set(id);
  try {
    await options.navigate?.();
    await tick();
    let mark = markElement(id);
    for (let attempt = 1; !mark && attempt < LOOKUP_ATTEMPTS; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, LOOKUP_WAIT_MS));
      mark = markElement(id);
    }
    if (!mark) return false;
    if (scroll && typeof mark.scrollIntoView === "function") mark.scrollIntoView({ block: "center" });
    flash(mark);
    return true;
  } finally {
    if (pendingId === id) pendingId = null;
  }
}

function flash(mark: HTMLElement): void {
  mark.classList.remove(FLASH_CLASS);
  // Re-adding in the same frame would not restart the animation.
  void mark.offsetWidth;
  mark.classList.add(FLASH_CLASS);
  window.setTimeout(() => mark.classList.remove(FLASH_CLASS), FLASH_MS);
}
