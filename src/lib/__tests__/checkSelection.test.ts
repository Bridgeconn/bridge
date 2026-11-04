import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// Elective checks (#251) and Greek Room on demand (#252): which checks a run
// sends, how a run of some checks merges into a verse, and when a verse ticks.
const { runVerseChecks } = vi.hoisted(() => ({ runVerseChecks: vi.fn() }));
vi.mock("../api/bridgeClient", () => ({ bridge: { runVerseChecks } }));

import {
  checksRunNote, coversSelection, groupsOf, mergeFindings, normalizeChecks, toggleCheck,
  selectedEditorChecks, DEFAULT_EDITOR_CHECKS,
} from "../checkSelection";
import { editorChecks } from "../editorPrefs";
import { recheckVerse, runVerseGreekRoom } from "../verseChecks";
import { checkGroupsByVerse, checkStatusByVerse, findingsByVerse } from "../stores";
import type { QaFinding } from "../types/finding";

const finding = (id: string, check: string) => ({ id, check }) as unknown as QaFinding;
const ALL_CHECKS = ["tN", "tW", "alignment", "text", "languageQa"] as const;
const FULL = groupsOf(ALL_CHECKS);

describe("check selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    editorChecks.set([...ALL_CHECKS]);
    findingsByVerse.set({});
    checkGroupsByVerse.set({});
    checkStatusByVerse.set({});
  });

  it("defaults to Language QA, preserves chosen checks, keeps run order, and is never empty", () => {
    expect(DEFAULT_EDITOR_CHECKS).toEqual(["languageQa"]);
    expect(get(selectedEditorChecks)).toEqual(["tN", "tW", "alignment", "text", "languageQa"]);
    expect(normalizeChecks(["greekroom", "tN", "bogus"], DEFAULT_EDITOR_CHECKS)).toEqual(["tN", "greekroom"]);
    expect(normalizeChecks([], DEFAULT_EDITOR_CHECKS)).toEqual([...DEFAULT_EDITOR_CHECKS]);
    toggleCheck(editorChecks, "greekroom", true);
    toggleCheck(editorChecks, "tW", false);
    expect(get(selectedEditorChecks)).toEqual(["tN", "alignment", "text", "languageQa", "greekroom"]);
  });

  it("keeps the findings of the checks a run did not include", () => {
    const existing = [finding("n", "tN"), finding("w", "wildebeest"), finding("u", "usfm"), finding("old", "")];
    const merged = mergeFindings(existing, [finding("w2", "wildebeest")], groupsOf(["greekroom"]));
    expect(merged.map((f) => f.id)).toEqual(["n", "w2"]);
  });

  it("ticks only once every selected check has run, and says Greek Room has not", () => {
    expect(coversSelection(groupsOf(["alignment"]), ALL_CHECKS)).toBe(false);
    expect(coversSelection(FULL, ALL_CHECKS)).toBe(true);
    expect(checksRunNote(undefined)).toBe("");
    expect(checksRunNote(FULL)).toBe(" · Ran: tN, tW, Alignment, USFM and text, Language QA · Greek Room not run");
    expect(checksRunNote([...FULL, ...groupsOf(["greekroom"])])).not.toContain("not run");
  });

  it("a verse re-check merges, records what ran, and ticks only when the selection is covered", async () => {
    findingsByVerse.set({ "1:2": [finding("n", "tN")] });
    runVerseChecks.mockResolvedValue([finding("a", "alignment")]);
    await recheckVerse("1", "2", ["alignment"]);
    expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["alignment"]);
    expect(get(findingsByVerse)["1:2"].map((f) => f.id)).toEqual(["n", "a"]);
    expect(get(checkStatusByVerse)["1:2"]).toBe("pending");

    checkGroupsByVerse.set({ "1:2": FULL });
    await recheckVerse("1", "2", ["alignment"]);
    expect(get(checkStatusByVerse)["1:2"]).toBe("succeeded");
  });

  it("after an edit the run replaces every finding, and Language QA is not sent to verse.runChecks", async () => {
    findingsByVerse.set({ "1:2": [finding("w", "wildebeest"), finding("n", "tN")] });
    checkGroupsByVerse.set({ "1:2": [...FULL, "wildebeest", "usfm", "names"] });
    runVerseChecks.mockResolvedValue([finding("n2", "tN")]);
    await recheckVerse("1", "2", ALL_CHECKS, { replace: true });
    expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["tN", "tW", "alignment", "text"]);
    expect(get(findingsByVerse)["1:2"].map((f) => f.id)).toEqual(["n2"]);
    expect(get(checkGroupsByVerse)["1:2"]).not.toContain("wildebeest");
    expect(checksRunNote(get(checkGroupsByVerse)["1:2"])).toContain("Greek Room not run");
    expect(get(checkStatusByVerse)["1:2"]).toBe("succeeded");
  });

  it("Run Greek Room on a verse asks for greekroom alone and keeps the rest", async () => {
    findingsByVerse.set({ "1:2": [finding("n", "tN")] });
    runVerseChecks.mockResolvedValue([finding("w", "wildebeest")]);
    await runVerseGreekRoom("1", "2");
    expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["greekroom"]);
    expect(get(findingsByVerse)["1:2"].map((f) => f.id)).toEqual(["n", "w"]);
    expect(get(checkGroupsByVerse)["1:2"]).toEqual(expect.arrayContaining(["wildebeest", "usfm", "names"]));
  });

  it("does not call native verse checks when the saved selection is Language QA only", async () => {
    editorChecks.set(["languageQa"]);
    findingsByVerse.set({ "1:2": [finding("old-text", "text")] });
    await recheckVerse("1", "2", ["languageQa"], { replace: true });
    expect(runVerseChecks).not.toHaveBeenCalled();
    expect(get(findingsByVerse)["1:2"]).toEqual([]);
    expect(get(checkGroupsByVerse)["1:2"]).toEqual(["languageQa"]);
    expect(get(checkStatusByVerse)["1:2"]).toBe("succeeded");
  });
});
