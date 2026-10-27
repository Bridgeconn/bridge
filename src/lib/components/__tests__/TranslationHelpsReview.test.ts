import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { listChecksForVerse, listIssueResolutions, resolveIssueResolutionFromParatext, paratextThreadsFor } =
  vi.hoisted(() => ({
    listChecksForVerse: vi.fn(),
    listIssueResolutions: vi.fn(),
    resolveIssueResolutionFromParatext: vi.fn(),
    paratextThreadsFor: vi.fn(),
  }));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { listChecksForVerse, listIssueResolutions, resolveIssueResolutionFromParatext, paratextThreadsFor },
}));

import TranslationHelpsReview from "../TranslationHelpsReview.svelte";
import { nativeChecksByVerse, aiCheckReviewsByVerse } from "../../stores";
import type { CheckAutomationResult, IssueResolutionRecord, NativeCheckReview } from "../../types/finding";

function check(overrides: Partial<NativeCheckReview> = {}): NativeCheckReview {
  return {
    chapter: "1",
    verse: "19",
    tool: "translationWords",
    groupId: "jesus",
    checkId: "q36v",
    sourceQuote: "Ἰησοῦ Χριστοῦ",
    sourceOccurrence: 1,
    occurrenceNote: "",
    selections: [],
    nothingToSelect: false,
    invalidated: false,
    stale: false,
    selectionStatus: "pending",
    evaluationStatus: "not_run",
    provenance: "none",
    stateFingerprint: "fp",
    automaticSelection: null,
    ...overrides,
  };
}

function applied(): CheckAutomationResult {
  return { outcome: "applied", reason: "" };
}

function skipped(reason: string): CheckAutomationResult {
  return { outcome: "skipped", reason };
}

function mount(checks: NativeCheckReview[]) {
  listChecksForVerse.mockResolvedValue({
    chapter: "1", verse: "19", checks, state: "ready", retryAfterMs: 0, message: "",
    aiReviewState: "current", aiReviews: [], aiQaIssues: [], aiSummary: "",
  });
  return render(TranslationHelpsReview, { props: { chapter: "1", verse: "19" } });
}

/**
 * The engine already decided, per check, whether it could select the words
 * automatically and why not. Until this was rendered, a check the AI declined
 * looked identical to one no AI had ever seen: "Pending", with no explanation.
 */
describe("TranslationHelpsReview automatic-selection outcome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nativeChecksByVerse.set({});
    aiCheckReviewsByVerse.set({});
    listIssueResolutions.mockResolvedValue({ items: [] });
  });

  it("says why a check the AI declined is still pending", async () => {
    mount([check({
      automaticSelection: skipped("AI confidence is below the 82% automatic-selection threshold"),
    })]);

    await waitFor(() => {
      expect(screen.getByText(/Left for you/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/AI confidence is below the 82% automatic-selection threshold/),
    ).toBeInTheDocument();
  });

  it("marks a check the AI selected, and tallies both against the verse", async () => {
    mount([
      check({
        checkId: "q36v",
        selections: [{ text: "यीशु", occurrence: 1, occurrences: 1 }],
        selectionStatus: "selected",
        provenance: "bridge_ai",
        automaticSelection: applied(),
      }),
      check({
        checkId: "zr2k",
        tool: "translationNotes",
        automaticSelection: skipped("Stage 3 mapping is not safe for a verse-local automatic selection"),
      }),
    ]);

    await waitFor(() => {
      expect(screen.getByText(/Selected automatically by the AI review/)).toBeInTheDocument();
    });
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText(/1 selected by AI review/)).toBeInTheDocument();
    expect(screen.getByText("1 pending")).toBeInTheDocument();
  });

  it("does not credit the AI for a selection a human has since taken over", async () => {
    mount([check({
      selections: [{ text: "यीशु", occurrence: 1, occurrences: 1 }],
      selectionStatus: "selected",
      provenance: "human",
      automaticSelection: applied(),
    })]);

    await waitFor(() => {
      expect(screen.getByText("1 of 1")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Selected automatically by the AI review/)).not.toBeInTheDocument();
    expect(screen.queryByText(/selected by AI review/)).not.toBeInTheDocument();
  });

  it("keeps the run-AI-review prompt when no automatic pass has run", async () => {
    mount([check()]);

    await waitFor(() => {
      expect(screen.getByText(/Run AI review to evaluate these checks/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Left for you/)).not.toBeInTheDocument();
  });
});

function resolution(overrides: Partial<IssueResolutionRecord> = {}): IssueResolutionRecord {
  return {
    schemaVersion: 1, resolutionId: "r1", bookId: "psa", chapter: "1", verse: "19", reference: "PSA 1:19",
    check: { tool: "translationWords", groupId: "jesus", checkId: "q36v", sourceQuote: "Ἰησοῦ Χριστοῦ",
      sourceOccurrence: 1, stateFingerprint: "fp" },
    selectedText: "", issueSummary: "Issue", reviewerNote: "Note", proposedCorrection: "", evidence: [],
    status: "open", recheck: { status: "not_run" },
    paratext: { status: "not_queued", messageId: "", attempts: 0, lastError: "", sentAt: "", remoteId: "",
      contentSignature: "sig" },
    history: [{ event: "created", at: "2026-10-27T00:00:00Z", by: "Benz" }],
    createdAt: "2026-10-27T00:00:00Z", updatedAt: "2026-10-27T00:00:00Z",
    ...overrides,
  } as IssueResolutionRecord;
}

describe("TranslationHelpsReview: Mark resolved in Bridge (#358 f)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nativeChecksByVerse.set({});
    aiCheckReviewsByVerse.set({});
  });

  it("updates the card at once: the click's record replaces the old one and the offer goes", async () => {
    listIssueResolutions.mockResolvedValue({ items: [resolution()] });
    paratextThreadsFor.mockResolvedValue({
      state: "ready", pending: [],
      links: [{ kind: "issue_resolution", localId: "r1", threadId: "T1", messageId: "", direction: "paratext_to_bridge",
        thread: { id: "T1", kind: "note", status: "deleted", resolved: true, verseRef: "PSA 1:19", verse: "19",
          users: ["Yesu Selva Benz"], firstDate: "2026-10-26T10:00:00+05:30", lastDate: "2026-10-26T10:01:00+05:30",
          lastUser: "Yesu Selva Benz", excerpt: "Bridge review", selectedText: "", assignedUser: "", tags: [],
          hidden: false, commentCount: 2, contextBefore: "", contextAfter: "",
          comments: [
            { user: "Yesu Selva Benz", date: "2026-10-26T10:00:00+05:30", contents: "Bridge review", status: "todo",
              type: "", assignedUser: null, replyToUser: "", language: "", tagsAdded: [], tagsRemoved: [] },
            { user: "Yesu Selva Benz", date: "2026-10-26T10:01:00+05:30", contents: "", status: "deleted",
              type: "", assignedUser: null, replyToUser: "", language: "", tagsAdded: [], tagsRemoved: [] },
          ] } }],
    });
    resolveIssueResolutionFromParatext.mockResolvedValue({ record: resolution({
      status: "resolved",
      history: [
        { event: "created", at: "2026-10-27T00:00:00Z", by: "Benz" },
        { event: "resolved_from_paratext", at: "2026-10-27T00:01:00Z", by: "Benz", status: "resolved",
          previousStatus: "open", threadId: "T1" },
      ],
    } as Partial<IssueResolutionRecord>) });
    mount([check()]);

    await fireEvent.click(await screen.findByRole("button", { name: "Mark resolved in Bridge" }));

    expect(resolveIssueResolutionFromParatext).toHaveBeenCalledWith("1", "19", "r1", "T1");
    expect(await screen.findByText("Resolved, following Paratext")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark resolved in Bridge" })).toBeNull();
  });
});
