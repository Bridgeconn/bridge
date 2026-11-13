import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

import ActivityBar from "../ActivityBar.svelte";
import EditorTabs from "../EditorTabs.svelte";
import { leaves } from "../../alignmentLayout";
import { SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, setSidePanel, sidePanelRecency, sidePanels, versesOpen } from "../../editorPrefs";
import {
  defaultTabLayout, groupOf, moveTab, openTabs, reconcileTabs, resetTabLayout, resizeSplit, selectTab, splitTab, tabLayout, visibleTabs,
} from "../../editorTabs";
import { versesShown, workAreaEmpty } from "../../panelFit";

// Verses and Review open: the editor's default, verses left, Review right.
function reset(): void {
  for (const id of SIDE_PANEL_ORDER) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial, float: null, detached: false });
  }
  sidePanelRecency.set([]);
  versesOpen.set(true);
  resetTabLayout();
}

const button = (name: string) => screen.getByRole("button", { name });
const tab = (name: string) => screen.getByRole("tab", { name });
const layout = () => get(tabLayout);
const groupTabs = (id: Parameters<typeof groupOf>[1]) => layout().groups[groupOf(layout(), id)!].tabs;

// 2026-11-13: the editor's left rail, in place of the View menu (#488).
// 2026-11-14: its panes are tabs of the work area's groups.
describe("ActivityBar", () => {
  beforeEach(reset);

  // #487: Language QA is a tab of the Review panel, with no button of its own.
  it("has one button per pane, marked where it is open and where it is showing, and none for Language QA", async () => {
    render(ActivityBar);
    const names = Array.from(screen.getByRole("group", { name: "Panels" }).querySelectorAll("button"))
      .map((item) => item.getAttribute("aria-label"));
    expect(names).toEqual(["Verses", "Source", "Reference", "Paratext", "Review"]);
    // Verses and Review each show in their group; Source is closed.
    expect(button("Verses")).toHaveClass("active");
    expect(button("Review")).toHaveClass("active");
    expect(button("Source")).toHaveAttribute("aria-pressed", "false");
    expect(button("Source")).not.toHaveClass("open");
    // Opened, Source joins the group in use (the verses') and shows there:
    // Verses is then open, behind it.
    await fireEvent.click(button("Source"));
    expect(button("Source")).toHaveClass("active");
    expect(button("Verses")).toHaveClass("open");
    expect(button("Verses")).not.toHaveClass("active");
    expect(button("Verses")).toHaveAttribute("aria-pressed", "true");
  });

  it("a click opens a pane and shows it, shows one that is behind another, and closes one that is showing", async () => {
    render(ActivityBar);
    await fireEvent.click(button("Reference"));
    expect(get(sidePanels).reference.open).toBe(true);
    expect(get(visibleTabs).has("reference")).toBe(true);
    expect(groupTabs("reference")).toEqual(["editor", "reference"]);
    expect(get(versesShown)).toBe(false);
    // Verses is open behind Reference: a click shows it, and does not close it.
    await fireEvent.click(button("Verses"));
    expect(get(versesOpen)).toBe(true);
    expect(get(versesShown)).toBe(true);
    // Showing: a click closes it, and the group's other tab shows.
    await fireEvent.click(button("Verses"));
    expect(get(versesOpen)).toBe(false);
    expect(get(visibleTabs).has("reference")).toBe(true);
  });

  it("with every pane closed the work area is empty, and Verses brings it back", async () => {
    render(ActivityBar);
    await fireEvent.click(button("Verses"));
    expect(get(workAreaEmpty)).toBe(false);
    await fireEvent.click(button("Review"));
    expect(get(openTabs)).toEqual([]);
    expect(get(workAreaEmpty)).toBe(true);
    await fireEvent.click(button("Verses"));
    expect(get(versesShown)).toBe(true);
    expect(get(workAreaEmpty)).toBe(false);
  });

  it("names each button in an instant hint, not a native title", async () => {
    render(ActivityBar);
    expect(button("Source")).not.toHaveAttribute("title");
    await fireEvent.mouseEnter(button("Source"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Source: the Hebrew, Aramaic or Greek");
    await fireEvent.mouseLeave(button("Source"));
    await fireEvent.mouseEnter(button("Verses"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Click to close it");
    await fireEvent.mouseLeave(button("Verses"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

describe("tab groups (editorTabs)", () => {
  beforeEach(reset);

  it("starts with the verses on the left and Review on the right, as two groups", () => {
    const start = layout();
    expect(Object.keys(start.groups)).toHaveLength(2);
    expect(groupTabs("editor")).toEqual(["editor"]);
    expect(groupTabs("review")).toEqual(["review"]);
    expect(typeof start.tree).toBe("object");
    expect([...get(visibleTabs)].sort()).toEqual(["editor", "review"]);
    // One group when Review is closed.
    expect(Object.keys(defaultTabLayout(["editor", "source"]).groups)).toHaveLength(1);
    expect(defaultTabLayout([]).tree).toBeNull();
  });

  it("a panel opened by any route joins the group in use and shows; closing it shows its neighbour", () => {
    selectTab("review");
    setSidePanel("paratext", { open: true });
    expect(groupTabs("paratext")).toEqual(["review", "paratext"]);
    expect(get(visibleTabs).has("paratext")).toBe(true);
    setSidePanel("paratext", { open: false });
    expect(groupTabs("review")).toEqual(["review"]);
    expect(get(visibleTabs).has("review")).toBe(true);
    // A panel in its own window is not a tab; a group's last tab gone removes the group.
    setSidePanel("review", { detached: true });
    expect(get(openTabs)).toEqual(["editor"]);
    expect(Object.keys(layout().groups)).toHaveLength(1);
    expect(layout().tree).toBe(groupOf(layout(), "editor"));
  });

  it("splits a tab off to an edge, moves a tab between groups, and resizes a split", () => {
    setSidePanel("source", { open: true });
    selectTab("editor");
    setSidePanel("reference", { open: true });
    const main = groupOf(layout(), "editor")!;
    expect(layout().groups[main].tabs).toEqual(["editor", "source", "reference"]);
    // Source below the verses: a third group.
    splitTab("source", main, "bottom");
    expect(Object.keys(layout().groups)).toHaveLength(3);
    expect(groupTabs("source")).toEqual(["source"]);
    expect(leaves(layout().tree!).sort()).toEqual(Object.keys(layout().groups).sort());
    expect(layout().focused).toBe(groupOf(layout(), "source"));
    // Reference into Review's group, first in its strip.
    moveTab("reference", groupOf(layout(), "review")!, 0);
    expect(groupTabs("review")).toEqual(["reference", "review"]);
    expect(get(visibleTabs).has("reference")).toBe(true);
    // The only tab of a group cannot be split from itself.
    const before = layout();
    splitTab("source", groupOf(before, "source")!, "right");
    expect(layout()).toBe(before);
    // Source back into the verses' group: its own group goes.
    moveTab("source", main);
    expect(Object.keys(layout().groups)).toHaveLength(2);
    expect(leaves(layout().tree!).sort()).toEqual(Object.keys(layout().groups).sort());
    // The split's share is kept between 15% and 85%.
    const split = layout().tree as { id: string; ratio: number };
    resizeSplit(split.id, 0.99);
    expect((layout().tree as { ratio: number }).ratio).toBe(0.85);
  });

  it("reconcile leaves a layout that already matches untouched", () => {
    const start = layout();
    expect(reconcileTabs(start, get(openTabs))).toBe(start);
  });
});

describe("EditorTabs", () => {
  beforeEach(reset);
  const mainGroup = () => groupOf(layout(), "editor")!;

  it("shows one tab per pane of its group, each an icon and a name, with the one showing selected", async () => {
    setSidePanel("source", { open: true });
    selectTab("editor");
    render(EditorTabs, { props: { group: mainGroup() } });
    expect(screen.getAllByRole("tab").map((item) => item.textContent?.trim())).toEqual(["Verses", "Source"]);
    expect(tab("Verses")).toHaveAttribute("aria-selected", "true");
    expect(tab("Source")).toHaveAttribute("aria-selected", "false");
    expect(tab("Verses").querySelector("svg")).not.toBeNull();
    // Review is in the other group, so not in this strip.
    expect(screen.queryByRole("tab", { name: "Review" })).toBeNull();
  });

  it("a click shows a tab; its close button closes it; arrows move between the group's tabs", async () => {
    setSidePanel("source", { open: true });
    selectTab("editor");
    render(EditorTabs, { props: { group: mainGroup() } });
    await fireEvent.click(tab("Source"));
    expect(get(visibleTabs).has("source")).toBe(true);
    await fireEvent.keyDown(tab("Source"), { key: "ArrowLeft" });
    expect(get(versesShown)).toBe(true);
    await fireEvent.click(button("Close Source"));
    expect(get(sidePanels).source.open).toBe(false);
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    // The group's last tab closed: the strip goes with the group.
    await fireEvent.click(button("Close Verses"));
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(get(versesOpen)).toBe(false);
  });

  it("Split right moves the tab showing into a new group beside its own", async () => {
    setSidePanel("source", { open: true });
    render(EditorTabs, { props: { group: mainGroup() } });
    await fireEvent.click(button("Split Source to the right"));
    await tick();
    expect(groupTabs("source")).toEqual(["source"]);
    expect(groupTabs("editor")).toEqual(["editor"]);
    expect(Object.keys(layout().groups)).toHaveLength(3);
    // One tab left: nothing to split, so no button.
    expect(screen.queryByRole("button", { name: /^Split/ })).toBeNull();
  });
});
