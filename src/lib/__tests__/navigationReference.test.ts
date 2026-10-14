import { describe, expect, it } from "vitest";

import { bridgeReference } from "../navigationReference";

describe("bridgeReference (#110)", () => {
  it("is the book, chapter and verse Paratext and Logos are sent", () => {
    expect(bridgeReference({ bookId: "gen" }, "1", "5")).toBe("GEN 1:5");
    expect(bridgeReference({ bookId: "1co" }, "13", "4-7")).toBe("1CO 13:4-7");
  });

  it("is empty with no project or no selected verse", () => {
    expect(bridgeReference(null, "1", "5")).toBe("");
    expect(bridgeReference({ bookId: "gen" }, "1", null)).toBe("");
    expect(bridgeReference({ bookId: "gen" }, "1", "")).toBe("");
  });
});
