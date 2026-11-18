import { describe, expect, it } from "vitest";
import { aiWindowLabel } from "../aiReviewUi";

describe("aiWindowLabel (#502)", () => {
  it("names the verses of a request that holds several", () => {
    expect(aiWindowLabel({ state: "running", currentChapter: "1", currentWindow: ["4", "5", "6", "7"] }))
      .toBe("Verses 1:4–7 are being reviewed together in one request");
  });

  it("says nothing for one verse, no window, a finished job or no job", () => {
    expect(aiWindowLabel({ state: "running", currentChapter: "1", currentWindow: ["4"] })).toBe("");
    expect(aiWindowLabel({ state: "running", currentChapter: "1", currentWindow: [] })).toBe("");
    // An engine older than #502 reports no window at all.
    expect(aiWindowLabel({ state: "running", currentChapter: "1" })).toBe("");
    expect(aiWindowLabel({ state: "succeeded", currentChapter: null, currentWindow: ["4", "5"] })).toBe("");
    expect(aiWindowLabel(null)).toBe("");
  });
});
