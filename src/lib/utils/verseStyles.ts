import type { TextSegment } from "./highlight";

/**
 * Character styles in the reader (#213). The engine's `VerseDisplay.styles`
 * lists every character style that opened and closed in the verse (`\it`,
 * `\nd`, `\wj`, a nested `\+it` ...) as a range over the plain text; the
 * frontend only draws them, it never parses USFM (gotcha 14). Layout only,
 * like usfmNotes.ts: the finding segments are split again at every style
 * boundary and each piece says which styles cover it, so the verse markup
 * wraps the piece in the matching classes. Nested styles stack (`st-wj st-it`).
 *
 * Bounds must already be UTF-16 indexes into the rendered text (see
 * utils/verseDisplay.ts plainToUtf16); the engine sends code points.
 */
export interface StyleRange {
  marker: string;
  start: number;
  end: number;
}

/** The class for one style marker: `st-nd`, `st-wj`, `st-it` ... */
export function styleClass(marker: string): string {
  return `st-${marker.toLowerCase()}`;
}

/** The class attribute for a piece's styles, "" when it has none. */
export function styleClasses(markers: string[] | undefined): string {
  return (markers ?? []).map(styleClass).join(" ");
}

/**
 * Split `segments` at the style boundaries inside them and record, on each
 * piece, the markers covering it in the order the engine listed them (outer
 * before inner). A segment with no style boundary inside it comes back as it
 * was, with its `styles` set. A finding's reference number stays on the last
 * piece of its segment only, as withNoteMarkers keeps it.
 */
export function withStyleSpans(segments: TextSegment[], styles: StyleRange[]): TextSegment[] {
  const ranges = styles.filter((s) => s.end > s.start);
  if (!ranges.length) return segments;
  const out: TextSegment[] = [];
  let offset = 0;
  for (const seg of segments) {
    const segStart = offset;
    const segEnd = offset + seg.text.length;
    const cuts = new Set<number>([segStart, segEnd]);
    for (const range of ranges) {
      if (range.start > segStart && range.start < segEnd) cuts.add(range.start);
      if (range.end > segStart && range.end < segEnd) cuts.add(range.end);
    }
    const points = Array.from(cuts).sort((a, b) => a - b);
    for (let i = 0; i < points.length - 1; i += 1) {
      const start = points[i];
      const end = points[i + 1];
      const covering = ranges.filter((r) => r.start <= start && r.end >= end).map((r) => r.marker);
      out.push({
        ...seg,
        text: seg.text.slice(start - segStart, end - segStart),
        numbers: end === segEnd ? seg.numbers : [],
        styles: covering,
      });
    }
    if (points.length < 2) out.push({ ...seg, styles: [] });
    offset = segEnd;
  }
  return out;
}
