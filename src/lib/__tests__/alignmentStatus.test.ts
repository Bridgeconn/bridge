import { describe, expect, it } from "vitest";

import { alignmentStatusLabel, isAlignmentComplete } from "../alignmentStatus";

describe("alignment status (#228)", () => {
  it("counts a verse completed through a cross-verse link as complete, and nothing else", () => {
    expect(isAlignmentComplete("complete")).toBe(true);
    expect(isAlignmentComplete("complete_cross_verse")).toBe(true);
    for (const other of ["partial", "untouched", "invalid", undefined, ""]) {
      expect(isAlignmentComplete(other)).toBe(false);
    }
  });

  it("labels the cross-verse state in words and leaves the others as they are", () => {
    expect(alignmentStatusLabel("complete_cross_verse")).toBe("complete (cross-verse)");
    expect(alignmentStatusLabel("complete")).toBe("complete");
    expect(alignmentStatusLabel("partial")).toBe("partial");
    expect(alignmentStatusLabel("invalid")).toBe("invalid");
    expect(alignmentStatusLabel(undefined)).toBe("untouched");
  });
});
