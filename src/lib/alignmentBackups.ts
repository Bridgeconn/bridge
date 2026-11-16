// The Word alignment bar's "Go back to an earlier version" list (2026-11-16,
// Joel): each backup is the verse as it was just before one change. The engine
// sends the newest 20 with a UTC timestamp and its own name for the change;
// the menu lists the newest BACKUPS_SHOWN in the reviewer's time and words.
// Display only: every backup stays on disk, and Undo still steps through them.

export const BACKUPS_SHOWN = 10;

/** The engine's `_save_alignment` operation names (bridge_service.py,
 *  alignment_reset.py, alignment_source_split.py). */
const CHANGES: Record<string, string> = {
  realign: "before a word was placed",
  unalign: "before a word was removed",
  restore: "before an undo",
  splitSource: "before source words were joined or split",
  ai_propose_apply: "before a suggestion was applied",
  ai_auto_align: "before an automatic alignment",
  ai_auto_revert: "before an automatic alignment was undone",
  reset: "before a reset",
  restoreReset: "before a reset was undone",
};

const startOfDay = (date: Date): number => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** "Today 11:23", "Yesterday 16:05" or "14 Nov 2026, 16:05", in local time.
 *  A timestamp that does not parse is shown as it came. */
export function backupTime(timestamp: string, now: Date = new Date()): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Yesterday ${time}`;
  return `${date.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })}, ${time}`;
}

export function backupChange(operation: string): string {
  return CHANGES[operation] ?? "before a change";
}

export function backupLabel(item: { timestamp: string; operation: string }, now: Date = new Date()): string {
  return `${backupTime(item.timestamp, now)} · ${backupChange(item.operation)}`;
}
