import { describe, expect, it } from "vitest";
import { openIssueSummary } from "../../verseIssues";
import { lqaFinding } from "./languageQaFixture";
import type { QaFinding } from "../../types/finding";

function finding(overrides: Partial<QaFinding> = {}): QaFinding {
  return {
    id: "f1", project_id: "p1", book: "php", chapter: 1, verse: 6, start_offset: null, end_offset: null,
    original_text: "", engine: "local", check_type: "x", category: "spelling", severity: "low", confidence: 0.5,
    suggested_replacement: null, explanation: "", evidence: [], engine_version: "1", resource_versions: {},
    status: "open", human_comment: null, created_at: "", resolved_at: null, ...overrides,
  };
}

// #383: what the verse row's pill shows.
describe("openIssueSummary (#383)", () => {
  it("is empty for a clear verse", () => {
    expect(openIssueSummary([], [])).toEqual({ count: 0, worst: "info", title: "", tab: "lqa" });
  });

  it("counts open findings and every Language QA finding, and names their sources", () => {
    const summary = openIssueSummary([
      finding({ id: "a", engine: "wildebeest", category: "unicode" }),
      finding({ id: "b", category: "alignment", severity: "medium" }),
      finding({ id: "c", category: "alignment", status: "ignored" }),
      finding({ id: "d", category: "translation_word", status: "accepted" }),
    ], [lqaFinding({ id: "l1" }), lqaFinding({ id: "l2" })]);
    expect(summary.count).toBe(4);
    expect(summary.title).toBe("4 open findings · 1 Greek Room, 1 alignment, 2 Language QA");
    expect(summary.worst).toBe("medium");
    expect(summary.tab).toBe("greekroom");
  });

  it("takes the worst severity across both kinds, and the singular for one", () => {
    expect(openIssueSummary([finding({ severity: "low" })], [lqaFinding({ severity: "high" })]).worst).toBe("high");
    expect(openIssueSummary([finding({ severity: "info" })], []).worst).toBe("info");
    expect(openIssueSummary([finding({ severity: "weird" as never })], []).worst).toBe("low");
    expect(openIssueSummary([finding({ category: "translation_note" })], []).title).toBe("1 open finding · 1 tN");
  });

  it("lands on the tab of the first open finding: Greek Room, tN/tW, or Language QA", () => {
    expect(openIssueSummary([finding({ category: "translation_note" }), finding({ id: "g", engine: "names" })], []).tab).toBe("tntw");
    expect(openIssueSummary([finding({ status: "ignored" }), finding({ id: "g", engine: "usfm" })], []).tab).toBe("greekroom");
    expect(openIssueSummary([], [lqaFinding()]).tab).toBe("lqa");
  });
});
