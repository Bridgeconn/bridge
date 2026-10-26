import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import SidePanel from "../SidePanel.svelte";
import SideRail from "../SideRail.svelte";
import PanelHeader from "../PanelHeader.svelte";
import { PANEL_MIN, SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, setSidePanel, sidePanels } from "../../editorPrefs";
import { languageQaChannel } from "../../languageQaInline";

/** jsdom has no PointerEvent: a MouseEvent carries the pointer event's name and fields. */
async function pointer(target: HTMLElement, type: string, clientX = 0): Promise<void> {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, clientX }));
  await tick();
}

function reset(): void {
  for (const id of ["reference", "languageQa", "review"] as const) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial });
  }
}

describe("SIDE_PANEL_LIMITS (#379 item 6)", () => {
  it("gives every panel one minimum width except Language QA, which keeps 320", () => {
    for (const id of SIDE_PANEL_ORDER) {
      expect(SIDE_PANEL_LIMITS[id].min, id).toBe(id === "languageQa" ? 320 : PANEL_MIN);
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

  it("resizes from its left edge by keyboard and by drag, within limits, and remembers the width", async () => {
    setSidePanel("reference", { open: true });
    render(SidePanel, { props: { id: "reference", label: "Reference" } });
    const handle = screen.getByRole("separator", { name: /Resize the Reference panel/ });
    const width = () => (document.getElementById("side-panel-reference") as HTMLElement).style.width;
    expect(width()).toBe("300px");

    await fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(width()).toBe("316px");
    expect(JSON.parse(localStorage.getItem("bridge.editor.sidePanels.v1") ?? "{}").reference.width).toBe(316);
    await fireEvent.keyDown(handle, { key: "End" });
    expect(width()).toBe("640px");

    // A drag shows as it goes and is saved when it ends.
    await pointer(handle, "pointerdown", 500);
    await pointer(handle, "pointermove", 700);
    expect(width()).toBe("440px");
    expect(get(sidePanels).reference.width).toBe(640);
    await pointer(handle, "pointerup");
    expect(get(sidePanels).reference.width).toBe(440);

    await fireEvent.dblClick(handle);
    expect(width()).toBe("300px");
  });

  it("closes when its edge is dragged far to the right, and reopens at its last width", async () => {
    setSidePanel("reference", { open: true, width: 360 });
    render(SidePanel, { props: { id: "reference", label: "Reference" } });
    const handle = screen.getByRole("separator", { name: /Resize the Reference panel/ });
    // 360 wide; 80px to the right is 280, still above the minimum (260): stays open.
    await pointer(handle, "pointerdown", 500);
    await pointer(handle, "pointermove", 580);
    expect(screen.queryByText("Release to close")).toBeNull();
    // Past min - 60 (200): the hint shows, and release closes it.
    await pointer(handle, "pointermove", 800);
    expect(screen.getByText("Release to close")).toBeInTheDocument();
    await pointer(handle, "pointerup");
    expect(get(sidePanels).reference).toEqual({ open: false, width: 360 });
    expect(document.getElementById("side-panel-reference")).toBeNull();
  });

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

describe("SideRail", () => {
  beforeEach(reset);
  afterEach(() => {
    reset();
    languageQaChannel.set({ projectPath: "", status: null, error: "" });
  });

  it("toggles each panel's column and opens Settings", async () => {
    const onOpenSettings = vi.fn();
    render(SideRail, { props: { onOpenSettings } });
    const lqa = screen.getByRole("button", { name: /Language QA/ });
    expect(lqa.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(lqa);
    expect(get(sidePanels).languageQa.open).toBe(true);
    expect(lqa.getAttribute("aria-pressed")).toBe("true");
    await fireEvent.click(screen.getByRole("button", { name: /Review/ }));
    expect(get(sidePanels).review.open).toBe(false);
    await fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(onOpenSettings).toHaveBeenCalled();
  });

  // #379 item 6: the buttons run top to bottom as the columns run left to right.
  it("lists the panels in SIDE_PANEL_ORDER, Settings last", () => {
    render(SideRail);
    const names = screen.getAllByRole("button").map((button) => button.getAttribute("aria-controls"));
    expect(names).toEqual([...SIDE_PANEL_ORDER.map((id) => `side-panel-${id}`), null]);
  });

  it("badges Language QA with its total, or ! when the channel failed", async () => {
    languageQaChannel.set({ projectPath: "/p", error: "", status: { totalFindings: 18 } as never });
    render(SideRail);
    expect(screen.getByRole("button", { name: /Language QA/ }).textContent).toContain("18");
    languageQaChannel.set({ projectPath: "/p", error: "engine gone", status: null });
    await tick();
    expect(screen.getByRole("button", { name: /Language QA/ }).textContent).toContain("!");
  });
});

// #379 (Benz's item 7): one header bar with a line under it on every panel.
describe("PanelHeader (#379)", () => {
  beforeEach(reset);
  afterEach(reset);

  it("shows the title, carries the hint as its tooltip, and Close closes the column as the rail does", async () => {
    setSidePanel("reference", { open: true });
    render(PanelHeader, { props: { id: "reference", title: "Reference · OV", hint: "C:/bibles/ov", label: "the Reference panel" } });
    const title = screen.getByRole("heading", { level: 2, name: "Reference · OV" });
    expect(title.getAttribute("title")).toBe("C:/bibles/ov");
    expect(document.querySelector("[data-panel-bar='reference']")).not.toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Close the Reference panel" }));
    expect(get(sidePanels).reference.open).toBe(false);
  });

  it("names Close after the title when no label is given, and defers to onClose when one is given", async () => {
    const onClose = vi.fn();
    setSidePanel("languageQa", { open: true });
    render(PanelHeader, { props: { id: "languageQa", title: "Language QA", onClose } });
    await fireEvent.click(screen.getByRole("button", { name: "Close Language QA" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(get(sidePanels).languageQa.open).toBe(true);
  });

  it("is the first thing every one of the five panels draws, with the actions in its slot", () => {
    const source = (name: string) => readFileSync(resolve(process.cwd(), "src/lib/components", `${name}.svelte`), "utf-8");
    for (const [name, id] of [["SourceTextPanel", "source"], ["ReferencePanel", "reference"], ["LanguageQaPanel", "languageQa"],
      ["ParatextNotesPanel", "paratext"], ["ReviewPanel", "review"]] as const) {
      const text = source(name);
      expect(text, name).toMatch(new RegExp(`<PanelHeader id="${id}"`));
      // No panel keeps a header of its own beside the shared one.
      expect(text, name).not.toMatch(/class="(head|pt-head|head-row)"/);
    }
    // One bar: one padding, one title size, one background, one line under it.
    const bar = source("PanelHeader");
    expect(bar).toContain("padding: 8px 12px");
    expect(bar).toContain("border-bottom: 1px solid var(--border)");
    expect(bar).toContain("background: var(--surface-2)");
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
    // One bar height: 8 + 24 + 8 + the 1px line = 41px, every slotted control 24px like Close.
    expect(source("PanelHeader")).toMatch(/\.panel-bar \{[^}]*min-height: 41px/);
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
