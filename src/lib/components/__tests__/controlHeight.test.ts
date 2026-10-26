// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #377: one control height in the top bar and the report header. jsdom does
// not lay out, so what is pinned is the token and which rules take it, read
// from the stylesheets on disk (the pattern of stackingLayers.test.ts).
const indexCss = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8");
const component = (name: string): string =>
  readFileSync(resolve(process.cwd(), "src/lib/components", `${name}.svelte`), "utf-8");

/** The declaration block of the rule written as `<selector> {` at the start of a line. */
function rule(source: string, selector: string): string {
  const start = source.indexOf(`
  ${selector} {`);
  if (start < 0) throw new Error(`no rule for ${selector}`);
  const open = source.indexOf("{", start);
  return source.slice(open + 1, source.indexOf("}", open));
}

describe("control height (#377)", () => {
  it("defines --control-h as 28px in index.css", () => {
    expect(indexCss).toMatch(/--control-h:\s*28px;/);
  });

  it("sizes every top-bar control from the token, with an inherited font and a flat line box", () => {
    const topBar = component("TopBar");
    for (const selector of [".btn", ".sync-status", ".select", ".goto", ".chapter-step"]) {
      const block = rule(topBar, selector);
      expect(block, selector).toContain("height: var(--control-h)");
      expect(block, selector).toContain("font: inherit");
      expect(block, selector).toContain("line-height: 1");
      expect(block, selector).toContain("box-sizing: border-box");
    }
    for (const selector of [".btn", ".sync-status", ".goto", ".chapter-step"]) {
      const block = rule(topBar, selector);
      expect(block, selector).toContain("display: inline-flex");
      expect(block, selector).toContain("align-items: center");
    }
    expect(rule(topBar, ".btn")).not.toMatch(/padding:\s*6px/);
  });

  it("gives the report screen's Generate report button and the Export summary the same height", () => {
    const report = component("ProjectReportScreen");
    const button = rule(report, ".small-button");
    const summary = rule(report, ".export summary");
    for (const block of [button, summary]) {
      expect(block).toContain("height: var(--control-h)");
      expect(block).toContain("display: inline-flex");
      expect(block).toContain("align-items: center");
      expect(block).toContain("box-sizing: border-box");
    }
    expect(button).toContain("font: inherit");
    expect(button).toContain("font-size: var(--fs-2xs)");
  });
});
