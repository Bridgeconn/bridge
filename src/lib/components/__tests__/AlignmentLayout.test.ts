// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/svelte";
import Fixture from "./fixtures/AlignmentLayoutFixture.svelte";
import { defaultLayout, dockPane, edgeScrollStep, gridAreasText, gridFor, validLayout } from "../../alignmentLayout";

const elementsFromPoint = document.elementsFromPoint;
afterEach(() => { document.elementsFromPoint = elementsFromPoint; vi.unstubAllGlobals(); localStorage.clear(); });

const stageOf = (container: HTMLElement) => container.querySelector<HTMLElement>(".alignment-layout")!;

describe("gridFor (#485): the docked tree as a grid whose rows fit their content", () => {
  it("stacks the word default: three rows, one column, no width divider", () => {
    const grid = gridFor(defaultLayout("word").tree);
    expect(grid.areas).toEqual([["read"], ["source"], ["target"]]);
    expect(grid.columns).toEqual([100]);
    expect(grid.dividers).toEqual([]);
  });

  it("the cross default: Read across the top, Source beside Target below, one divider on the second row", () => {
    const grid = gridFor(defaultLayout("cross").tree);
    expect(grid.areas).toEqual([["read", "read"], ["source", "target"]]);
    expect(grid.columns).toEqual([50, 50]);
    expect(grid.dividers).toHaveLength(1);
    expect(grid.dividers[0]).toMatchObject({ id: "source-target", column: 2, rowStart: 2, rowEnd: 3, ratio: .5 });
    expect(gridAreasText(grid.areas)).toBe('"read read" "source target"');
  });

  it("a leaf beside a stacked pair spans both rows; a nested width ratio multiplies", () => {
    const grid = gridFor(dockPane(defaultLayout("word").tree, "read", "source", "left"));
    // (read | source) / target: the pair shares the top row, Target spans both columns below.
    expect(grid.areas).toEqual([["read", "source"], ["target", "target"]]);
    expect(grid.dividers[0]).toMatchObject({ column: 2, rowStart: 1, rowEnd: 2 });
    const three = gridFor(dockPane(dockPane(defaultLayout("word").tree, "read", "source", "left"), "target", "source", "right"));
    expect(three.areas).toEqual([["read", "source", "target"]]);
    expect(three.columns.reduce((s, w) => s + w, 0)).toBeCloseTo(100);
    expect(three.dividers.map((d) => d.column)).toEqual([2, 3]);
  });

  it("a layout saved by the current build, vertical ratios included, still validates and lays out", () => {
    const saved = JSON.parse(JSON.stringify(defaultLayout("word")));
    saved.tree.ratio = .3; saved.tree.second.ratio = .7;
    expect(validLayout(saved)).toBe(true);
    expect(gridFor(saved.tree).areas).toEqual([["read"], ["source"], ["target"]]);
    expect(validLayout({ ...saved, floating: ["read"], positions: { read: { x: 10, y: 10, width: 300, height: 200 } } })).toBe(true);
  });
});

describe("edgeScrollStep (#485)", () => {
  it("is zero away from the edges, grows towards them, and never fires in a box too short for two bands", () => {
    expect(edgeScrollStep(300, 0, 600)).toBe(0);
    expect(edgeScrollStep(20, 0, 600)).toBe(-6);
    expect(edgeScrollStep(0, 0, 600)).toBe(-12);
    expect(edgeScrollStep(580, 0, 600)).toBe(6);
    expect(edgeScrollStep(600, 0, 600)).toBe(12);
    expect(edgeScrollStep(5, 0, 70)).toBe(0);
  });
});

describe("AlignmentWorkspace (#485)", () => {
  it("arranges panes side by side or stacked, persists and resets without discarding content", async () => {
    const first = render(Fixture);
    const stage = stageOf(first.container);
    expect(stage.dataset.gridAreas).toBe('"read" "source" "target"');
    const source = screen.getByRole("region", { name: "Source area" });
    expect(source.style.gridArea).toBe("source");
    const draft = screen.getByLabelText("Reading draft");
    await fireEvent.input(draft, { target: { value: "keep this reading draft" } });
    await fireEvent.click(within(source).getByRole("button", { name: "Source area tools" }));
    await fireEvent.click(await screen.findByRole("menuitem", { name: "Dock left of" }));
    await fireEvent.click(await screen.findByRole("menuitem", { name: "Target" }));
    expect(stage.dataset.gridAreas).toBe('"read read" "source target"');
    expect(stage.dataset.gridColumns).toBe("50fr 50fr");
    expect((draft as HTMLInputElement).value).toBe("keep this reading draft");
    const saved = JSON.parse(localStorage.getItem("bridge.alignment.docking.v3.local.default.word")!);
    expect(saved.tree.second.axis).toBe("horizontal");
    first.unmount();
    const second = render(Fixture);
    expect(stageOf(second.container).dataset.gridAreas).toBe('"read read" "source target"');
    await fireEvent.input(screen.getByLabelText("Reading draft"), { target: { value: "still here" } });
    await fireEvent.click(screen.getByRole("button", { name: "Alignment layout tools" }));
    await fireEvent.click(await screen.findByRole("menuitem", { name: "Reset layout" }));
    expect(stageOf(second.container).dataset.gridAreas).toBe('"read" "source" "target"');
    expect((screen.getByLabelText("Reading draft") as HTMLInputElement).value).toBe("still here");
  });

  it("has no fixed height and no scroll container of its own; a docked pane's content does not scroll", () => {
    const workspace = readFileSync(resolve(process.cwd(), "src/lib/components/AlignmentWorkspace.svelte"), "utf-8");
    const stage = workspace.match(/\.alignment-layout \{([^}]*)\}/)?.[1] ?? "";
    expect(stage).toMatch(/display: grid/);
    expect(stage).not.toMatch(/height:/);
    expect(stage).not.toMatch(/overflow(-y)?:\s*(auto|scroll|hidden)/);
    const pane = readFileSync(resolve(process.cwd(), "src/lib/components/AlignmentPane.svelte"), "utf-8");
    expect(pane.match(/\n\s*\.content \{([^}]*)\}/)?.[1] ?? "").not.toMatch(/overflow/);
    expect(pane).toMatch(/\.floating \.content \{[^}]*overflow: auto/);
  });

  it("docks a dragged handle at the target edge and adjusts the width divider with the keyboard; no height divider exists", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const { container } = render(Fixture);
    const source = screen.getByRole("region", { name: "Source area" }), target = screen.getByRole("region", { name: "Target area" });
    const stage = stageOf(container);
    expect(screen.queryByRole("slider")).toBeNull();
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500 } as DOMRect);
    source.getBoundingClientRect = () => ({ left: 0, top: 110, width: 1000, height: 250 } as DOMRect);
    target.getBoundingClientRect = () => ({ left: 0, top: 360, width: 1000, height: 140 } as DOMRect);
    document.elementsFromPoint = vi.fn(() => [target, stage]);
    await fireEvent.pointerDown(screen.getByRole("button", { name: "Move Source" }), { button: 0, clientX: 20, clientY: 125 });
    await fireEvent.pointerMove(window, { clientX: 5, clientY: 420 });
    expect(screen.getByText("Source to the left of Target")).toBeInTheDocument();
    await fireEvent.pointerUp(window);
    expect(stage.dataset.gridAreas).toBe('"read read" "source target"');
    const divider = screen.getByRole("slider", { name: "Resize area widths" });
    expect(screen.queryByRole("slider", { name: "Resize area heights" })).toBeNull();
    await fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(stage.dataset.gridColumns).toBe("55fr 45fr");
    await fireEvent.keyDown(divider, { key: "ArrowDown" });
    expect(stage.dataset.gridColumns).toBe("55fr 45fr");
  });

  it("floats freely over the center of another area; the stage grows to the floating box and the rest re-flows", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const { container } = render(Fixture);
    const source = screen.getByRole("region", { name: "Source area" }), target = screen.getByRole("region", { name: "Target area" });
    const stage = stageOf(container);
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500 } as DOMRect);
    source.getBoundingClientRect = () => ({ left: 0, top: 110, width: 1000, height: 250 } as DOMRect);
    target.getBoundingClientRect = () => ({ left: 0, top: 360, width: 1000, height: 140 } as DOMRect);
    document.elementsFromPoint = vi.fn(() => [target, stage]);
    await fireEvent.pointerDown(screen.getByRole("button", { name: "Move Source" }), { button: 0, clientX: 20, clientY: 125 });
    await fireEvent.pointerMove(window, { clientX: 500, clientY: 430 });
    expect(screen.queryByText(/Source to the/)).not.toBeInTheDocument();
    await fireEvent.pointerUp(window);
    expect(source).toHaveClass("floating");
    expect(source.style.left).toBe("400px");
    expect(source.style.top).toBe("415px");
    expect(source.style.gridArea).toBe("");
    expect(stage.dataset.gridAreas).toBe('"read" "target"');
    expect(parseFloat(stage.style.minHeight)).toBe(415 + 250);
    // Its size boxes show; Dock in the tools menu puts it back.
    await fireEvent.change(within(source).getByLabelText("Source height"), { target: { value: "300" } });
    expect(parseFloat(stage.style.minHeight)).toBe(415 + 300);
    await fireEvent.click(within(source).getByRole("button", { name: "Source area tools" }));
    await fireEvent.click(await screen.findByRole("menuitem", { name: "Dock in the workspace" }));
    expect(source).not.toHaveClass("floating");
    expect(stage.dataset.gridAreas).toBe('"read source" "target target"');
  });
});
