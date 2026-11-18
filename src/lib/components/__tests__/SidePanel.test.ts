import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import SidePanel from "../SidePanel.svelte";
import PanelHeader from "../PanelHeader.svelte";
import {
  PANEL_MIN, SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, movePanel, setSidePanel, sidePanelOrder, sidePanels,
} from "../../editorPrefs";

/** jsdom has no PointerEvent: a MouseEvent carries the pointer event's name and fields. */
async function pointer(target: HTMLElement, type: string, clientX = 0): Promise<void> {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, clientX }));
  await tick();
}

function reset(): void {
  for (const id of ["reference", "paratext", "review"] as const) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial, float: null });
  }
  sidePanelOrder.set([...SIDE_PANEL_ORDER]);
}

describe("SIDE_PANEL_LIMITS (#379 item 6)", () => {
  it("gives every panel one minimum width (Language QA, which kept 320, is the Review panel's tab since #487)", () => {
    expect(SIDE_PANEL_ORDER).toEqual(["source", "reference", "paratext", "review"]);
    for (const id of SIDE_PANEL_ORDER) {
      expect(SIDE_PANEL_LIMITS[id].min, id).toBe(PANEL_MIN);
      expect(SIDE_PANEL_LIMITS[id].initial, id).toBeGreaterThanOrEqual(SIDE_PANEL_LIMITS[id].min);
    }
    expect(PANEL_MIN).toBe(260);
  });
});

describe("SidePanel (Benz, 2026-10-09)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 1600 });
    reset();
  });
  afterEach(reset);

  it("caps the width at 45% of the window, and a kept-mounted panel is hidden, not removed, when closed", async () => {
    window.innerWidth = 1000;
    setSidePanel("review", { open: true, width: 700 });
    render(SidePanel, { props: { id: "review", label: "Review", keepMounted: true } });
    const column = document.getElementById("side-panel-review") as HTMLElement;
    expect(column.style.width).toBe("450px");
    setSidePanel("review", { open: false });
    await tick();
    expect(document.getElementById("side-panel-review")?.hidden).toBe(true);
  });
});

// #379 (Benz's item 7): one header bar with a line under it on every panel.
describe("PanelHeader (#379)", () => {
  beforeEach(reset);
  afterEach(reset);

  it("shows the title, carries the hint as its tooltip, and Close closes the column as the View menu does", async () => {
    setSidePanel("reference", { open: true });
    render(PanelHeader, { props: { id: "reference", title: "Reference · OV", hint: "C:/bibles/ov", label: "the Reference panel" } });
    const title = screen.getByRole("heading", { level: 2, name: "Reference · OV" });
    expect(title.getAttribute("title")).toBe("C:/bibles/ov");
    expect(document.querySelector("[data-panel-bar='reference']")).not.toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Close the Reference panel" }));
    expect(get(sidePanels).reference.open).toBe(false);
  });

  // 2026-11-14: a panel is a tab, placed by dragging it (EditorTabs); the
  // tools menu no longer moves a column left or right. The saved order
  // still names every panel: it is the order new tabs are listed in.
  it("offers no column moves in its tools menu, and a saved order that lost a panel gets it back", async () => {
    setSidePanel("reference", { open: true });
    render(PanelHeader, { props: { id: "reference", title: "Reference", label: "the Reference panel" } });
    await fireEvent.click(screen.getByRole("button", { name: "the Reference panel panel tools" }));
    expect(await screen.findByRole("menuitem", { name: "Move to separate window" })).toBeInTheDocument();
    // The floating box inside the window is gone (2026-11-14).
    expect(screen.queryByRole("menuitem", { name: "Float inside Bridge" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Move panel left" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Move panel right" })).toBeNull();
    // A saved order missing a panel (added after the save) is completed.
    sidePanelOrder.set(["review", "source"] as never);
    sidePanelOrder.update((order) => order);
    expect(get(sidePanelOrder)).toEqual(["review", "source"]);
  });

  it("names Close after the title when no label is given, and defers to onClose when one is given", async () => {
    const onClose = vi.fn();
    setSidePanel("paratext", { open: true });
    render(PanelHeader, { props: { id: "paratext", title: "Paratext notes", onClose } });
    await fireEvent.click(screen.getByRole("button", { name: "Close Paratext notes" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(get(sidePanels).paratext.open).toBe(true);
  });

  it("is the first thing every one of the four panels draws, with the actions in its slot", () => {
    const source = (name: string) => readFileSync(resolve(process.cwd(), "src/lib/components", `${name}.svelte`), "utf-8");
    for (const [name, id] of [["SourceTextPanel", "source"], ["ReferencePanel", "reference"],
      ["ParatextNotesPanel", "paratext"], ["ReviewPanel", "review"]] as const) {
      const text = source(name);
      expect(text, name).toMatch(new RegExp(`<PanelHeader id="${id}"`));
      // No panel keeps a header of its own beside the shared one.
      expect(text, name).not.toMatch(/class="(head|pt-head|head-row)"/);
    }
    // #487: Language QA is a tab of the Review panel and draws no bar.
    expect(source("LanguageQaPanel")).not.toContain("<PanelHeader");
    // #488: the rail is gone; nothing mounts or imports it.
    expect(readFileSync(resolve(process.cwd(), "src/App.svelte"), "utf-8")).not.toMatch(/SideRail|editor-toolbar/);
    // One bar: one padding, one title size, one background, one line under it.
    const bar = source("PanelHeader");
    expect(bar).toContain("padding: 0 8px");
    expect(bar).toContain("border-bottom: 1px solid var(--border)");
    expect(bar).toContain("background: var(--surface)");
    expect(bar).toMatch(/\.panel-title \{[^}]*font-size: var\(--fs-xs\)/);
  });

  // Item 6 (Benz, 2026-10-26): one body padding and type scale, one surface.
  // jsdom lays nothing out, so the rules are pinned where they are written.
  it("gives every panel body --surface at --fs-xs, content 12px from the edge and 10px under the bar, no raw px", () => {
    const source = (name: string) => readFileSync(resolve(process.cwd(), "src/lib/components", `${name}.svelte`), "utf-8");
    const roots: Record<string, string> = { SourceTextPanel: "source-panel", ReferencePanel: "reference-panel",
      LanguageQaPanel: "language-qa", ParatextNotesPanel: "pt-notes", ReviewPanel: "panel" };
    for (const [name, root] of Object.entries(roots)) {
      const text = source(name);
      const rule = text.match(new RegExp(`\\.${root} \\{[^}]*\\}`))?.[0] ?? "";
      expect(rule, `${name} root`).toContain("font-size: var(--fs-xs)");
      expect(rule, `${name} root`).not.toContain("--surface-2");
      expect(text, `${name} raw px`).not.toMatch(/font-size:\s*\d/);
    }
    // The three panels with one scroll box pad it 10px 12px.
    expect(source("ParatextNotesPanel")).toMatch(/\.pt-scroll \{[^}]*padding: 10px 12px/);
    expect(source("LanguageQaPanel")).toMatch(/\.panel-body \{[^}]*padding: 10px 12px/);
    expect(source("ReviewPanel")).toMatch(/\.tab-content \{[^}]*padding: 10px 12px/);
    // Review's tab bar is Language QA's: the body gutter, the same button padding, --fs-3xs.
    for (const [name, rule] of [["LanguageQaPanel", "panel-tabs"], ["ReviewPanel", "tabs"]]) {
      const text = source(name);
      expect(text, name).toMatch(new RegExp(`\\.${rule} \\{[^}]*padding: 0 12px`));
      expect(text, name).toMatch(new RegExp(`\\.${rule} \\{[^}]*font-size: var\\(--fs-3xs\\)`));
      expect(text, name).toMatch(new RegExp(`\\.${rule} button \\{[^}]*padding: 8px 6px 6px`));
    }
    // Compact editor/panel headers share 36px; slotted controls remain 24px.
    expect(source("PanelHeader")).toMatch(/\.panel-bar \{[^}]*min-height: 36px/);
    expect(source("PanelHeader")).toMatch(/\.panel-actions :global\(button:not\(\.info-btn\)\) \{[^}]*height: 24px/);
    // Review's four tabs never vanish: each label gives way with an ellipsis and keeps its name in its title.
    expect(source("ReviewPanel")).toMatch(/\.tab-label \{[^}]*text-overflow: ellipsis/);
    expect(source("ReviewPanel")).not.toMatch(/\.tabs \{[^}]*overflow-x: auto/);
    // The two verse lists: the list's 4px plus each row's 6px 8px is the same 10px / 12px.
    for (const name of ["SourceTextPanel", "ReferencePanel"]) {
      expect(source(name), name).toMatch(/\n\s*ol \{[^}]*padding: 4px;/);
      expect(source(name), name).toMatch(/li button \{[^}]*padding: 6px 8px/);
    }
  });
});

// 2026-11-14: no floating box. A saved one (an older save, a project's
// workspace) is cleared as it reaches the store, so the panel is a tab.
describe("a saved floating box", () => {
  it("is cleared, and the panel is an ordinary tab", () => {
    sidePanels.update((all) => ({ ...all, reference: { ...all.reference, open: true, float: { x: 20, y: 40, width: 440, height: 400 } } }));
    expect(get(sidePanels).reference.float).toBeNull();
    setSidePanel("reference", { float: { x: 1, y: 2, width: 300, height: 300 } });
    expect(get(sidePanels).reference.float).toBeNull();
    setSidePanel("reference", { open: false });
  });
});
