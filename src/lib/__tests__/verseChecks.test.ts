import { describe, expect, it } from "vitest";

import { summarizeGreekRoomChapter } from "../verseChecks";
import type { QaFinding } from "../types/finding";

const gr = (id: string, engine: string, status = "open") =>
  ({ id, engine, status, check: engine, severity: "medium", category: "unicode", check_type: "x",
    explanation: "", evidence: [] }) as unknown as QaFinding;

describe("summarizeGreekRoomChapter (#202)", () => {
  it("counts the chapter's checked verses and its open Greek Room findings only", () => {
    const summary = summarizeGreekRoomChapter("1", ["1", "2", "3"], {
      "1:1": [gr("a", "wildebeest"), gr("b", "usfm"), gr("c", "names", "ignored")],
      "1:2": [gr("d", "local"), gr("e", "wildebeest")],
      "2:1": [gr("f", "wildebeest")],
    }, { "1:1": ["wildebeest", "usfm"], "1:2": ["tN"], "2:1": ["wildebeest"] });
    expect(summary).toEqual({ checkedVerses: 1, totalVerses: 3, openFindings: 3 });
  });

  it("is zero for a chapter nothing has run on", () => {
    expect(summarizeGreekRoomChapter("1", ["1", "2"], {}, {})).toEqual({ checkedVerses: 0, totalVerses: 2, openFindings: 0 });
  });
});
