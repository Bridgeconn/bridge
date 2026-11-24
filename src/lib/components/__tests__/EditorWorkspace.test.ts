import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { fireEvent, render, screen } from "@testing-library/svelte";
import Fixture from "./fixtures/EditorWorkspaceFixture.svelte";
import { editorTree } from "../../editorDocking";
import { tick } from "svelte";
import { groupOf, resetTabLayout, selectTab, splitTab, tabLayout } from "../../editorTabs";
import { versesOpen } from "../../editorPrefs";
import { resetPanelLayout, setSidePanel, sidePanels } from "../../editorPrefs";
const original = document.elementsFromPoint;
beforeEach(() => { editorTree.set(null); resetPanelLayout(); versesOpen.set(true); setSidePanel("review", { open: false }); setSidePanel("paratext", { open: true }); resetTabLayout(); selectTab("paratext"); });
afterEach(() => { document.elementsFromPoint = original; editorTree.set(null); resetPanelLayout(); vi.unstubAllGlobals(); });
// #519: the panel bar's tools menu, and its Dock entries, are gone; a tab is
// placed by dragging it or with the strip's Split right. What a split must
// still do is unchanged: a new group, its own strip, and the pane not remounted.
it("a tab split above the verses becomes a group over them, with its own strip, without remounting its filter", async () => {
  render(Fixture); const draft = screen.getByLabelText("QA filter"); await fireEvent.input(draft, { target: { value: "keep me" } });
  expect(Object.keys(get(tabLayout).groups)).toHaveLength(1);
  expect(screen.queryByRole("button", { name: /panel tools/ })).toBeNull();
  splitTab("paratext", groupOf(get(tabLayout), "editor")!, "top");
  await tick();
  const layout = get(tabLayout);
  expect(Object.keys(layout.groups)).toHaveLength(2);
  expect(layout.tree).toMatchObject({ axis: "vertical", first: groupOf(layout, "paratext"), second: groupOf(layout, "editor") });
  expect(screen.getByLabelText("QA filter")).toBe(draft);
  expect(draft).toHaveValue("keep me");
  // Each group has its own tab strip.
  expect(screen.getAllByRole("tablist")).toHaveLength(2);
  const splitter = screen.getByRole("slider", { name: "Resize panel heights" });
  await fireEvent.keyDown(splitter, { key: "ArrowDown" }); expect(splitter).toHaveAttribute("aria-valuenow", "52");
});
it("a tab dragged to the right edge of a group splits it there; dropped on another group's strip it joins that group", async () => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  render(Fixture);
  const frame = () => document.querySelector("[data-tab-group]") as HTMLElement;
  const rect = (el: Element, r: Partial<DOMRect>) => { (el as HTMLElement).getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...r }) as DOMRect; };
  rect(frame(), { left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600 });
  // Near the right edge of the body: a split, with a preview before release.
  await fireEvent.pointerDown(screen.getByRole("tab", { name: "Paratext" }), { button: 0, clientX: 100, clientY: 10 });
  await fireEvent.pointerMove(window, { clientX: 760, clientY: 300 });
  expect(document.querySelector(".drop-preview")).not.toBeNull();
  await fireEvent.pointerUp(window);
  let layout = get(tabLayout);
  expect(Object.keys(layout.groups)).toHaveLength(2);
  expect(layout.tree).toMatchObject({ axis: "horizontal", first: groupOf(layout, "editor"), second: groupOf(layout, "paratext") });
  expect(document.querySelector(".drop-preview")).toBeNull();
  // Dropped on the verses' strip: back into that group, and its own group goes.
  const target = document.querySelector(`[data-tab-group="${groupOf(layout, "editor")}"]`) as HTMLElement;
  rect(target, { left: 0, top: 0, width: 400, height: 600, right: 400, bottom: 600 });
  await fireEvent.pointerDown(screen.getByRole("tab", { name: "Paratext" }), { button: 0, clientX: 500, clientY: 10 });
  await fireEvent.pointerMove(window, { clientX: 300, clientY: 12 });
  await fireEvent.pointerUp(window);
  layout = get(tabLayout);
  expect(Object.keys(layout.groups)).toHaveLength(1);
  expect(layout.groups[groupOf(layout, "editor")!].tabs).toEqual(["editor", "paratext"]);
});
it("Escape cancels a drag without floating, closing or changing panel state", async () => {
  vi.stubGlobal("PointerEvent", MouseEvent); document.elementsFromPoint = () => [];
  render(Fixture); const before = structuredClone(get(sidePanels));
  // The bar has no drag handle (#519): the tab is what drags.
  expect(screen.queryByRole("button", { name: "Move Language QA" })).toBeNull();
  await fireEvent.pointerDown(screen.getByRole("tab", { name: "Paratext" }), { button: 0, clientX: 40, clientY: 10 });
  await fireEvent.pointerMove(window, { clientX: 300, clientY: 200 });
  await fireEvent.keyDown(window, { key: "Escape" }); await fireEvent.pointerUp(window);
  expect(get(sidePanels)).toEqual(before); expect(get(editorTree)).toBeNull();
});
it("a side panel's tab released on the rail or a bar stays a tab; only outside the window does it leave", async () => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  render(Fixture); const before = structuredClone(get(sidePanels));
  // No group is under the pointer (jsdom gives every frame an empty box).
  await fireEvent.pointerDown(screen.getByRole("tab", { name: "Paratext" }), { button: 0, clientX: 100, clientY: 10 });
  await fireEvent.pointerMove(window, { clientX: 20, clientY: 300 });
  await fireEvent.pointerUp(window);
  expect(get(sidePanels)).toEqual(before);
  expect(get(sidePanels).paratext.float ?? null).toBeNull();
});
