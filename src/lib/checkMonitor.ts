/** How the check monitor reads a failed checks.status poll (#210).
 *
 *  The sidecar answers one request at a time. A long request ahead of a poll
 *  (opening a book that was never opened, for one) holds it past the desktop's
 *  30-second limit, and the poll fails with "... timed out" although the check
 *  job is still running. That is a busy sidecar, not a failed check, so the
 *  monitor keeps polling; it gives up only when the sidecar stays silent for
 *  MAX_BUSY_TIMEOUTS polls in a row (about five minutes). */

export const MAX_BUSY_TIMEOUTS = 10;

export const BUSY_LABEL = "Waiting for Bridge to finish another task";

export function isBusyTimeout(error: unknown): boolean {
  return /timed out/i.test(error instanceof Error ? error.message : String(error));
}

/** The notice for a check that stopped, in plain words; the sidecar's own text
 *  follows as the detail someone diagnosing it needs. */
export function checkFailureMessage(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  const lead = isBusyTimeout(error)
    ? "Bridge stopped answering while checking."
    : "Checking stopped because of an error.";
  return `${lead} Your text is not affected; press Retry to check again. (Details: ${detail})`;
}
