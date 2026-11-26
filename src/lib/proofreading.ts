// The proofreading run (#505): chosen books of the open collection are read
// one after another by Bridge's AI, through the bundled toolkit
// (proofreading.start). This module owns the run's status and its poll, as
// collectionQa.ts does for Collection QA, so the dashboard bar and the rest of
// the app (which is read-only while a run is active) read one source.
//
// It polls only while a run is active, every POLL_MS, and not at all
// otherwise: the performance contract's "zero pollers awake when idle".
import { writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import type { ProofreadingSnapshot } from "./types/proofreading";

export const POLL_MS = 1000;
const ACTIVE = new Set(["queued", "running", "cancelling"]);

/** The latest snapshot (idle: each book's last recorded run), or null before the first read. */
export const proofreading = writable<ProofreadingSnapshot | null>(null);
/** True while a run is active: book switching, editing and checks are held. */
export const proofreadingRunning = writable(false);

let timer: ReturnType<typeof setTimeout> | undefined;
let sequence = 0;

function publish(snapshot: ProofreadingSnapshot): boolean {
  proofreading.set(snapshot);
  const active = ACTIVE.has(snapshot.state);
  proofreadingRunning.set(active);
  return active;
}

async function poll(jobId: string, ticket: number): Promise<void> {
  try {
    const snapshot = await bridge.proofreadingStatus(jobId);
    if (ticket !== sequence) return;
    if (publish(snapshot)) timer = setTimeout(() => void poll(jobId, ticket), POLL_MS);
  } catch {
    if (ticket === sequence) timer = setTimeout(() => void poll(jobId, ticket), POLL_MS * 5);
  }
}

/** Read the current state once (the last recorded runs when nothing is running),
 * and keep polling if a run is active -- e.g. after the dashboard was reopened mid-run. */
export async function refreshProofreading(): Promise<void> {
  const ticket = ++sequence;
  if (timer) clearTimeout(timer);
  const snapshot = await bridge.proofreadingStatus("");
  if (ticket !== sequence) return;
  if (publish(snapshot) && snapshot.jobId) timer = setTimeout(() => void poll(snapshot.jobId, ticket), POLL_MS);
}

/** `books`: the ids to read, or null for every book. `force`: read a book
 *  again though it is unchanged since its recorded run. */
export async function startProofreading(books: string[] | null, force = false): Promise<void> {
  const ticket = ++sequence;
  if (timer) clearTimeout(timer);
  const snapshot = await bridge.proofreadingStart(books, force);
  if (ticket !== sequence) return;
  if (publish(snapshot)) timer = setTimeout(() => void poll(snapshot.jobId, ticket), POLL_MS);
}

// An answer that arrives after the run was let go of (the project closed:
// stopProofreading) or re-read (a refresh or a new start) is dropped. Published
// late it would mark a run as active with nothing polling it, and the app,
// which is read-only while one is, would stay held.
export async function pauseProofreading(paused: boolean): Promise<void> {
  const ticket = sequence;
  const snapshot = await bridge.proofreadingPause(paused);
  if (ticket === sequence) publish(snapshot);
}

export async function cancelProofreading(): Promise<void> {
  const ticket = sequence;
  const snapshot = await bridge.proofreadingCancel();
  if (ticket === sequence) publish(snapshot);
}

/** Stop polling (project closed); the next refresh starts afresh. */
export function stopProofreading(): void {
  ++sequence;
  if (timer) clearTimeout(timer);
  timer = undefined;
  proofreading.set(null);
  proofreadingRunning.set(false);
}

/** "1.2k", "3.4M": a token count for a status line. */
export function compactCount(value: number | undefined | null): string {
  const n = Number(value ?? 0);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(n));
}
