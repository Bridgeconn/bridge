/**
 * #507: paragraph and poetry lines from the display payload, as layout over
 * a verse's pieces. The displays are the engine's own output for these
 * strings (verseDisplayFixtures.ts), so the positions are what it sends.
 */
import { describe, expect, it } from "vitest";
import type { TextSegment } from "../../utils/highlight";
import type { VersePiece } from "../../utils/usfmNotes";
import { withNoteMarkers } from "../../utils/usfmNotes";
import { withStyleSpans } from "../../utils/verseStyles";
import { plainToUtf16 } from "../../utils/verseDisplay";
import {
  isStructured, lineClass, lineStartsForLayout, openingParas, splitIntoLines, type VerseLine,
} from "../../utils/verseLines";
import type { VerseDisplay } from "../../types/finding";
import { displayFor } from "./verseDisplayFixtures";

const PSALM_3_1 = "Lord, how\n\\q2 many are they \\qs Selah\\qs*\n\\q1";
const STANZA_END = "Many say\n\\b\n\\q1";
const WITH_NOTE = "But you\n\\q2 are a shield\\f + \\ft a note\\f*\n\\q1 my glory";
const TITLE = "a\n\\d A Psalm of David\n\\q1";
const PROSE = "I lay down \\k and slept\\k*.\n\\p";
const TAMIL = "\\q1 கர்த்தாவே,\n\\q2 என் சத்துருக்கள்";

const seg = (text: string, extra: Partial<TextSegment> = {}): TextSegment =>
  ({ text, findingIds: [], className: null, title: "", numbers: [], ...extra });

/** The pieces VerseList builds for a display with no findings. */
function piecesOf(display: VerseDisplay): VersePiece[] {
  const styles = display.styles.map((s) => ({
    marker: s.marker, start: plainToUtf16(display, s.start), end: plainToUtf16(display, s.end),
  }));
  const notes = display.notes.map((n) => ({ ...n, position: plainToUtf16(display, n.position) }));
  return withNoteMarkers(withStyleSpans([seg(display.plain)], styles), notes);
}

function linesOf(raw: string, opening = { marker: "", gap: false }): VerseLine[] {
  const display = displayFor(raw);
  return splitIntoLines(piecesOf(display), lineStartsForLayout(display), opening);
}

const textOf = (line: VerseLine): string =>
  line.pieces.map((piece) => (piece.kind === "text" ? piece.seg.text : "")).join("");

const shape = (lines: VerseLine[]) => lines.map((line) => [line.marker, textOf(line).trim(), line.gap]);

describe("splitIntoLines", () => {
  it("puts each poetry line on its own line under its marker, the first under the opening one", () => {
    const lines = linesOf(PSALM_3_1, { marker: "q1", gap: false });
    expect(shape(lines)).toEqual([["q1", "Lord, how", false], ["q2", "many are they Selah", false]]);
    // The verse's last \q1 has nothing after it: it starts no line here.
    expect(lines).toHaveLength(2);
  });

  it("keeps every character, in order: the lines read back are the plain text", () => {
    for (const raw of [PSALM_3_1, STANZA_END, WITH_NOTE, TITLE, PROSE, TAMIL]) {
      expect(linesOf(raw).map(textOf).join("")).toBe(displayFor(raw).plain);
    }
  });

  it("keeps a character style on the line it is in", () => {
    const [, second] = linesOf(PSALM_3_1);
    const selah = second.pieces.find((piece) => piece.kind === "text" && piece.seg.styles?.includes("qs"));
    expect(selah?.kind === "text" && selah.seg.text).toBe("Selah");
  });

  it("keeps a footnote callout on the line it was lifted from", () => {
    const lines = linesOf(WITH_NOTE);
    expect(shape(lines)).toEqual([["", "But you", false], ["q2", "are a shield", false], ["q1", "my glory", false]]);
    expect(lines.map((line) => line.pieces.filter((piece) => piece.kind === "note").length)).toEqual([0, 1, 0]);
  });

  it("starts no line for a stanza break; a gap is drawn before the line after it", () => {
    // Inside one verse: text, \b, then a new line.
    const display: VerseDisplay = {
      plain: "one\n\ntwo", notes: [], removed: [], styles: [], warnings: [],
      paras: [{ marker: "b", position: 4 }, { marker: "q1", position: 5 }],
    };
    const lines = splitIntoLines([{ kind: "text", seg: seg(display.plain) }], lineStartsForLayout(display), { marker: "q1", gap: false });
    expect(shape(lines)).toEqual([["q1", "one", false], ["q1", "two", true]]);
    // At the end of a verse the break belongs to the next verse (openingParas).
    expect(shape(linesOf(STANZA_END, { marker: "q1", gap: false }))).toEqual([["q1", "Many say", false]]);
  });

  it("draws a gap before the first line when the verse before ended with a stanza break", () => {
    expect(shape(linesOf(PROSE, { marker: "q1", gap: true }))).toEqual([["q1", "I lay down and slept.", true]]);
  });

  it("starts at the verse's own first marker when the verse begins with one", () => {
    expect(shape(linesOf(TAMIL, { marker: "p", gap: false }))).toEqual([
      ["q1", "கர்த்தாவே,", false], ["q2", "என் சத்துருக்கள்", false],
    ]);
  });

  it("reads a psalm title inside a verse as a line of its own", () => {
    expect(shape(linesOf(TITLE))).toEqual([["", "a", false], ["d", "A Psalm of David", false]]);
  });

  it("splits a finding's mark at a line start and keeps its number on the last part", () => {
    const display = displayFor(PSALM_3_1);
    const text = display.plain;
    const cut = text.indexOf("many");
    const marked = seg(text.slice(5, cut + 4), { className: "m-gr", findingIds: ["f"], numbers: [1] });
    const pieces: VersePiece[] = [
      { kind: "text", seg: seg(text.slice(0, 5)) }, { kind: "text", seg: marked },
      { kind: "text", seg: seg(text.slice(cut + 4)) },
    ];
    const lines = splitIntoLines(pieces, lineStartsForLayout(display), { marker: "q1", gap: false });
    const marks = lines.flatMap((line) => line.pieces)
      .filter((piece) => piece.kind === "text" && piece.seg.className === "m-gr")
      .map((piece) => (piece.kind === "text" ? [piece.seg.text, piece.seg.numbers] : []));
    expect(marks).toEqual([[" how\n", []], ["many", [1]]]);
    expect(lines.map(textOf).join("")).toBe(text);
  });

  it("is one line for a verse with no paragraph marker, and for an older engine's display", () => {
    const older = { plain: "alpha beta", notes: [], removed: [], styles: [], warnings: [] } as VerseDisplay;
    const lines = splitIntoLines([{ kind: "text", seg: seg(older.plain) }], lineStartsForLayout(older), { marker: "", gap: false });
    expect(shape(lines)).toEqual([["", "alpha beta", false]]);
    expect(isStructured(lines)).toBe(false);
  });

  it("converts positions past an astral character to UTF-16", () => {
    // Code point 4 of "𝔸 a\nb" is "b"; its UTF-16 index is 5.
    const display: VerseDisplay = {
      plain: "𝔸 a\nb", notes: [], removed: [], styles: [], warnings: [], paras: [{ marker: "q2", position: 4 }],
    };
    expect(lineStartsForLayout(display)).toEqual([{ marker: "q2", start: 5 }]);
    const lines = splitIntoLines([{ kind: "text", seg: seg(display.plain) }], lineStartsForLayout(display), { marker: "q1", gap: false });
    expect(shape(lines)).toEqual([["q1", "𝔸 a", false], ["q2", "b", false]]);
  });
});

describe("isStructured", () => {
  it("is false for one line of ordinary prose and true for poetry, a title or more than one line", () => {
    expect(isStructured(linesOf(PROSE, { marker: "p", gap: false }))).toBe(false);
    expect(isStructured(linesOf(PROSE, { marker: "", gap: false }))).toBe(false);
    expect(isStructured(linesOf(PROSE, { marker: "q1", gap: false }))).toBe(true);
    expect(isStructured(linesOf(PROSE, { marker: "p", gap: true }))).toBe(true);
    expect(isStructured(linesOf(PSALM_3_1))).toBe(true);
    expect(isStructured(linesOf(TITLE))).toBe(true);
  });
});

describe("lineClass", () => {
  it("names the class for a marker, and none for an unknown opening", () => {
    expect(lineClass("q2")).toBe("pl-q2");
    expect(lineClass("")).toBe("");
  });
});

describe("openingParas", () => {
  const displays = {
    "3:1": displayFor(PSALM_3_1), "3:2": displayFor(STANZA_END), "3:3": displayFor(WITH_NOTE),
    "3:4": displayFor(PROSE), "3:5": displayFor("plain verse"),
  };
  const keys = ["3:1", "3:2", "3:3", "3:4", "3:5"];

  it("carries the last paragraph marker of the verses before, starting from the engine's opener", () => {
    const openings = openingParas(keys, displays, { "3:1": "q1" });
    expect(openings["3:1"]).toEqual({ marker: "q1", gap: false });
    // Verse 1 ends with \q1; verse 2 ends with \b then \q1, so verse 3 opens
    // in \q1 after a stanza break; verse 3's last line is \q1; verse 4 ends
    // with \p, which verse 5 opens in.
    expect(openings["3:2"]).toEqual({ marker: "q1", gap: false });
    expect(openings["3:3"]).toEqual({ marker: "q1", gap: true });
    expect(openings["3:4"]).toEqual({ marker: "q1", gap: false });
    expect(openings["3:5"]).toEqual({ marker: "p", gap: false });
  });

  it("takes the engine's opener over the carried one: a heading stands between", () => {
    const openings = openingParas(keys, displays, { "3:1": "q1", "3:3": "p" });
    expect(openings["3:3"]).toEqual({ marker: "p", gap: false });
    expect(openings["3:4"]).toEqual({ marker: "q1", gap: false });
  });

  it("opens in no known paragraph when nothing says, and skips a verse with no display yet", () => {
    const openings = openingParas(["3:9", "3:5"], displays, {});
    expect(openings["3:9"]).toEqual({ marker: "", gap: false });
    expect(openings["3:5"]).toEqual({ marker: "", gap: false });
  });
});
