import { describe, expect, it } from "vitest";

import { relativeTime } from "../utils/relativeTime";

const NOW = Date.parse("2026-11-13T12:00:00Z");
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();

describe("relativeTime", () => {
  it("steps from seconds up to years", () => {
    expect(relativeTime(ago(0), NOW)).toBe("just now");
    expect(relativeTime(ago(2), NOW)).toBe("2 sec ago");
    expect(relativeTime(ago(59), NOW)).toBe("59 sec ago");
    expect(relativeTime(ago(60), NOW)).toBe("1 min ago");
    expect(relativeTime(ago(3599), NOW)).toBe("59 min ago");
    expect(relativeTime(ago(3600), NOW)).toBe("1 hr ago");
    expect(relativeTime(ago(86400), NOW)).toBe("1 day ago");
    expect(relativeTime(ago(3 * 86400), NOW)).toBe("3 days ago");
    expect(relativeTime(ago(14 * 86400), NOW)).toBe("2 weeks ago");
    expect(relativeTime(ago(70 * 86400), NOW)).toBe("2 months ago");
    expect(relativeTime(ago(800 * 86400), NOW)).toBe("2 years ago");
  });

  it("reads a future time as just now and an unreadable one as nothing", () => {
    expect(relativeTime(ago(-30), NOW)).toBe("just now");
    expect(relativeTime("", NOW)).toBe("");
    expect(relativeTime(undefined, NOW)).toBe("");
    expect(relativeTime("not a date", NOW)).toBe("");
  });
});
