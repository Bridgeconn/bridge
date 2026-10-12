import { describe, expect, it } from "vitest";
import { MAX_BUSY_TIMEOUTS, checkFailureMessage, isBusyTimeout } from "../checkMonitor";

describe("check monitor (#210)", () => {
  it("reads both forms of the sidecar's timeout as a busy sidecar", () => {
    expect(isBusyTimeout(new Error("sidecar request 'checks.status' timed out"))).toBe(true);
    expect(isBusyTimeout("Request 'checks.status' timed out after 30s")).toBe(true);
    expect(isBusyTimeout(new Error("No active check job"))).toBe(false);
  });

  it("gives up on a silent sidecar after about five minutes of 30-second timeouts", () => {
    expect(MAX_BUSY_TIMEOUTS * 30).toBeGreaterThanOrEqual(300);
  });

  it("words a stopped check plainly, with the sidecar's text as the detail", () => {
    const timedOut = checkFailureMessage(new Error("sidecar request 'checks.status' timed out"));
    expect(timedOut).toMatch(/^Bridge stopped answering while checking\. Your text is not affected; press Retry/);
    expect(timedOut).toContain("(Details: sidecar request 'checks.status' timed out)");
    expect(checkFailureMessage("No active check job")).toMatch(/^Checking stopped because of an error\./);
  });
});
