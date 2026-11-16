import { describe, expect, it } from "vitest";
import { BACKUPS_SHOWN, backupChange, backupLabel, backupTime } from "../alignmentBackups";

// Local-time dates on both sides, so the test does not depend on the zone.
const at = (y: number, m: number, d: number, h: number, min: number) => new Date(y, m - 1, d, h, min);
const clock = (date: Date) => date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

describe("alignment backup labels", () => {
  const now = at(2026, 11, 16, 12, 0);

  it("says Today, Yesterday, or the date, in local time", () => {
    const today = at(2026, 11, 16, 11, 23), yesterday = at(2026, 11, 15, 23, 59), older = at(2026, 11, 10, 9, 5);
    expect(backupTime(today.toISOString(), now)).toBe(`Today ${clock(today)}`);
    expect(backupTime(yesterday.toISOString(), now)).toBe(`Yesterday ${clock(yesterday)}`);
    expect(backupTime(older.toISOString(), now)).toContain("2026");
    expect(backupTime(older.toISOString(), now)).toContain(clock(older));
  });

  it("shows a timestamp it cannot read as it came", () => {
    expect(backupTime("not a date", now)).toBe("not a date");
  });

  it("names the change in plain words, and an unknown one generally", () => {
    expect(backupChange("realign")).toBe("before a word was placed");
    expect(backupChange("unalign")).toBe("before a word was removed");
    expect(backupChange("restore")).toBe("before an undo");
    expect(backupChange("something_new")).toBe("before a change");
  });

  it("joins the two, and lists ten", () => {
    const saved = at(2026, 11, 16, 11, 23);
    expect(backupLabel({ timestamp: saved.toISOString(), operation: "realign" }, now)).toBe(`Today ${clock(saved)} · before a word was placed`);
    expect(BACKUPS_SHOWN).toBe(10);
  });
});
