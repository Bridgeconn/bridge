import { describe, expect, it } from "vitest";
import { sourceColumns } from "../alignmentGroups";
import type { AlignmentToken } from "../types/finding";
const token = (id: string, word: string): AlignmentToken => ({ id, word, occurrence: 1, occurrences: 1 });
const sig = (word: string) => `${word}\u241f1\u241f1`;
function separated(direction: "left" | "right", sourceDirection: "ltr" | "rtl"): Parameters<typeof sourceColumns>[0] {
  return { topTokens: [token("H1", "A"), token("H2", "C"), token("H3", "B")], bottomTokens: [],
    groups: [{ id: "G1", topIds: ["H1", "H2"], bottomIds: ["T1"] }, { id: "G2", topIds: ["H3"], bottomIds: [] }],
    sourceDirection, sourceLayout: { order: [sig("A"), sig("B"), sig("C")],
      placements: { [sig("B")]: { direction, members: [sig("A"), sig("B"), sig("C")] } } } };
}
describe("source-group presentation preserves identities", () => {
  it.each(["ltr", "rtl"] as const)("places a separated middle word on the requested physical side in %s", (dir) => {
    const left = sourceColumns(separated("left", dir)).map((c) => c.tokens.map((t) => t.word).join(""));
    const right = sourceColumns(separated("right", dir)).map((c) => c.tokens.map((t) => t.word).join(""));
    expect(left).toEqual(dir === "ltr" ? ["B", "AC"] : ["AC", "B"]);
    expect(right).toEqual(dir === "ltr" ? ["AC", "B"] : ["B", "AC"]);
  });
  it("ignores a dormant placement when undo has restored the joined group", () => {
    const context = separated("right", "ltr");
    context.groups = [{ id: "joined", topIds: ["H1", "H3", "H2"], bottomIds: ["T1"] }];
    expect(sourceColumns(context)).toHaveLength(1);
    expect(sourceColumns(context)[0].ids.sort()).toEqual(["H1", "H2", "H3"]);
  });
});
