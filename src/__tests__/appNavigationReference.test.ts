import { describe, expect, it } from "vitest";

// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import appSource from "../App.svelte?raw";

describe("App.svelte publishes Bridge's verse to Paratext and Logos (#110)", () => {
  it("computes navigationReference from the stores named in the reactive statement", () => {
    // Svelte 4 re-runs a `$:` statement only for the names written in it. A
    // no-argument call that read the stores inside a function ran once at
    // mount, and a verse change in Bridge never reached Paratext (seen on the
    // installed 0.16.0 with Paratext 9.5, 2026-10-14). jsdom cannot mount
    // App.svelte, so this pins the statement itself.
    const statement = (appSource as string).match(/^\s*\$:\s*navigationReference\s*=\s*(.+);\s*$/m);
    expect(statement, "the $: navigationReference statement").not.toBeNull();
    for (const store of ["$project", "$currentChapter", "$selectedVerse"]) {
      expect(statement![1]).toContain(store);
    }
  });
});

describe("App.svelte re-reads the open chapter after an Align with AI run (#517)", () => {
  it("keeps the selected verse", () => {
    // With no verse given, activateChapter selects the chapter's first verse,
    // and an alignment tab that follows the editor is rebuilt on verse 1: its
    // range, filter and scroll are lost (Joel, 2026-11-25). jsdom cannot mount
    // App.svelte, so this pins the call itself.
    const block = (appSource as string).match(/\$: if \(\$autoAlignFinished && [\s\S]*?\n  \}\r?\n/);
    expect(block, "the $: autoAlignFinished statement").not.toBeNull();
    expect(block![0]).toContain("activateChapter($currentChapter, get(selectedVerse) ?? undefined)");
    expect(block![0]).not.toMatch(/activateChapter\(\$currentChapter\)/);
  });
});
