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
import {
  PANEL_MIN, SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, clampPanelFloat, movePanel, setSidePanel, sidePanelOrder, sidePanels,
  undockSidePanel,
} from "../../editorPrefs";
import { languageQaChannel } from "../../languageQaInline";

/** jsdom has no PointerEvent: a MouseEvent carries the pointer event's name and fields. */
async function pointer(target: HTMLElement, type: string, clientX = 0): Promise<void> {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, clientX }));
  await tick();
}

function reset(): void {
  for (const id of ["reference", "languageQa", "review"] as const) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial, float: null });
  }
  sidePanelOrder.set([...SIDE_PANEL_ORDER]);
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
    expect(get(sidePanels).reference).toEqual({ open: false, width: 360, float: null });
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
  it("lists the panels in SIDE_PANEL_ORDER by default, Settings last", () => {
    render(SideRail);
    const names = screen.getAllByRole("button").map((button) => button.getAttribute("aria-controls"));
    expect(names).toEqual([...SIDE_PANEL_ORDER.map((id) => `side-panel-${id}`), null]);
  });

  // #389 step 2: the reviewer's order, and the rail follows it.
  it("follows the reviewer's order as it changes", async () => {
    render(SideRail);
    movePanel("reference", -1);
    await tick();
    const names = screen.getAllByRole("button").map((button) => button.getAttribute("aria-controls"));
    expect(names.slice(0, 2)).toEqual(["side-panel-reference", "side-panel-source"]);
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

  // #389 step 2: ◂ ▸ in the bar reorder the columns, the order is remembered,
  // and a saved order that lost a panel gets it back in its default place.
  it("moves its column with ◂ ▸, which the saved order and the rail follow", async () => {
    setSidePanel("reference", { open: true });
    render(PanelHeader, { props: { id: "reference", title: "Reference", label: "the Reference panel" } });
    render(SideRail);
    const left = screen.getByRole("button", { name: "Move the Reference panel left" });
    const right = screen.getByRole("button", { name: "Move the Reference panel right" });
    expect(left).toBeEnabled();
    await fireEvent.click(left);
    expect(get(sidePanelOrder)).toEqual(["reference", "source", "languageQa", "paratext", "review"]);
    expect(JSON.parse(localStorage.getItem("bridge.editor.sidePanelOrder.v1") ?? "[]")[0]).toBe("reference");
    expect(left).toBeDisabled();
    const rail = screen.getAllByRole("button").filter((b) => b.getAttribute("aria-controls")).map((b) => b.getAttribute("aria-controls"));
    expect(rail[0]).toBe("side-panel-reference");
    await fireEvent.click(right);
    await fireEvent.click(right);
    expect(get(sidePanelOrder)).toEqual(["source", "languageQa", "reference", "paratext", "review"]);
    // The last column's ▸ is disabled; a Review bar at the end cannot move right.
    render(PanelHeader, { props: { id: "review", title: "Review", label: "the Review panel" } });
    expect(screen.getByRole("button", { name: "Move the Review panel right" })).toBeDisabled();
    // A saved order missing a panel (added after the save) is completed.
    sidePanelOrder.set(["review", "source"] as never);
    sidePanelOrder.update((order) => order);
    expect(get(sidePanelOrder)).toEqual(["review", "source"]);
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

// #389 step 3: undock into a box inside the window, dock back, remembered.
describe("undocked panels (#389)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 1366 });
    Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: 768 });
    reset();
  });
  afterEach(reset);

  it("Undock in the bar turns the column into a box at its place; Dock puts it back; both are remembered", async () => {
    setSidePanel("reference", { open: true, width: 300 });
    render(SidePanel, { props: { id: "reference", label: "Reference" } });
    render(PanelHeader, { props: { id: "reference", title: "Reference", label: "the Reference panel" } });
    await fireEvent.click(screen.getByRole("button", { name: "Undock the Reference panel" }));
    const saved = get(sidePanels).reference;
    expect(saved.open).toBe(true);
    expect(saved.width).toBe(300);
    // jsdom lays nothing out, so the column's rect is empty and the default place is used.
    expect(saved.float).toEqual({ x: 1366 - 60 - 360, y: 80, width: 360, height: 480 });
    await tick();
    const box = document.getElementById("side-panel-reference") as HTMLElement;
    expect(box.classList.contains("floating")).toBe(true);
    expect(box.style.left).toBe("946px");
    expect(box.style.width).toBe("360px");
    expect(box.style.height).toBe("480px");
    expect(JSON.parse(localStorage.getItem("bridge.editor.sidePanels.v1") ?? "{}").reference.float.width).toBe(360);
    // The bar now offers Dock instead of ◂ ▸ / Undock.
    expect(screen.queryByRole("button", { name: "Undock the Reference panel" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Dock the Reference panel" }));
    expect(get(sidePanels).reference.float).toBeNull();
    await tick();
    const column = document.getElementById("side-panel-reference") as HTMLElement;
    expect(column.classList.contains("floating")).toBe(false);
    expect(column.style.width).toBe("300px");
  });

  it("moves by its grip (pointer and keys), resizes from its corner, stays inside the window, and Escape closes it", async () => {
    undockSidePanel("reference", { x: 100, y: 100, width: 400, height: 300 });
    render(SidePanel, { props: { id: "reference", label: "Reference" } });
    const grip = screen.getByRole("button", { name: "Move the Reference panel" });
    await pointer(grip, "pointerdown", 150);
    grip.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, clientX: 250, clientY: 40 }));
    await tick();
    const box = () => document.getElementById("side-panel-reference") as HTMLElement;
    expect(box().style.left).toBe("200px");
    expect(box().style.top).toBe("140px");
    await pointer(grip, "pointerup");
    expect(get(sidePanels).reference.float).toEqual({ x: 200, y: 140, width: 400, height: 300 });

    await fireEvent.keyDown(grip, { key: "ArrowLeft", shiftKey: true });
    expect(get(sidePanels).reference.float?.x).toBe(152);
    // Dragged past the right edge: the box stops at the window's edge.
    await fireEvent.keyDown(grip, { key: "ArrowRight", shiftKey: true });
    for (let i = 0; i < 40; i += 1) await fireEvent.keyDown(grip, { key: "ArrowRight", shiftKey: true });
    expect(get(sidePanels).reference.float?.x).toBe(1366 - 400);

    const corner = screen.getByRole("separator", { name: /Resize the Reference panel; drag the corner/ });
    await fireEvent.keyDown(corner, { key: "ArrowDown", shiftKey: true });
    expect(get(sidePanels).reference.float?.height).toBe(348);
    // Never below the minimum size.
    for (let i = 0; i < 20; i += 1) await fireEvent.keyDown(corner, { key: "ArrowLeft", shiftKey: true });
    expect(get(sidePanels).reference.float?.width).toBe(260);

    await fireEvent.keyDown(box(), { key: "Escape" });
    expect(get(sidePanels).reference.open).toBe(false);
    // Closed, not docked: it reopens as a box where it was.
    expect(get(sidePanels).reference.float?.width).toBe(260);
  });

  it("keeps a saved box inside a window that shrank, and the saved shape stays valid without it", () => {
    expect(clampPanelFloat({ x: 1200, y: 700, width: 600, height: 900 }, 1000, 600)).toEqual({ x: 400, y: 16, width: 600, height: 584 });
    expect(clampPanelFloat({ x: 0, y: 0, width: 1200, height: 300 }, 1000, 600)).toEqual({ x: 0, y: 0, width: 984, height: 300 });
    expect(clampPanelFloat({ x: -20, y: -5, width: 100, height: 50 }, 1366, 768)).toEqual({ x: 0, y: 0, width: 260, height: 200 });
    expect(clampPanelFloat({ x: 10, y: 20, width: 300, height: 250 }, 1366, 768)).toEqual({ x: 10, y: 20, width: 300, height: 250 });
  });
});
