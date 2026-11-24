import type { VerseDisplay } from "../types/finding";
import { codePointToUtf16 } from "./codePoints";
import type { VersePiece } from "./usfmNotes";

/**
 * Paragraph and poetry lines in the reader (#507). The engine's
 * `VerseDisplay.paras` lists every paragraph marker inside a verse (`\q1`,
 * `\q2`, `\p`, `\d`, `\b` ...) with the place in the plain text where its
 * content starts; the frontend only draws them, it never parses USFM (gotcha
 * 14). Layout only, like usfmNotes.ts and verseStyles.ts: the pieces of a
 * verse are grouped into lines, each line knowing its marker, so the markup
 * can put a `\q2` line on its own line at its own indent.
 *
 * No character is added, dropped or moved: the text of the lines, read in
 * order, is the text of the pieces they were given. Selections and finding
 * offsets index that text, so it has to stay exactly `display.plain`.
 */

/** Where a paragraph's content starts, as a UTF-16 index into the rendered text. */
export interface LineStart {
  marker: string;
  start: number;
}

export interface VerseLine {
  /** The paragraph marker this line is in: "q1", "q2", "p", "d" ... or "" when unknown. */
  marker: string;
  /** A stanza break (`\b`) comes before this line. */
  gap: boolean;
  pieces: VersePiece[];
}

/** The paragraph a verse opens in, and whether a stanza break comes before it. */
export interface VerseOpening {
  marker: string;
  gap: boolean;
}

/** `\b` is a blank line between stanzas: it has no content and no indent of its own. */
const STANZA_BREAK = "b";

/** Markers drawn as ordinary running text: only their line break shows. */
const PLAIN_PARAGRAPHS = new Set(["", "p", "m", "po", "nb", "tr", STANZA_BREAK]);

/** The engine's paragraph positions are code points into `plain`; lines are UTF-16. */
export function lineStartsForLayout(display: VerseDisplay): LineStart[] {
  return (display.paras ?? []).map((para) => ({
    marker: para.marker, start: codePointToUtf16(display.plain, para.position),
  }));
}

/** The class for one paragraph marker: `pl-q1`, `pl-q2`, `pl-d` ... "" when it has none. */
export function lineClass(marker: string): string {
  return marker ? `pl-${marker.toLowerCase()}` : "";
}

/**
 * Whether a verse is drawn as separate lines. A verse of one line in an
 * ordinary paragraph is not: it is drawn as running text, exactly as it was
 * before there were lines.
 */
export function isStructured(lines: VerseLine[]): boolean {
  return lines.length > 1 || lines.some((line) => line.gap || !PLAIN_PARAGRAPHS.has(line.marker));
}

/**
 * The paragraph each verse of a chapter opens in. A verse opens in the last
 * paragraph the verses before it started, so a `\q1` at the end of verse 3 is
 * the paragraph of verse 4's first line. `openers` are the ones no stored
 * verse can say (before the chapter's first verse, after a section heading),
 * which the engine reads from the preserved source; where it has one, it wins.
 * `keys` are the chapter's verse keys in reading order.
 */
export function openingParas(
  keys: string[], displays: Record<string, VerseDisplay>, openers: Record<string, string>,
): Record<string, VerseOpening> {
  const out: Record<string, VerseOpening> = {};
  let marker = "";
  let gap = false;
  for (const key of keys) {
    if (openers[key] !== undefined) {
      marker = openers[key];
      // A heading (or the chapter's start) stands between: no stanza break to draw.
      gap = false;
    }
    out[key] = { marker, gap };
    gap = false;
    const display = displays[key];
    const paras = display?.paras ?? [];
    if (!display || !paras.length) continue;
    const chars = Array.from(display.plain);
    for (let index = 0; index < paras.length; index += 1) {
      const para = paras[index];
      const end = index + 1 < paras.length ? paras[index + 1].position : chars.length;
      const empty = chars.slice(para.position, end).join("").trim() === "";
      if (para.marker === STANZA_BREAK) gap = true;
      else {
        marker = para.marker;
        // Text after a stanza break means the break was inside this verse.
        if (!empty) gap = false;
      }
    }
  }
  return out;
}

function hasContent(pieces: VersePiece[]): boolean {
  return pieces.some((piece) => piece.kind !== "text" || piece.seg.text.trim() !== "");
}

/**
 * Group a verse's pieces into lines. `starts` must already be UTF-16 indexes
 * into the rendered text (lineStartsForLayout). A piece that runs across a
 * line start is split there; a finding's reference number stays on the last
 * part of its piece, as withNoteMarkers and withStyleSpans keep it.
 *
 * A marker with nothing after it starts no line: the `\q1` a verse ends with
 * belongs to the next verse, and its whitespace stays on the line before it.
 * `\b` starts no line either; it sets `gap` on the line that follows.
 */
export function splitIntoLines(pieces: VersePiece[], starts: LineStart[], opening: VerseOpening): VerseLine[] {
  const groups: { marker: string; pieces: VersePiece[] }[] = [{ marker: opening.marker, pieces: [] }];
  let next = 0;
  let offset = 0;
  const openDue = () => {
    while (next < starts.length && starts[next].start <= offset) {
      groups.push({ marker: starts[next].marker, pieces: [] });
      next += 1;
    }
  };

  for (const piece of pieces) {
    openDue();
    if (piece.kind !== "text") {
      groups[groups.length - 1].pieces.push(piece);
      continue;
    }
    const seg = piece.seg;
    const segStart = offset;
    const segEnd = offset + seg.text.length;
    let cursor = segStart;
    while (next < starts.length && starts[next].start < segEnd) {
      const at = starts[next].start;
      if (at > cursor) {
        groups[groups.length - 1].pieces.push({ kind: "text", seg: {
          ...seg, text: seg.text.slice(cursor - segStart, at - segStart), numbers: [],
        } });
        cursor = at;
      }
      groups.push({ marker: starts[next].marker, pieces: [] });
      next += 1;
    }
    groups[groups.length - 1].pieces.push(
      cursor === segStart ? piece : { kind: "text", seg: { ...seg, text: seg.text.slice(cursor - segStart) } },
    );
    offset = segEnd;
  }
  openDue();

  const lines: VerseLine[] = [];
  let gap = opening.gap;
  let held: VersePiece[] = [];
  for (const group of groups) {
    if (!hasContent(group.pieces)) {
      if (group.marker === STANZA_BREAK) gap = true;
      if (lines.length) lines[lines.length - 1].pieces.push(...group.pieces);
      else held.push(...group.pieces);
      continue;
    }
    lines.push({ marker: group.marker, gap, pieces: [...held, ...group.pieces] });
    gap = false;
    held = [];
  }
  if (!lines.length) lines.push({ marker: opening.marker, gap: opening.gap, pieces: held });
  return lines;
}
