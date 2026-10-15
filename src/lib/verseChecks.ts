// One verse's checks re-run in place (#251, #252): after an edit, an
// alignment save, a tN/tW selection, or Run Greek Room on the verse. The run's
// groups replace only their own findings, the verse remembers what has run,
// and its ✓ shows only once every selected check has.
import { derived, get, writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { chapterVerseNums, checkGroupsByVerse, checkStatusByVerse, currentChapter, findingsByVerse, verseKey } from "./stores";
import { coversSelection, editorCheckList, groupsOf, mergeFindings } from "./checkSelection";
import type { QaFinding } from "./types/finding";

/** The verse key a Run Greek Room on one verse is working on, or "". */
export const greekRoomVerseRunning = writable("");

export interface RecheckOptions {
  /** After an edit: findings of the checks not re-run were about the old
   *  text, so they go, and the verse's run record starts again. */
  replace?: boolean;
  /** Groups that ran by another route (Language QA's own pass after an edit). */
  alsoRan?: readonly string[];
}

/** Re-run `checks` on one verse; resolves to the verse's findings now. A
 *  failure rejects and leaves the verse's findings as they were. */
export async function recheckVerse(chapter: string, verse: string, checks: readonly string[],
                                   { replace = false, alsoRan = [] }: RecheckOptions = {}): Promise<QaFinding[]> {
  const key = verseKey(chapter, verse);
  const engineChecks = checks.filter((check) => check !== "languageQa");
  const fresh = engineChecks.length ? await bridge.runVerseChecks(chapter, verse, engineChecks) : [];
  const groups = [...groupsOf(checks), ...alsoRan];
  let merged: QaFinding[] = [];
  findingsByVerse.update((all) => {
    merged = replace ? [...fresh] : mergeFindings(all[key], fresh, groups);
    return { ...all, [key]: merged };
  });
  let ran: string[] = [];
  checkGroupsByVerse.update((all) => {
    ran = replace ? [...new Set(groups)] : [...new Set([...(all[key] ?? []), ...groups])];
    return { ...all, [key]: ran };
  });
  checkStatusByVerse.update((all) => ({
    ...all, [key]: coversSelection(ran, editorCheckList()) ? "succeeded" : "pending",
  }));
  return merged;
}

/** Run Greek Room on one verse (#252): Wildebeest on its text, and the book's
 *  USFM and names results as last scanned (a chapter or book run rescans). */
export async function runVerseGreekRoom(chapter: string, verse: string): Promise<void> {
  const key = verseKey(chapter, verse);
  if (get(greekRoomVerseRunning)) return;
  greekRoomVerseRunning.set(key);
  try {
    await recheckVerse(chapter, verse, ["greekroom"]);
  } finally {
    greekRoomVerseRunning.set("");
  }
}

/** #202: where the result of a Greek Room run lands without a click on the
 *  verse's mark. Per chapter: how many of its verses have had Greek Room run
 *  (a verse run, a chapter or book job) and how many Greek Room findings are
 *  open across them. Read by the Review panel's Greek Room tab, and meant for
 *  the status bar beside Language QA (App.svelte). */
export interface GreekRoomChapterSummary {
  /** Verses of the chapter Greek Room has run on. */
  checkedVerses: number;
  /** Verses in the chapter. */
  totalVerses: number;
  /** Open Greek Room findings (Wildebeest, USFM, names) across the chapter. */
  openFindings: number;
}

const GREEK_ROOM_ENGINES = new Set(["wildebeest", "usfm", "names"]);

export function summarizeGreekRoomChapter(
  chapter: string, verses: readonly string[], findings: Record<string, QaFinding[]>,
  ran: Record<string, string[]>,
): GreekRoomChapterSummary {
  let checkedVerses = 0;
  let openFindings = 0;
  for (const verse of verses) {
    const key = verseKey(chapter, verse);
    if ((ran[key] ?? []).includes("wildebeest")) checkedVerses += 1;
    openFindings += (findings[key] ?? []).filter((f) => GREEK_ROOM_ENGINES.has(f.engine) && f.status === "open").length;
  }
  return { checkedVerses, totalVerses: verses.length, openFindings };
}

export const greekRoomChapterSummary = derived(
  [currentChapter, chapterVerseNums, findingsByVerse, checkGroupsByVerse],
  ([chapter, nums, findings, ran]) => summarizeGreekRoomChapter(chapter, nums[chapter] ?? [], findings, ran),
);
