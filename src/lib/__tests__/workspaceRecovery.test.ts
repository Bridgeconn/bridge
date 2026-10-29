import { describe, expect, it } from "vitest";

import { workspaceRecoveryNotice, workspaceRecoverySummary } from "../workspaceRecovery";

// #338: the startup notice names the quarantined file, what happened, the
// rediscovery, what was lost and the hub re-pull. Nothing after a healthy open.
describe("workspaceRecoveryNotice", () => {
  const base = {
    at: "2026-10-27T10:00:00Z", error: "file is not a database",
    quarantined: "workspace.quarantined-20261027T100000Z.sqlite3",
    backup: "", backupWrittenAt: "", backupError: "", lost: [] as string[],
  };

  it("is empty after a healthy open", () => {
    expect(workspaceRecoveryNotice(null)).toBe("");
    expect(workspaceRecoveryNotice(undefined)).toBe("");
    expect(workspaceRecoveryNotice({ ...base, outcome: "" })).toBe("");
  });

  it("describes a restore from the last-good backup", () => {
    const text = workspaceRecoveryNotice({
      ...base, outcome: "restored", backup: "workspace.last-good.sqlite3", backupWrittenAt: "2026-10-26T08:00:00Z",
      lost: ["changes made since the backup was written"], rediscoveredManaged: 3,
      hubRepull: { state: "done", users: 4 },
    });
    expect(text).toContain("set aside as workspace.quarantined-20261027T100000Z.sqlite3");
    expect(text).toContain("restored from the last-good backup written");
    expect(text).toContain("3 projects in the projects folder were rediscovered");
    expect(text).toContain("Lost: changes made since the backup was written.");
    expect(text).toContain("re-pulled from the hub (4)");
  });

  it("describes a rebuild with no backup and a hub that must be rejoined", () => {
    const text = workspaceRecoveryNotice({
      ...base, outcome: "rebuilt", rediscoveredManaged: 1,
      lost: ["users and their roles", "the device id"],
      hubRepull: { state: "not-joined", detail: "Rejoin the hub from Settings > Team: the hub address was in the rebuilt database." },
    });
    expect(text).toContain("No last-good backup existed yet, so a new database was built.");
    expect(text).toContain("1 project in the projects folder was rediscovered");
    expect(text).toContain("Lost: users and their roles; the device id.");
    expect(text).toContain("Rejoin the hub from Settings > Team");
  });

  it("names a damaged backup and a failed re-pull", () => {
    const text = workspaceRecoveryNotice({
      ...base, outcome: "rebuilt", backupError: "malformed", backupQuarantined: "workspace.quarantined-x-backup.sqlite3",
      hubRepull: { state: "failed", error: "The hub answered 403." },
    });
    expect(text).toContain("The last-good backup was damaged too (set aside as workspace.quarantined-x-backup.sqlite3)");
    expect(text).toContain("could not be re-pulled from the hub: The hub answered 403.");
  });
});

describe("workspaceRecoverySummary (the dialog's content)", () => {
  const base = {
    at: "2026-10-27T10:00:00Z", error: "file is not a database",
    quarantined: "workspace.quarantined-20261027T100000Z.sqlite3",
    backup: "", backupWrittenAt: "", backupError: "", lost: [] as string[],
  };

  it("is null after a healthy open, so no dialog mounts", () => {
    expect(workspaceRecoverySummary(null)).toBeNull();
    expect(workspaceRecoverySummary({ ...base, outcome: "" })).toBeNull();
  });

  it("structures a restore: title, headline, the quarantine name, the backup time, the count", () => {
    const summary = workspaceRecoverySummary({
      ...base, outcome: "restored", backup: "workspace.last-good.sqlite3", backupWrittenAt: "2026-10-26T08:00:00Z",
      lost: ["changes made since the backup was written"], rediscoveredManaged: 202, hubRepull: { state: "done", users: 4 },
    })!;
    expect(summary.title).toBe("Workspace restored");
    expect(summary.headline).toContain("restored from its last-good backup");
    expect(summary.facts[0]).toEqual({ label: "Damaged file set aside as", value: "workspace.quarantined-20261027T100000Z.sqlite3" });
    expect(summary.facts.map((f) => f.label)).toContain("Backup written");
    expect(summary.facts.find((f) => f.label.startsWith("Rediscovered"))?.value).toBe("202 project books");
    expect(summary.lost).toEqual(["changes made since the backup was written"]);
    expect(summary.hub).toContain("(4)");
    expect(summary.needsAction).toBe(false);
  });

  it("structures a rebuild with no backup and flags a hub that must be rejoined", () => {
    const summary = workspaceRecoverySummary({
      ...base, outcome: "rebuilt", rediscoveredManaged: 1, lost: ["users and their roles", "the device id"],
      hubRepull: { state: "not-joined", detail: "Rejoin the hub from Settings > Team: the hub address was in the rebuilt database." },
    })!;
    expect(summary.title).toBe("Workspace rebuilt");
    expect(summary.headline).toContain("No last-good backup existed yet");
    expect(summary.facts.find((f) => f.label.startsWith("Rediscovered"))?.value).toBe("1 project book");
    expect(summary.lost).toHaveLength(2);
    expect(summary.needsAction).toBe(true);
  });

  it("names a damaged backup", () => {
    const summary = workspaceRecoverySummary({
      ...base, outcome: "rebuilt", backupError: "malformed", backupQuarantined: "workspace.quarantined-x-backup.sqlite3",
    })!;
    expect(summary.headline).toContain("backup was damaged too");
    expect(summary.facts.map((f) => f.value)).toContain("workspace.quarantined-x-backup.sqlite3");
  });
});
