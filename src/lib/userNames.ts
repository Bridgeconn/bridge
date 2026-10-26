import { writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";

/**
 * The workspace's users by id, so a history row can name its reviewer instead
 * of printing a 36-character actor id (#313). Filled from the existing
 * `users.list`; an id this device does not know stays an id (see
 * `actorDisplayName` in utils/reviewLabels.ts).
 */
export const userNames = writable<Record<string, string>>({});

let inFlight: Promise<void> | null = null;

/** Best effort: a failed or unavailable list leaves the names as they were,
 *  and the history keeps showing ids. Concurrent callers share one request. */
export function loadUserNames(): Promise<void> {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const listed = await bridge.usersList();
      const names: Record<string, string> = {};
      for (const user of listed?.users ?? []) {
        if (user.userId && user.displayName?.trim()) names[user.userId] = user.displayName.trim();
      }
      userNames.set(names);
    } catch {
      // keep what we had: ids are still shown
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}
