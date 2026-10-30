import type { WorkspaceRecovery } from "./api/bridgeClient";

/** #338: the one-time startup notice for a recovered workspace database, as
 *  one plain paragraph: what was set aside, what happened (restored from the
 *  last-good backup, or rebuilt), that the projects folder was rediscovered,
 *  what was lost, and what the hub re-pull did. Never an error. */
export function workspaceRecoveryNotice(recovery: WorkspaceRecovery | null | undefined): string {
  if (!recovery || !recovery.outcome) return "";
  const parts: string[] = [];
  parts.push(`Bridge's workspace database was damaged and has been set aside as ${recovery.quarantined}.`);
  if (recovery.outcome === "restored") {
    const when = recovery.backupWrittenAt ? ` written ${formatWhen(recovery.backupWrittenAt)}` : "";
    parts.push(`It was restored from the last-good backup${when}.`);
  } else {
    parts.push(
      recovery.backupError
        ? `The last-good backup was damaged too (set aside as ${recovery.backupQuarantined ?? "a quarantine file"}), so a new database was built.`
        : "No last-good backup existed yet, so a new database was built.",
    );
  }
  if (typeof recovery.rediscoveredManaged === "number") {
    const n = recovery.rediscoveredManaged;
    parts.push(`${n} project${n === 1 ? "" : "s"} in the projects folder ${n === 1 ? "was" : "were"} rediscovered.`);
  } else if (recovery.registryError) {
    parts.push(`The projects folder could not be rediscovered: ${recovery.registryError}`);
  }
  if (recovery.lost && recovery.lost.length > 0) {
    parts.push(`Lost: ${recovery.lost.join("; ")}.`);
  }
  const repull = recovery.hubRepull;
  if (repull?.state === "pending") parts.push("Users and roles are being re-pulled from the hub.");
  else if (repull?.state === "done") parts.push(`Users and roles were re-pulled from the hub (${repull.users ?? 0}).`);
  else if (repull?.state === "failed") parts.push(`Users and roles could not be re-pulled from the hub: ${repull.error ?? "unknown error"}. They will be re-pulled on the next sync.`);
  else if (repull?.state === "not-joined" && repull.detail) parts.push(repull.detail);
  return parts.join(" ");
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** One line of the recovery dialog's fact list. */
export interface RecoveryFact { label: string; value: string }

/** The recovery dialog's content (#338, redesigned 2026-10-29): a headline
 *  for the outcome, the facts a maintainer would ask for, the list of what
 *  was lost, and the hub re-pull's state as its own line. The same
 *  information as `workspaceRecoveryNotice`, structured for a dialog. Null
 *  after a healthy open, so the dialog never mounts. */
export interface RecoverySummary {
  title: string;
  headline: string;
  facts: RecoveryFact[];
  lost: string[];
  hub: string;
  /** True when the user has something to do (rejoin the hub). */
  needsAction: boolean;
}

export function workspaceRecoverySummary(recovery: WorkspaceRecovery | null | undefined): RecoverySummary | null {
  if (!recovery || !recovery.outcome) return null;
  const restored = recovery.outcome === "restored";
  const facts: RecoveryFact[] = [{ label: "Damaged file set aside as", value: recovery.quarantined }];
  let headline: string;
  if (restored) {
    headline = "Your workspace was restored from its last-good backup.";
    if (recovery.backupWrittenAt) facts.push({ label: "Backup written", value: formatWhen(recovery.backupWrittenAt) });
  } else if (recovery.backupError) {
    headline = "The last-good backup was damaged too, so a new workspace was built.";
    if (recovery.backupQuarantined) facts.push({ label: "Damaged backup set aside as", value: recovery.backupQuarantined });
  } else {
    headline = "No last-good backup existed yet, so a new workspace was built.";
  }
  if (typeof recovery.rediscoveredManaged === "number") {
    const n = recovery.rediscoveredManaged;
    facts.push({ label: "Rediscovered in the projects folder", value: `${n} project book${n === 1 ? "" : "s"}` });
  } else if (recovery.registryError) {
    facts.push({ label: "Projects folder", value: `could not be rediscovered: ${recovery.registryError}` });
  }
  let hub = "";
  let needsAction = false;
  const repull = recovery.hubRepull;
  if (repull?.state === "pending") hub = "Users and roles are being re-pulled from the hub.";
  else if (repull?.state === "done") hub = `Users and roles were re-pulled from the hub (${repull.users ?? 0}).`;
  else if (repull?.state === "failed") hub = `Users and roles could not be re-pulled from the hub: ${repull.error ?? "unknown error"}. They will be re-pulled on the next sync.`;
  else if (repull?.state === "not-joined" && repull.detail) { hub = repull.detail; needsAction = true; }
  return {
    title: restored ? "Workspace restored" : "Workspace rebuilt",
    headline,
    facts,
    lost: recovery.lost ?? [],
    hub,
    needsAction,
  };
}
