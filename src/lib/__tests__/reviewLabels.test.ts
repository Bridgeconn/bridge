import { describe, expect, it } from "vitest";

import { LEGACY_HUMAN_LABEL, actorDisplayId, actorDisplayName, actorLabel } from "../utils/reviewLabels";

describe("actorDisplayName (#313)", () => {
  const names = { "04592b9d-9d9b-4232-aac1-03b353afedd1": "Benz" };
  it("names a known id, keeps an unknown id, and leaves legacy:human alone", () => {
    expect(actorDisplayName("04592b9d-9d9b-4232-aac1-03b353afedd1", names)).toBe("Benz");
    expect(actorDisplayName("9143bbc0-b361-4d9b-a51e-de0f59348478", names)).toBe("9143bbc0-b361-4d9b-a51e-de0f59348478");
    expect(actorDisplayName("human", { human: "Someone" })).toBe(LEGACY_HUMAN_LABEL);
    expect(actorDisplayName(undefined, names)).toBe("");
  });
});

describe("legacy:human rendering (#237)", () => {
  it("shows a row written before identity existed as legacy:human, never as a person", () => {
    expect(actorDisplayId("human")).toBe(LEGACY_HUMAN_LABEL);
    expect(actorLabel("HUMAN", "human")).toBe("HUMAN · legacy:human");
  });

  it("leaves every real id and every other actor alone", () => {
    expect(actorDisplayId("9143bbc0-b361-4d9b-a51e-de0f59348478")).toBe("9143bbc0-b361-4d9b-a51e-de0f59348478");
    expect(actorDisplayId("")).toBe("");
    expect(actorDisplayId(undefined)).toBe("");
    expect(actorLabel("AI", "gpt-5.6")).toBe("AI · gpt-5.6");
    expect(actorLabel(undefined, undefined)).toBe("Unknown actor");
  });
});
