/** The editor's Go to box (2026-11-11): what the reviewer typed, read as a
 *  verse of the chapter on show ("4") or a chapter and verse ("1:4", "1.4",
 *  "1 4"; "3:" is the chapter alone), and checked against the book. Nothing
 *  here moves the editor; the caller does, once the target is known good. */

export type GoToTarget =
  | { ok: true; chapter: string; verse: string | null }
  | { ok: false; error: string };

export const GO_TO_INVALID = "Invalid chapter or verse. Type a verse (4) or a chapter and verse (1:4).";

/** A verse as USFM may number it: 4, 3a, or a bridge 3-4 (gotcha 12). */
const VERSE = /^\d+[a-z]?(?:-\d+[a-z]?)?$/i;
const CHAPTER = /^\d+[a-z]?$/i;

export function parseGoTo(input: string, currentChapter: string, chapters: readonly string[]): GoToTarget {
  const typed = input.trim();
  if (!typed) return { ok: false, error: GO_TO_INVALID };
  const parts = typed.split(/\s*[:.]\s*|\s+/);
  if (parts.length > 2) return { ok: false, error: GO_TO_INVALID };
  const [chapter, verse] = parts.length === 2 ? parts : [currentChapter, parts[0]];
  if (!CHAPTER.test(chapter) || (verse !== "" && !VERSE.test(verse))) return { ok: false, error: GO_TO_INVALID };
  if (!chapters.includes(chapter)) return { ok: false, error: `Chapter ${chapter} is not in this book.` };
  return { ok: true, chapter, verse: verse === "" ? null : verse };
}

/** The chapter's own id for a typed verse: itself, or the bridge or lettered
 *  segment that holds it ("2" in a chapter whose first verse is "1-3"). */
export function resolveVerse(typed: string, verseIds: readonly string[]): string | null {
  const exact = verseIds.find((id) => id.toLowerCase() === typed.toLowerCase());
  if (exact !== undefined) return exact;
  if (!/^\d+$/.test(typed)) return null;
  const wanted = Number(typed);
  for (const id of verseIds) {
    const match = /^(\d+)[a-z]?(?:-(\d+)[a-z]?)?$/i.exec(id);
    if (!match) continue;
    const first = Number(match[1]);
    const last = match[2] === undefined ? first : Number(match[2]);
    if (wanted >= first && wanted <= last) return id;
  }
  return null;
}

export const verseMissing = (verse: string, chapter: string): string => `Verse ${verse} is not in chapter ${chapter}.`;
