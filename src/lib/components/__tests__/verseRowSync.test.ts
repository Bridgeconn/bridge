import { describe, expect, it } from "vitest";

import { levelVerseRows, sideBySide } from "../../verseRowSync";

/** jsdom lays nothing out, so every rectangle here is stubbed: this covers the
 * pairing and the arithmetic, not real rendering. */
function box(el: HTMLElement, left: number, top: number, width: number, height: number) {
  el.getBoundingClientRect = () => ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON() {} }) as DOMRect;
}

function page(columns: { left: number; top: number; rows: Record<string, number> }[]) {
  const root = document.createElement("div");
  const rows: Record<string, HTMLElement>[] = [];
  columns.forEach((column, index) => {
    const col = document.createElement("section");
    col.setAttribute("data-verse-col", String(index));
    box(col, column.left, column.top, 400, 900);
    const made: Record<string, HTMLElement> = {};
    for (const [key, height] of Object.entries(column.rows)) {
      const row = document.createElement("div");
      row.setAttribute("data-verse-row", key);
      box(row, column.left, 0, 400, height);
      col.appendChild(row);
      made[key] = row;
    }
    root.appendChild(col);
    rows.push(made);
  });
  return { root, rows };
}

describe("verseRowSync (#495)", () => {
  it("treats columns as side by side only when they are apart and start level", () => {
    expect(sideBySide({ left: 0, right: 400, top: 10 }, { left: 410, right: 810, top: 10 })).toBe(true);
    expect(sideBySide({ left: 410, right: 810, top: 12 }, { left: 0, right: 400, top: 10 })).toBe(true);
    // Stacked: same horizontal span, one below the other.
    expect(sideBySide({ left: 0, right: 800, top: 10 }, { left: 0, right: 800, top: 500 })).toBe(false);
    // A floating pane overlapping the other.
    expect(sideBySide({ left: 0, right: 400, top: 10 }, { left: 200, right: 600, top: 10 })).toBe(false);
  });

  it("gives the shorter block of each verse the taller one's height", () => {
    const { root, rows } = page([
      { left: 0, top: 0, rows: { title: 30, "7": 300, "8": 120 } },
      { left: 410, top: 0, rows: { title: 30, "7": 90, "8": 260.4 } },
    ]);
    levelVerseRows(root);
    expect(rows[1]["7"].style.minHeight).toBe("300px");
    expect(rows[0]["7"].style.minHeight).toBe("");
    expect(rows[0]["8"].style.minHeight).toBe("260.4px");
    expect(rows[1]["8"].style.minHeight).toBe("");
    expect(rows[0].title.style.minHeight).toBe("");
  });

  // 2026-11-25 (Joel): a drop on verse 2 left the panel on verse 1. While the
  // heights are cleared a column is only as tall as its own words, and the
  // browser moves a panel scrolled past that back up as soon as it is
  // measured. jsdom does not lay out, so that move is made here by hand, in
  // the measurement; the real thing was watched in headless Edge (BUILD_LOG).
  it("puts each panel back where it was scrolled after the pass", () => {
    const { root, rows } = page([
      { left: 0, top: 0, rows: { "1": 400, "2": 400 } },
      { left: 410, top: 0, rows: { "1": 40, "2": 40 } },
    ]);
    const panels = [0, 1].map((index) => {
      const body = document.createElement("div");
      body.setAttribute("data-panel-body", index ? "target" : "source");
      body.appendChild(root.children[0]);
      root.appendChild(body);
      body.scrollTop = 700;
      return body;
    });
    const measure = rows[1]["2"].getBoundingClientRect.bind(rows[1]["2"]);
    rows[1]["2"].getBoundingClientRect = () => { panels[1].scrollTop = 0; return measure(); };
    levelVerseRows(root);
    expect(rows[1]["2"].style.minHeight).toBe("400px");
    expect(panels.map((body) => body.scrollTop)).toEqual([700, 700]);
  });

  it("clears the heights when the columns are stacked, and leaves an unpaired verse alone", () => {
    const { root, rows } = page([
      { left: 0, top: 0, rows: { "7": 300, "9": 50 } },
      { left: 0, top: 900, rows: { "7": 90 } },
    ]);
    rows[1]["7"].style.minHeight = "300px";
    levelVerseRows(root);
    expect(rows[1]["7"].style.minHeight).toBe("");
    expect(rows[0]["9"].style.minHeight).toBe("");
  });
});
