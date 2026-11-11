import { describe, expect, it } from "vitest";
import { GO_TO_INVALID, parseGoTo, resolveVerse, verseMissing } from "../../goTo";

const CHAPTERS = ["1", "2", "3"];

describe("parseGoTo", () => {
  it("reads a bare verse as a verse of the chapter on show", () => {
    expect(parseGoTo(" 4 ", "2", CHAPTERS)).toEqual({ ok: true, chapter: "2", verse: "4" });
    expect(parseGoTo("3-4", "2", CHAPTERS)).toEqual({ ok: true, chapter: "2", verse: "3-4" });
    expect(parseGoTo("3a", "2", CHAPTERS)).toEqual({ ok: true, chapter: "2", verse: "3a" });
  });

  it("reads chapter and verse with a colon, a full stop or a space; a chapter alone with a trailing colon", () => {
    for (const typed of ["1:4", "1.4", "1 4", "1 : 4"]) {
      expect(parseGoTo(typed, "2", CHAPTERS)).toEqual({ ok: true, chapter: "1", verse: "4" });
    }
    expect(parseGoTo("3:", "2", CHAPTERS)).toEqual({ ok: true, chapter: "3", verse: null });
  });

  it("refuses what is not a chapter or verse", () => {
    for (const typed of ["", "   ", "abc", "1:x", "1:2:3", "-4", "1:-", "john 3"]) {
      expect(parseGoTo(typed, "2", CHAPTERS)).toEqual({ ok: false, error: GO_TO_INVALID });
    }
  });

  it("names a chapter the book does not have", () => {
    expect(parseGoTo("40:1", "2", CHAPTERS)).toEqual({ ok: false, error: "Chapter 40 is not in this book." });
    // Mid book switch: the chapter on show is not in the new book's list.
    expect(parseGoTo("4", "99", CHAPTERS)).toEqual({ ok: false, error: "Chapter 99 is not in this book." });
  });
});

describe("resolveVerse", () => {
  const VERSES = ["1-3", "4", "5a", "5b", "6"];

  it("finds the verse itself, or the bridge or segment that holds it", () => {
    expect(resolveVerse("4", VERSES)).toBe("4");
    expect(resolveVerse("2", VERSES)).toBe("1-3");
    expect(resolveVerse("1-3", VERSES)).toBe("1-3");
    expect(resolveVerse("5", VERSES)).toBe("5a");
    expect(resolveVerse("5B", VERSES)).toBe("5b");
  });

  it("returns null for a verse the chapter does not have", () => {
    expect(resolveVerse("7", VERSES)).toBeNull();
    expect(resolveVerse("2-3", VERSES)).toBeNull();
    expect(verseMissing("7", "2")).toBe("Verse 7 is not in chapter 2.");
  });
});
