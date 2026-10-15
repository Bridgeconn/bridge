// The signed-in user's role on the open project (#279), for the top bar and
// the reporter banner. Display only: every action is still decided by the
// engine's authorize(), which refuses with a plain message.
import { writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import type { TeamRoles } from "./types/finding";

export const projectRoles = writable<TeamRoles | null>(null);

let sequence = 0;

/** Read team.roles for the open project; null when none is open or it fails. */
export async function refreshProjectRoles(projectOpen: boolean): Promise<void> {
  const ticket = ++sequence;
  if (!projectOpen) {
    projectRoles.set(null);
    return;
  }
  try {
    const roles = await bridge.teamRoles();
    if (ticket === sequence) projectRoles.set(roles);
  } catch {
    if (ticket === sequence) projectRoles.set(null);
  }
}

export const ROLE_NAMES: Record<string, string> = {
  project_admin: "Project admin", editor: "Editor", reporter: "Reporter",
};
