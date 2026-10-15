import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { get } from "svelte/store";

import { project, targetLang } from "../../stores";
import type { ProjectInfo } from "../../types/finding";

// Read from disk: vitest serves a CSS import, `?raw` included, as an empty
// module, unlike the `.svelte?raw` reads other tests make; and under jsdom
// import.meta.url is not a file URL. Vitest runs from the repo root.
const indexCss = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8");

// #286: the target face in the project language's own order. jsdom does not
// choose platform fonts, so the rendered-font check (which font draws a "."
// beside Gurmukhi letters) is the Edge/WebView2 probe recorded on the issue;
// what can be pinned here is the rule that drives it and the attribute that
// selects it.

/** The declaration block of the rule whose selector list contains `selector`. */
function ruleFor(selector: string): string {
  const match = indexCss.match(new RegExp(`^[^{}]*${selector.replace(/[()]/g, "\\$&")}[^{}]*\\{([^}]*)\\}`, "m"));
  return match?.[1] ?? "";
}

function familiesOf(declaration: string): string[] {
  return (declaration.match(/"[^"]+"|var\(--[a-z-]+\)/g) ?? []).map((item) => item.replace(/"/g, ""));
}

describe("targetLang", () => {
  it("is the project's language code, lower-cased, and absent without one", () => {
    project.set(null);
    expect(get(targetLang)).toBeUndefined();
    project.set({ path: "/p", bookId: "gen", targetLanguageId: "PAN" } as ProjectInfo);
    expect(get(targetLang)).toBe("pan");
    project.set({ path: "/p", bookId: "gen", targetLanguageId: "" } as ProjectInfo);
    expect(get(targetLang)).toBeUndefined();
    project.set(null);
  });
});

describe("index.css target font order (#286)", () => {
  it("keeps Vijaya first in the default stack, so Tamil is as it was", () => {
    expect(familiesOf(ruleFor(":root").match(/--font-indic:([^;]*);/)?.[1] ?? "")[0]).toBe("Vijaya");
    expect(indexCss).toMatch(/--font-target:\s*var\(--font-indic\),\s*var\(--font-ui\);/);
    expect(indexCss).not.toMatch(/:lang\(ta\)/);
  });

  it("puts the Gurmukhi faces before Vijaya for a Punjabi project, under both ISO codes", () => {
    for (const code of ["pa", "pan"]) {
      const families = familiesOf(ruleFor(`:lang(${code})`));
      expect(families.slice(0, 2)).toEqual(["Nirmala UI", "Noto Serif Gurmukhi"]);
      expect(families.indexOf("var(--font-indic)")).toBeGreaterThan(1);
      expect(families).toContain("var(--font-ui)");
    }
  });

  it("does the same for the other Indic pack languages and their aliases", () => {
    const expected: Record<string, string> = {
      hi: "Noto Serif Devanagari", hin: "Noto Serif Devanagari",
      ml: "Noto Serif Malayalam", mal: "Noto Serif Malayalam",
      or: "Noto Serif Oriya", ori: "Noto Serif Oriya", ory: "Noto Serif Oriya", od: "Noto Serif Oriya",
    };
    for (const [code, face] of Object.entries(expected)) {
      expect(familiesOf(ruleFor(`:lang(${code})`)).slice(0, 2), code).toEqual(["Nirmala UI", face]);
    }
  });

  it("leaves the UI chrome stack alone", () => {
    expect(indexCss).toMatch(/--font-ui: -apple-system, "Inter", Segoe UI, Helvetica, Arial, var\(--font-indic\), sans-serif;/);
  });
});
