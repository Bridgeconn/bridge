import { describe, expect, it } from "vitest";
import {
  idFor, isLiveGap, liveIssues, liveSuggestions, placedByPass, relationTag, signatureOf, suggestionsForSource,
  verdictView, windowProblem, passLabel, providerProblem, windowJobError,
} from "../autoAlign";
import type { AlignmentContext, AutoAlignSuggestion, AutoAlignVerdict } from "../types/finding";

function ctx(overrides: Partial<AlignmentContext> = {}): AlignmentContext {
  return {
    chapter: "1", verse: "4",
    alignment: { alignments: [], wordBank: [] },
    topTokens: [{ id: "H001", word: "πάντοτε", occurrence: 1, occurrences: 1 }, { id: "H002", word: "τῷ", occurrence: 1, occurrences: 1 }],
    bottomTokens: [{ id: "T001", word: "எப்பொழுதும்", occurrence: 1, occurrences: 1 }],
    groups: [{ id: "G001", topIds: ["H001"], bottomIds: [] }, { id: "G002", topIds: ["H002"], bottomIds: [] }],
    status: "untouched", completionState: "pending", sourceAvailable: true, sourceMessage: "",
    sourceDirection: "ltr", targetDirection: "ltr", issues: [], canComplete: false, history: [],
    chapterStatus: { complete: 0, complete_cross_verse: 0, partial: 0, untouched: 1, invalid: 0 },
    gaps: { sourceUnmatched: 2, targetUnmatched: 1 },
    crossVerseLinks: [], crossVerseGroups: [], crossVerseAccountedIds: [], crossVerseRealizedIds: [],
    crossVerseAccounted: 0, crossVerseRealized: 0, fullyAccounted: false,
    nullDecisions: { source: [], target: [] }, accountedBy: { tc: 0, crossVerse: 0, null: 0 }, accounted: false,
    ...overrides,
  };
}

const VERDICT: AutoAlignVerdict = {
  chapter: "1", verse: "4", verdict: "NEEDS_REVIEW", runId: "aa-1", applyRequested: true,
  issues: [{ kind: "POSSIBLE_OMISSION", side: "source", signature: "πάντοτε␟1␟1", word: "πάντοτε", id: "H001", note: "no 'always'" }],
  suggestions: [], applied: { groups: [], links: [], nulls: [] }, window: ["3", "4"], createdAt: "",
};
const SUMMARY = { verdict: "NEEDS_REVIEW" as const, runId: "aa-1", createdAt: "", stale: false, issues: 1, suggestions: 0 };

describe("autoAlign helpers", () => {
  it("names a token by its tC signature and finds its current id", () => {
    expect(signatureOf({ word: "τῷ", occurrence: 1, occurrences: 2 })).toBe("τῷ␟1␟2");
    expect(idFor(ctx(), "source", "τῷ␟1␟1")).toBe("H002");
    expect(idFor(ctx(), "target", "gone␟1␟1")).toBeNull();
  });

  it("a null decision closes the gap, so its issue stops being live", () => {
    expect(isLiveGap(ctx(), "source", "πάντοτε␟1␟1")).toBe(true);
    expect(liveIssues(ctx(), VERDICT)).toHaveLength(1);
    const decided = ctx({ nullDecisions: { source: [{ id: "H001", decisionId: "d", word: "πάντοτε", reason: "IMPLICIT", note: "", origin: "human", state: "active", stale: false }], target: [] } });
    expect(isLiveGap(decided, "source", "πάντοτε␟1␟1")).toBe(false);
    expect(liveIssues(decided, VERDICT)).toEqual([]);
  });

  it("the verdict card: idle before a pass, review with counts, clean when nothing is left", () => {
    expect(verdictView(ctx(), null).tone).toBe("idle");
    const review = verdictView(ctx({ autoAlign: SUMMARY }), VERDICT);
    expect(review.tone).toBe("review");
    expect(review.lines[0]).toBe("1 possible omission");
    const clean = verdictView(
      ctx({ autoAlign: { ...SUMMARY, verdict: "ALIGNED_CLEAN" }, accounted: true, groups: [{ id: "G001", topIds: ["H001"], bottomIds: ["T001"] }, { id: "G002", topIds: ["H002"], bottomIds: [] }],
        nullDecisions: { source: [{ id: "H002", decisionId: "d", word: "τῷ", reason: "GRAMMATICAL", note: "article", origin: "ai-auto", state: "active", stale: false }], target: [] } }),
      { ...VERDICT, verdict: "ALIGNED_CLEAN", issues: [] },
    );
    expect(clean.tone).toBe("clean");
    expect(clean.lines).toEqual(["All words in this verse", "1 grammatical"]);
  });

  it("an edit after the pass marks a verse with leftovers as stale", () => {
    expect(verdictView(ctx({ autoAlign: { ...SUMMARY, stale: true } }), VERDICT).tone).toBe("stale");
  });

  it("a suggestion drops away once its word has a home", () => {
    const s: AutoAlignSuggestion = {
      kind: "link", status: "UNCERTAIN", votes: { "source-first": true, "target-first": false },
      source: { side: "source", chapter: "1", verse: "4", signature: "πάντοτε␟1␟1", word: "πάντοτε", id: "H001" },
      target: { side: "target", chapter: "1", verse: "4", signature: "எப்பொழுதும்␟1␟1", word: "எப்பொழுதும்", id: "T001" },
      token: null, reason: "", note: "", confidence: 50,
    };
    const verdict = { ...VERDICT, suggestions: [s] };
    expect(liveSuggestions(ctx(), verdict)).toHaveLength(1);
    expect(suggestionsForSource([s], "4", "πάντοτε␟1␟1")).toHaveLength(1);
    const aligned = ctx({ groups: [{ id: "G001", topIds: ["H001"], bottomIds: ["T001"] }, { id: "G002", topIds: ["H002"], bottomIds: [] }] });
    expect(liveSuggestions(aligned, verdict)).toEqual([]);
  });

  it("tags and ledger lookups", () => {
    expect(relationTag(1, 1)).toBe("");
    expect(relationTag(2, 1)).toBe("2:1");
    const verdict = { ...VERDICT, applied: { groups: [{ tops: ["a␟1␟1", "b␟1␟1"], bottoms: ["x␟1␟1"] }], links: [], nulls: [] } };
    expect(placedByPass(verdict, "a␟1␟1", ["x␟1␟1"])).toBe(true);
    expect(placedByPass(verdict, "a␟1␟1", ["y␟1␟1"])).toBe(false);
  });

  it("a window is 1-5 consecutive verses", () => {
    const verses = ["1", "2", "3-4", "5", "6", "7", "8"];
    expect(windowProblem(["2", "3-4"], verses)).toBe("");
    expect(windowProblem([], verses)).toMatch(/at least one/);
    expect(windowProblem(["1", "2", "3-4", "5", "6", "7"], verses)).toMatch(/at most 5/);
    expect(windowProblem(["1", "5"], verses)).toMatch(/consecutive/);
  });
});

describe("window job progress and provider failures (#243)", () => {
  const pass = (number: number | null, stage = "") => ({ state: "running" as const, currentPass: { number, of: 2, direction: "", stage } });

  it("labels the pass the status reports", () => {
    expect(passLabel(null)).toBe("Starting…");
    expect(passLabel({ state: "queued", currentPass: null })).toBe("Starting…");
    expect(passLabel(pass(1))).toBe("Aligning… pass 1 of 2");
    expect(passLabel(pass(2))).toBe("Aligning… pass 2 of 2");
    expect(passLabel(pass(null, "reconcile"))).toBe("Comparing the two passes…");
    expect(passLabel(pass(null, "apply"))).toBe("Writing what both passes agree on…");
    expect(passLabel({ state: "running", currentPass: null })).toBe("Aligning…");
  });

  it("takes the failed window's own error over the job's count", () => {
    const results = { "1:1-3": { chapter: "1", verses: ["1", "2", "3"], status: "failed" as const, error: "The read operation timed out" } };
    expect(windowJobError({ results }, "1 window(s) failed.")).toBe("The read operation timed out");
    expect(windowJobError({ results: {} }, "1 window(s) failed.")).toBe("1 window(s) failed.");
    expect(windowJobError(null, "boom")).toBe("boom");
  });

  it("words a timeout, a 429 and an unreachable provider plainly, and leaves anything else raw", () => {
    expect(providerProblem("The read operation timed out")).toBe("The AI provider did not answer within 4 minutes; nothing was changed.");
    expect(providerProblem("Network error contacting OpenAI: timed out")).toContain("did not answer within 4 minutes");
    expect(providerProblem("OpenAI API error HTTP 429: Rate limit reached for gpt-5.6")).toBe(
      "The AI provider is limiting requests right now; nothing was changed. Try again in a minute.");
    expect(providerProblem("Network error contacting OpenAI: [WinError 10061] No connection could be made because the target machine actively refused it"))
      .toBe("Could not reach the AI provider; nothing was changed. Check the internet connection and Settings › AI provider.");
    expect(providerProblem("Network error contacting OpenAI: [Errno 11001] getaddrinfo failed")).toContain("Could not reach");
    expect(providerProblem("OpenAI API error HTTP 401: Incorrect API key provided")).toBeNull();
    expect(providerProblem("Verse/project data changed while AI was preparing alignment")).toBeNull();
  });
});
