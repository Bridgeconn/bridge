// Elective checks (#251) and Greek Room on demand (#252).
//
// A box is one elective check. Its id is the name the engine takes
// (checks.start, collection.runChecks, verse.runChecks), and every finding
// carries the group it came from (`check`). A run of some checks replaces only
// those groups' findings for a verse and keeps the rest; the engine does the
// same to the stored snapshot. Greek Room is Wildebeest plus the book USFM and
// names scans, and runs last.
import { derived, get } from "svelte/store";
import { collectionChecks, editorChecks } from "./editorPrefs";
import type { QaFinding } from "./types/finding";

export type CheckBoxId = "tN" | "tW" | "alignment" | "text" | "languageQa" | "greekroom";

export const CHECK_BOXES: ReadonlyArray<{ id: CheckBoxId; label: string; title: string }> = [
  { id: "tN", label: "Translation Notes", title: "translationNotes items still to check, stale or invalidated" },
  { id: "tW", label: "Translation Words", title: "translationWords items still to check, stale or invalidated" },
  { id: "alignment", label: "Alignment", title: "Alignment integrity, Word Alignment state, possible omissions and additions" },
  { id: "text", label: "USFM and text", title: "Unbalanced or redundant USFM markers in the verse, repeated words" },
  { id: "languageQa", label: "Language QA", title: "The language pack's spelling, sandhi, punctuation and other rules" },
  { id: "greekroom", label: "Greek Room", title: "Wildebeest character checks and the book's USFM structure and name spellings. The slowest; runs last" },
];

const ORDER = CHECK_BOXES.map((box) => box.id);
const LABELS: Record<string, string> = {
  tN: "tN", tW: "tW", alignment: "Alignment", text: "USFM and text",
  languageQa: "Language QA", greekroom: "Greek Room",
};
/** The finding groups each box refreshes; mirrors check_jobs.groups_ran. */
const BOX_GROUPS: Record<CheckBoxId, string[]> = {
  tN: ["tN", "tc"],
  tW: ["tW", "tc"],
  alignment: ["alignment"],
  text: ["text"],
  languageQa: ["languageQa"],
  greekroom: ["wildebeest", "usfm", "names"],
};

/** Known boxes only, in run order (Greek Room last); never empty. */
export function normalizeChecks(ids: readonly string[], fallback: readonly CheckBoxId[]): CheckBoxId[] {
  const known = ORDER.filter((id) => ids.includes(id));
  return known.length ? known : [...fallback];
}

export const DEFAULT_EDITOR_CHECKS: readonly CheckBoxId[] = ["tN", "tW", "alignment", "text", "languageQa"];
export const DEFAULT_COLLECTION_CHECKS: readonly CheckBoxId[] = [...DEFAULT_EDITOR_CHECKS, "greekroom"];

export const selectedEditorChecks = derived(editorChecks, (ids) => normalizeChecks(ids, DEFAULT_EDITOR_CHECKS));
export const selectedCollectionChecks = derived(collectionChecks, (ids) => normalizeChecks(ids, DEFAULT_COLLECTION_CHECKS));

export function toggleCheck(store: typeof editorChecks, id: CheckBoxId, on: boolean): void {
  store.update((ids) => (on ? [...new Set([...ids, id])] : ids.filter((other) => other !== id)));
}

/** The editor's current selection, for a run starting now. */
export function editorCheckList(): CheckBoxId[] {
  return get(selectedEditorChecks);
}

/** The finding groups a run of `checks` refreshes. */
export function groupsOf(checks: readonly string[]): string[] {
  const groups = new Set<string>();
  for (const check of checks) for (const group of BOX_GROUPS[check as CheckBoxId] ?? [check]) groups.add(group);
  return [...groups];
}

/** The group a finding belongs to; a finding without the tag (none should
 *  reach the editor) counts as refreshed by any run, as before #251. */
function groupOf(finding: QaFinding): string {
  return finding.check ?? "";
}

/** A verse's findings after a run of `groups`: the run's own, plus the
 *  earlier ones of every group it did not run. */
export function mergeFindings(existing: readonly QaFinding[] | undefined, fresh: readonly QaFinding[], groups: readonly string[]): QaFinding[] {
  const ran = new Set(groups);
  const freshIds = new Set(fresh.map((finding) => finding.id));
  const kept = (existing ?? []).filter((finding) => {
    const group = groupOf(finding);
    return group !== "" && !ran.has(group) && !freshIds.has(finding.id);
  });
  return [...kept, ...fresh];
}

/** Has every box of `selection` run on a verse whose run groups are `ran`? */
export function coversSelection(ran: readonly string[] | undefined, selection: readonly string[]): boolean {
  const have = new Set(ran ?? []);
  return groupsOf(selection).every((group) => have.has(group));
}

/** Which boxes ran, by name, from a verse's run groups. */
function boxesRan(ran: readonly string[]): CheckBoxId[] {
  const have = new Set(ran);
  return ORDER.filter((id) => BOX_GROUPS[id].filter((group) => group !== "tc").every((group) => have.has(group)));
}

/** The verse-number title's note on which checks have run (#251, #252):
 *  empty before any run; otherwise what ran, and "Greek Room not run" until
 *  it has. */
export function checksRunNote(ran: readonly string[] | undefined): string {
  if (!ran || ran.length === 0) return "";
  const done = boxesRan(ran);
  const parts = [`Ran: ${done.map((id) => LABELS[id]).join(", ") || "nothing"}`];
  if (!done.includes("greekroom")) parts.push("Greek Room not run");
  return ` · ${parts.join(" · ")}`;
}

/** "tN, tW, Alignment" for a progress line. */
export function checkListLabel(checks: readonly string[]): string {
  return checks.map((id) => LABELS[id] ?? id).join(", ");
}
