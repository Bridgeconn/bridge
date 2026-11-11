import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import EditorHeader from "../EditorHeader.svelte";
import { rawView } from "../../editorPrefs";

describe("EditorHeader (#489)", () => {
  beforeEach(() => rawView.set(false));

  it("names the chapter", () => {
    render(EditorHeader, { props: { chapter: "3", total: 4 } });
    expect(screen.getByRole("heading", { name: "Chapter 3 of 4" })).toBeInTheDocument();
  });

  it("carries the Raw USFM toggle, which shows its state and is saved", async () => {
    render(EditorHeader, { props: { chapter: "1", total: 4 } });
    const raw = screen.getByRole("button", { name: "Raw USFM" });
    expect(raw).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(true);
    expect(raw).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("bridge.editor.rawView.v1")).toBe("true");
    await fireEvent.click(raw);
    expect(get(rawView)).toBe(false);
    expect(raw).toHaveAttribute("aria-pressed", "false");
  });

  // jsdom lays nothing out, so this pins the rule, not the rendering: the
  // header must not shrink in its column and stays at the top if that
  // column's own scroller moves.
  it("is styled to stay at the top of the panel", () => {
    const source: string = readFileSync(resolve("src/lib/components/EditorHeader.svelte"), "utf8");
    const rule = /\.editor-header\s*\{([^}]*)\}/.exec(source)?.[1] ?? "";
    expect(rule).toContain("position: sticky");
    expect(rule).toContain("top: 0");
    expect(rule).toContain("flex: none");
  });

  it("the overflow menu no longer offers Raw USFM", () => {
    const app: string = readFileSync(resolve("src/App.svelte"), "utf8");
    expect(app).not.toContain("Raw USFM");
    expect(app).toContain("<EditorHeader");
  });
});
