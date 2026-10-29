// How long a QA report build will take, as a guess. project.report is one
// synchronous request the sidecar answers nothing during, so the app cannot
// ask how far it is; the build time is close to proportional to the book's
// verse count, so the card shows an estimate from the verse count and the
// rate measured on the builds that finished before (this session, and the
// last one kept in localStorage). An estimate, said to be one, never a
// measurement -- a real per-chapter percentage needs the build to become
// an engine job (BUILD_LOG 2026-10-30).

const STORAGE_KEY = "bridge.reportSecondsPerVerse";
// Genesis of a real Bible: 1,533 verses in about 130 s on the maintainer's
// laptop, the figure the dashboard's comments already quote.
const DEFAULT_SECONDS_PER_VERSE = 130 / 1533;
const FALLBACK_VERSES = 800;

let secondsPerVerse = readStored() ?? DEFAULT_SECONDS_PER_VERSE;

function readStored(): number | null {
  try {
    const raw = typeof localStorage === "undefined" ? null : localStorage.getItem(STORAGE_KEY);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** A build finished: fold its rate into the estimate (weighted towards the
 *  latest, so a faster or slower machine is learned in a couple of builds). */
export function recordReportBuild(verseCount: number, seconds: number): void {
  if (!(verseCount > 0) || !(seconds > 0)) return;
  const rate = seconds / verseCount;
  secondsPerVerse = secondsPerVerse === DEFAULT_SECONDS_PER_VERSE ? rate : (secondsPerVerse + rate * 2) / 3;
  try {
    localStorage.setItem(STORAGE_KEY, String(secondsPerVerse));
  } catch {
    // per-viewer convenience only
  }
}

/** Expected seconds for a book of `verseCount` verses (a book whose count is
 *  unknown is taken as a middling one). Never under five seconds, so the bar
 *  always has somewhere to go. */
export function estimateReportSeconds(verseCount: number | null | undefined): number {
  const verses = verseCount && verseCount > 0 ? verseCount : FALLBACK_VERSES;
  return Math.max(5, Math.round(verses * secondsPerVerse));
}

/** For tests: forget what was learned. */
export function resetReportEstimate(): void {
  secondsPerVerse = DEFAULT_SECONDS_PER_VERSE;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
