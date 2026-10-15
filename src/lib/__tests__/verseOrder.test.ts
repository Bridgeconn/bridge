import { afterEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";

import { compareVerses, inReadingOrder } from "../verseOrder";
import { chapterVerseNums, currentChapter, verseNums } from "../stores";

// #302: the 0.18.0 walk drew 2 John 1 as 1, 2, 6 ... 13, 3-4, 5a, 5b, because
// the chapter's verse list came from Object.keys of a verse map.
describe("verse reading order", () => {
  afterEach(() => chapterVerseNums.set({}));

  it("puts a bridge and lettered segments at their verse number", () => {
    const scrambled = ["1", "2", "6", "7", "13", "3-4", "5a", "5b", "front"];
    expect([...scrambled].sort(compareVerses)).toEqual(["front", "1", "2", "3-4", "5a", "5b", "6", "7", "13"]);
  });

  it("keeps an already ordered list as the same array", () => {
    const ordered = ["1", "2", "3"];
    expect(inReadingOrder(ordered)).toBe(ordered);
  });

  it("orders what Object.keys returns for a chapter with a bridge and segments", () => {
    const fromEngine = { "1": {}, "2": {}, "3-4": {}, "5a": {}, "5b": {}, "6": {}, "13": {} };
    // What App.svelte receives: integer-like keys first, whatever order was sent.
    expect(Object.keys(fromEngine)).toEqual(["1", "2", "6", "13", "3-4", "5a", "5b"]);
    chapterVerseNums.update((m) => ({ ...m, "1": Object.keys(fromEngine) }));
    currentChapter.set("1");
    expect(get(verseNums)).toEqual(["1", "2", "3-4", "5a", "5b", "6", "13"]);
  });

  it("orders every chapter on set, including a job snapshot's lists", () => {
    chapterVerseNums.set({ "1": ["2", "1"], "2": ["5b", "5a", "4"] });
    expect(get(chapterVerseNums)).toEqual({ "1": ["1", "2"], "2": ["4", "5a", "5b"] });
  });
});
