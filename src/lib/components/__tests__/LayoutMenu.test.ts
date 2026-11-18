import { beforeEach, expect, it } from "vitest";
import { get } from "svelte/store";
import { fireEvent, render, screen } from "@testing-library/svelte";
import Fixture from "./fixtures/EditorWorkspaceFixture.svelte";
import LayoutMenu from "../EditorLayoutMenu.svelte";
import { leaves } from "../../alignmentLayout";
import { editorTree } from "../../editorDocking";
import { resetPanelLayout, setSidePanel, versesOpen } from "../../editorPrefs";
import {
  LAYOUT_PRESETS, applyLayoutPreset, closeGroup, closeTab, currentPreset, focusGroup, groupOf, reconcileTabs, resetTabLayout, showTab,
  tabLayout, withLayoutPreset, type TabLayout,
} from "../../editorTabs";

// 2026-11-16 (Joel): layout presets, after VS Code's "Editor Layout". The
// work area is split a named way in one click; the places with no panel are
// empty groups that fill from the left rail or a dragged tab.
const layout = () => get(tabLayout);
const order = (value: TabLayout = layout()) => (value.tree ? leaves(value.tree) : []);
const tabsInOrder = (value: TabLayout = layout()) => order(value).map((gid) => value.groups[gid].tabs);

beforeEach(() => {
  editorTree.set(null); resetPanelLayout(); versesOpen.set(true);
  for (const id of ["source", "reference", "paratext", "review"] as const) setSidePanel(id, { open: false });
  resetTabLayout();
});

it("splits one group into the preset's places: the open tabs stay, the rest are empty", () => {
  expect(tabsInOrder()).toEqual([["editor"]]);
  applyLayoutPreset("top1bottom2");
  expect(tabsInOrder()).toEqual([["editor"], [], []]);
  expect(layout().tree).toMatchObject({ axis: "vertical", second: { axis: "horizontal" } });
  expect(currentPreset(layout())).toBe("top1bottom2");
  expect(order().slice(1).every((gid) => layout().groups[gid].active === null)).toBe(true);
});

it("opens the next panels in the empty places, in reading order", () => {
  applyLayoutPreset("columns3");
  showTab("source");
  showTab("review");
  expect(tabsInOrder()).toEqual([["editor"], ["source"], ["review"]]);
  // No empty place left: a new panel joins the group in use, as before.
  showTab("reference");
  expect(tabsInOrder()).toEqual([["editor"], ["source"], ["review", "reference"]]);
});

it("a clicked empty place is the one the next panel opens in", () => {
  applyLayoutPreset("columns3");
  focusGroup(order()[2]);
  showTab("source");
  expect(tabsInOrder()).toEqual([["editor"], [], ["source"]]);
});

it("keeps every tab when there are more groups than places: the rest join the last place", () => {
  showTab("source"); showTab("review");
  applyLayoutPreset("columns3");
  showTab("reference");
  const before = layout();
  expect(Object.keys(before.groups)).toHaveLength(3);
  applyLayoutPreset("columns2");
  const all = tabsInOrder().flat().sort();
  expect(tabsInOrder()).toHaveLength(2);
  expect(all).toEqual(Object.values(before.groups).flatMap((group) => group.tabs).sort());
  applyLayoutPreset("single");
  expect(tabsInOrder()).toHaveLength(1);
  expect(tabsInOrder()[0].sort()).toEqual(all);
});

it("lays out an empty work area, then fills it from the rail", () => {
  closeTab("editor");
  expect(layout().tree).toBeNull();
  applyLayoutPreset("grid");
  expect(tabsInOrder()).toEqual([[], [], [], []]);
  showTab("editor");
  showTab("review");
  expect(tabsInOrder()).toEqual([["editor"], ["review"], [], []]);
});

it("removes an empty place, and never a group that holds a tab", () => {
  applyLayoutPreset("columns2");
  const [filled, empty] = order();
  closeGroup(filled);
  expect(Object.keys(layout().groups)).toHaveLength(2);
  closeGroup(empty);
  expect(tabsInOrder()).toEqual([["editor"]]);
  expect(layout().tree).toBe(filled);
});

it("Reset layout drops the empty places, and a group still goes when its last tab is closed", () => {
  applyLayoutPreset("columns2");
  showTab("source");
  closeTab("source");
  expect(tabsInOrder()).toEqual([["editor"]]);
  applyLayoutPreset("grid");
  resetTabLayout();
  expect(tabsInOrder()).toEqual([["editor"]]);
});

it("is a pure function of the layout, and leaves an unknown preset alone", () => {
  const start = layout();
  expect(withLayoutPreset(start, "nope")).toBe(start);
  const next = withLayoutPreset(start, "rows2");
  expect(start.tree).toBe(order(start)[0]);
  expect(reconcileTabs(next, ["editor"])).toBe(next);
  expect(groupOf(next, "editor")).toBe(order(next)[0]);
});

it("the Layout button opens the shapes, marks the current one and applies a click", async () => {
  render(LayoutMenu);
  const button = screen.getByRole("button", { name: "Layout" });
  expect(screen.queryByRole("menu", { name: "Layout" })).toBeNull();
  await fireEvent.click(button);
  const shapes = screen.getAllByRole("menuitemradio");
  expect(shapes).toHaveLength(LAYOUT_PRESETS.length);
  expect(screen.getByRole("menuitemradio", { name: "Single" })).toHaveAttribute("aria-checked", "true");
  // Each picture has one box per place.
  expect(screen.getByRole("menuitemradio", { name: "Grid: two by two" }).querySelectorAll("rect")).toHaveLength(4);
  await fireEvent.click(screen.getByRole("menuitemradio", { name: "Two columns" }));
  expect(screen.queryByRole("menu", { name: "Layout" })).toBeNull();
  expect(tabsInOrder()).toEqual([["editor"], []]);
  await fireEvent.click(button);
  await fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu", { name: "Layout" })).toBeNull();
});

it("draws an empty place with its own tab strip, and removes it from its close button", async () => {
  applyLayoutPreset("columns2");
  render(Fixture);
  expect(document.querySelectorAll("[data-tab-group]")).toHaveLength(2);
  // The picker is the top bar's, not each strip's.
  expect(screen.queryByRole("button", { name: "Layout" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Reset layout" })).toBeNull();
  const empty = document.querySelector("[data-empty-group]") as HTMLElement;
  expect(empty).toHaveTextContent("Click a panel on the left to open it here, or drag a tab in.");
  await fireEvent.click(empty);
  expect(layout().focused).toBe(empty.dataset.emptyGroup);
  await fireEvent.click(screen.getByRole("button", { name: "Remove this empty area" }));
  expect(document.querySelector("[data-empty-group]")).toBeNull();
  expect(tabsInOrder()).toEqual([["editor"]]);
});
