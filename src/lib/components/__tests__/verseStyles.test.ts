/**
 * #213: character styles from the display payload, as layout over the
 * finding segments. The bounds here are UTF-16, the way VerseList hands them
 * over after plainToUtf16; the component test checks the conversion.
 */
import { describe, expect, it } from "vitest";
import { buildSegments, type TextSegment } from "../../utils/highlight";
import { styleClasses, withStyleSpans } from "../../utils/verseStyles";

const plain = (text: string): TextSegment => ({ text, findingIds: [], className: null, title: "", numbers: [] });

describe("withStyleSpans", () => {
  it("splits a segment at style boundaries and names the covering markers, outer first", () => {
    // "the Lord, said so to him." with \nd 4-8, \wj 10-24 and a nested \+it 15-17.
    const text = "the Lord, said so to him.";
    const pieces = withStyleSpans([plain(text)], [
      { marker: "nd", start: 4, end: 8 }, { marker: "wj", start: 10, end: 24 }, { marker: "it", start: 15, end: 17 },
    ]);
    expect(pieces.map((p) => [p.text, p.styles])).toEqual([
      ["the ", []], ["Lord", ["nd"]], [", ", []], ["said ", ["wj"]], ["so", ["wj", "it"]], [" to him", ["wj"]], [".", []],
    ]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
  });

  it("keeps a finding's underline and number where they were", () => {
    const text = "alpha beta gamma";
    const segments = buildSegments(text, [{
      id: "f", project_id: "p", book: "php", chapter: 1, verse: 6, start_offset: 6, end_offset: 10,
      original_text: "beta", engine: "wildebeest", check_type: "x", category: "unicode", severity: "low",
      confidence: 1, suggested_replacement: null, explanation: "e", evidence: [], engine_version: "1",
      resource_versions: {}, status: "open", human_comment: null, created_at: "", resolved_at: null,
    }]);
    // \it over "beta gam": the mark is split where the italic ends? No: the
    // italic covers the whole mark and runs past it into the next segment.
    const pieces = withStyleSpans(segments, [{ marker: "it", start: 6, end: 14 }]);
    expect(pieces.map((p) => [p.text, p.className, p.styles, p.numbers])).toEqual([
      ["alpha ", null, [], []],
      ["beta", "m-gr", ["it"], [1]],
      [" gam", null, ["it"], []],
      ["ma", null, [], []],
    ]);
  });

  it("leaves segments alone when the verse has no styles, and ignores empty ranges", () => {
    const segments = [plain("a"), plain("b")];
    expect(withStyleSpans(segments, [])).toBe(segments);
    expect(withStyleSpans(segments, [{ marker: "it", start: 1, end: 1 }])).toBe(segments);
  });

  it("names classes st-<marker>", () => {
    expect(styleClasses(["wj", "it"])).toBe("st-wj st-it");
    expect(styleClasses(undefined)).toBe("");
  });
});
