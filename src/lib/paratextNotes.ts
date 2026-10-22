// #357: per-verse Paratext note counts for the verse list badge. Read a
// chapter at a time from paratext.notesForChapter into
// paratextNoteCountsByVerse (verseKey()-keyed, cleared by resetBookState()).
// While the engine's index is still building, the chapter is asked again a
// few times; a late answer for a chapter the reviewer has left is dropped.
import { get } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { currentChapter, paratextNoteCountsByVerse, project, verseKey } from "./stores";
import type { ParatextNoteCount } from "./types/paratext";

const RETRY_MS = 2000;
const MAX_TRIES = 30;

let generation = 0;

/** Load `chapter`'s counts. Never throws: a book that is not linked to
 *  Paratext simply has none. */
export async function loadParatextNoteCounts(chapter: string, tries = MAX_TRIES): Promise<void> {
  const mine = ++generation;
  const path = get(project)?.path;
  for (let attempt = 0; attempt < tries; attempt++) {
    let result;
    try {
      result = await bridge.paratextNotesForChapter(chapter);
    } catch {
      return;
    }
    if (mine !== generation || get(project)?.path !== path || get(currentChapter) !== chapter) return;
    if (!result || result.state === "unavailable" || result.state === "error") return;
    if (result.state === "ready" || result.state === "stale" || attempt === tries - 1) {
      paratextNoteCountsByVerse.update((all) => {
        const next = Object.fromEntries(Object.entries(all).filter(([key]) => !key.startsWith(`${chapter}:`)));
        for (const [verse, count] of Object.entries(result.counts)) next[verseKey(chapter, verse)] = count;
        return next;
      });
      if (result.state === "ready") return;
    }
    await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
    if (mine !== generation) return;
  }
}

/** The verse numbers a Bridge verse covers: "3" -> [3], a bridge "3-5" ->
 *  [3, 4, 5], "4a" -> [4]. Paratext anchors a note on one verse number. */
export function verseAnchors(verse: string): string[] {
  const match = /^\s*(\d+)[a-z]?(?:\s*-\s*(\d+)[a-z]?)?/.exec(verse);
  if (!match) return [];
  const first = Number(match[1]);
  const last = Math.max(first, Number(match[2] ?? first));
  return Array.from({ length: Math.min(last - first + 1, 200) }, (_, i) => String(first + i));
}

/** The open/resolved threads on a Bridge verse (summed over a bridge). */
export function noteCountFor(
  counts: Record<string, ParatextNoteCount>, chapter: string, verse: string,
): ParatextNoteCount {
  const total = { open: 0, resolved: 0 };
  for (const anchor of verseAnchors(verse)) {
    const count = counts[verseKey(chapter, anchor)];
    if (count) {
      total.open += count.open;
      total.resolved += count.resolved;
    }
  }
  return total;
}
