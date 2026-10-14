// What entering a chapter does about checks (#272, closing #114): nothing
// while a job or Collection QA runs or the chapter is already loaded; the
// stored findings when they still describe the chapter, plus a job for only
// the selected checks they lack; otherwise the chapter job, as before.
import { missingChecks, type CheckBoxId } from "./checkSelection";
import type { StoredChapterFindings } from "./types/finding";

export interface ChapterEntryState {
  loaded: boolean;
  jobActive: boolean;
  collectionRunning: boolean;
}

export type ChapterEntryPlan =
  | { kind: "nothing" }
  | { kind: "read" }
  | { kind: "stored"; run: CheckBoxId[] }
  | { kind: "job"; run: CheckBoxId[] };

/** Before the read: is there anything to do at all? */
export function shouldReadStored(state: ChapterEntryState): boolean {
  return !state.loaded && !state.jobActive && !state.collectionRunning;
}

/** After the read (`stored` null when it failed). */
export function planChapterEntry(
  state: ChapterEntryState, stored: StoredChapterFindings | null, selection: CheckBoxId[],
): ChapterEntryPlan {
  if (!shouldReadStored(state)) return { kind: "nothing" };
  if (!stored?.current) return { kind: "job", run: selection };
  return { kind: "stored", run: missingChecks(stored.checkGroups, selection) };
}
