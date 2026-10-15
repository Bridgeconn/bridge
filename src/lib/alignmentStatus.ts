/**
 * The per-verse alignment status as the UI reads it (#228). The engine's
 * `status` has five values: translationCore's `untouched` / `partial` /
 * `complete`, Bridge's `invalid`, and `complete_cross_verse` -- not complete in
 * translationCore's terms, but every remaining gap is closed by an active
 * cross-verse link or a null decision. The verse ✓ and the chapter tallies
 * treat it as complete; export does not, and nothing here changes that.
 */
import type { AlignmentWorkStatus } from "./types/finding";

export function isAlignmentComplete(status: AlignmentWorkStatus | string | undefined): boolean {
  return status === "complete" || status === "complete_cross_verse";
}

/** The status word for a badge or a title: the engine's value, except that
 * `complete_cross_verse` reads "complete (cross-verse)". */
export function alignmentStatusLabel(status: AlignmentWorkStatus | string | undefined): string {
  if (status === "complete_cross_verse") return "complete (cross-verse)";
  return status || "untouched";
}
