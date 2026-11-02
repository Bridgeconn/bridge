// #357: per-verse Paratext note counts for the verse list badge. Read a
// chapter at a time from paratext.notesForChapter into
// paratextNoteCountsByVerse (verseKey()-keyed, cleared by resetBookState()).
// While the engine's index is still building, the chapter is asked again a
// few times; a late answer for a chapter the reviewer has left is dropped.
import { get, writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { revealSidePanel } from "./editorPrefs";
import { currentChapter, paratextNoteCountsByVerse, project, verseKey } from "./stores";
import type { ParatextNoteCount } from "./types/paratext";

// #426: a request from elsewhere in the editor (the verse context menu) to
// write a Paratext note on a verse, optionally on its selected text. The
// notes panel opens its composer with these and clears the request.
export interface ParatextNoteRequest {
  chapter: string;
  verse: string;
  selectedText: string;
}
export const paratextNoteRequest = writable<ParatextNoteRequest | null>(null);

/** Open the Paratext notes panel on `verse` with its composer ready. The
 *  verse is already the selected one when the menu was opened on it. */
export function requestParatextNote(chapter: string, verse: string, selectedText = ""): void {
  paratextNoteRequest.set({ chapter, verse, selectedText });
  revealSidePanel("paratext");
}

/** #426: composer drafts, kept while the reviewer moves between verses and
 *  books in this session (keyed by project path and verse). A draft is
 *  dropped once its note is queued. */
const drafts = new Map<string, { text: string; selectedText: string }>();

export function draftKey(projectPath: string, chapter: string, verse: string): string {
  return `${projectPath}|${verseKey(chapter, verse)}`;
}

export function readDraft(key: string): { text: string; selectedText: string } | null {
  return drafts.get(key) ?? null;
}

export function saveDraft(key: string, draft: { text: string; selectedText: string }): void {
  if (draft.text.trim() || draft.selectedText.trim()) drafts.set(key, draft);
  else drafts.delete(key);
}

export function dropDraft(key: string): void {
  drafts.delete(key);
}

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
