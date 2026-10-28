// #399: the strip under the top bar during Collection QA. The run's own
// snapshot (collection.qaStatus: books done, percent, time left, paused,
// cancelling) feeds the same checkingProgress store the check job feeds, so
// the strip moves from the editor and the report screen too, and its Cancel
// reaches the collection job, not the chapter job that is not running.
import { get } from "svelte/store";
import { cancelCollectionQa, collectionQa, collectionQaRunning, formatDuration } from "./collectionQa";
import { checkingProgress, type CheckingProgress } from "./stores";
import type { CollectionQaSnapshot } from "./types/collectionQa";

export type StripProgress = Pick<CheckingProgress, "running" | "percent" | "label" | "state">;

/** What the strip shows for an active run: "Collection QA · 3/66 books ·
 *  about 40 min left", the job's own percent, "cancelling" while it is. */
export function collectionStripProgress(snapshot: CollectionQaSnapshot): StripProgress {
  const parts = [`Collection QA · ${snapshot.completedBooks}/${snapshot.totalBooks} books`];
  if (snapshot.state === "cancelling") parts.push("cancelling");
  else if (snapshot.paused) parts.push("paused");
  else if (snapshot.estimatedRemainingSeconds !== null && snapshot.estimatedRemainingSeconds !== undefined) {
    parts.push(`about ${formatDuration(snapshot.estimatedRemainingSeconds)} left`);
  }
  return {
    running: true,
    percent: Math.max(0, Math.min(100, Math.round(snapshot.percent))),
    label: parts.join(" · "),
    state: snapshot.state === "cancelling" ? "cancelling" : "running",
  };
}

/** The strip's line once the run has stopped, by how it stopped. */
export function collectionFinishedLabel(snapshot: CollectionQaSnapshot | null): string {
  if (snapshot?.state === "cancelled") return "Collection QA cancelled";
  if (snapshot?.state === "failed") return `Collection QA failed${snapshot.error ? `: ${snapshot.error}` : ""}`;
  return "Collection QA finished";
}

/** Keep the strip in step with the run for as long as the app lives: while a
 *  run is active the strip is held (checkingProgress.running is what holds
 *  editing, alignment and AI review) and shows the run's own progress; when
 *  it stops, the hold is released with a line saying how. Returns the
 *  unsubscriber. */
export function bindCollectionStrip(): () => void {
  let held = false;
  const stopRunning = collectionQaRunning.subscribe((running) => {
    const snapshot = get(collectionQa);
    if (running && snapshot) {
      held = true;
      checkingProgress.update((p) => ({ ...p, ...collectionStripProgress(snapshot) }));
    } else if (!running && held) {
      held = false;
      // state stays "succeeded" whatever the outcome: the failed/cancelled
      // notice rows offer Retry, which re-runs a chapter job by id, not this run.
      checkingProgress.update((p) => ({ ...p, running: false, label: collectionFinishedLabel(snapshot), state: "succeeded" }));
    }
  });
  const stopSnapshot = collectionQa.subscribe((snapshot) => {
    if (held && snapshot && get(collectionQaRunning)) {
      checkingProgress.update((p) => ({ ...p, ...collectionStripProgress(snapshot) }));
    }
  });
  return () => { stopRunning(); stopSnapshot(); };
}

/** The strip's Cancel: the collection job while one runs, else the check
 *  job the caller holds. Says which it reached. */
export async function cancelStripJob(
  activeJobId: string, cancelCheckJob: (jobId: string) => Promise<void>,
): Promise<"collection" | "checks" | "none"> {
  if (get(collectionQaRunning)) {
    await cancelCollectionQa();
    return "collection";
  }
  if (!activeJobId) return "none";
  await cancelCheckJob(activeJobId);
  return "checks";
}
