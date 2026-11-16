import { beforeEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";

import {
  alignmentBusyElsewhere, alignmentOpen, closeAlignment, crossVerseOpen, detachAlignment, holdAlignmentBusy, openAlignment, openCrossVerse,
  watchAlignmentChanges,
} from "../alignmentUi";
import { alignmentRevisionByVerse, noteAlignmentChanged } from "../stores";
import { alignmentBusy, alignmentDetached } from "../alignmentWindow";
import { resetPanelLayout, setSidePanel, sidePanels, versesOpen } from "../editorPrefs";
import { closeTab, groupOf, openTabs, resetTabLayout, splitTab, tabLayout, visibleTabs } from "../editorTabs";

// 2026-11-15 (Joel): the alignment editors are tabs of the editor's work area,
// like the panels, not a dialog over the window.
describe("the alignment tabs", () => {
  beforeEach(() => {
    closeAlignment();
    alignmentDetached.set(false);
    resetPanelLayout();
    versesOpen.set(true);
    setSidePanel("review", { open: true });
    resetTabLayout();
  });

  it("opens as a tab of the group in use and shows; the Review panel is left as it was", () => {
    setSidePanel("review", { open: false });
    resetTabLayout();
    expect(get(openTabs)).not.toContain("alignment");
    expect(openAlignment("1", "6")).toBe(true);
    expect(get(openTabs)).toContain("alignment");
    const layout = get(tabLayout);
    expect(groupOf(layout, "alignment")).toBe(groupOf(layout, "editor"));
    expect(get(visibleTabs).has("alignment")).toBe(true);
    // #306 opened Review with the dialog; a tab needs no host panel.
    expect(get(sidePanels).review.open).toBe(false);
  });

  it("closing the tab closes the editor, and not while it is saving", () => {
    openAlignment("1", "6");
    alignmentBusy.set(true);
    closeTab("alignment");
    expect(get(alignmentOpen)).toBe(true);
    alignmentBusy.set(false);
    closeTab("alignment");
    expect(get(alignmentOpen)).toBe(false);
    expect(get(openTabs)).not.toContain("alignment");
    expect(groupOf(get(tabLayout), "alignment")).toBeNull();
  });

  // 2026-11-15 (Joel): two tabs, not one that holds either editor.
  it("opens the cross-verse page as its own tab and leaves Word alignment open", () => {
    openAlignment("1", "6");
    expect(openCrossVerse("6")).toBe(true);
    expect(get(alignmentOpen)).toBe(true);
    expect(get(crossVerseOpen)).toBe(true);
    expect(get(openTabs)).toEqual(expect.arrayContaining(["alignment", "crossVerse"]));
    expect(get(visibleTabs).has("crossVerse")).toBe(true);

    // Side by side: each tab is placed on its own.
    splitTab("crossVerse", groupOf(get(tabLayout), "crossVerse")!, "right");
    expect(groupOf(get(tabLayout), "crossVerse")).not.toBe(groupOf(get(tabLayout), "alignment"));
    expect(get(visibleTabs).has("alignment")).toBe(true);
    expect(get(visibleTabs).has("crossVerse")).toBe(true);

    // Opening another verse's alignment leaves the cross-verse tab alone.
    expect(openAlignment("1", "7")).toBe(true);
    expect(get(crossVerseOpen)).toBe(true);
  });

  it("closes each tab on its own", () => {
    openAlignment("1", "6");
    openCrossVerse("6");
    closeTab("crossVerse");
    expect(get(crossVerseOpen)).toBe(false);
    expect(get(alignmentOpen)).toBe(true);
    openCrossVerse("6");
    closeTab("alignment");
    expect(get(alignmentOpen)).toBe(false);
    expect(get(crossVerseOpen)).toBe(true);
    expect(get(openTabs)).toContain("crossVerse");
    expect(get(openTabs)).not.toContain("alignment");
  });

  it("the separate window takes one editor; the other stays a tab", () => {
    openAlignment("1", "6");
    openCrossVerse("6");
    detachAlignment("cross");
    expect(get(openTabs)).toContain("alignment");
    expect(get(openTabs)).not.toContain("crossVerse");
    detachAlignment("word");
    expect(get(openTabs)).not.toContain("alignment");
    expect(get(openTabs)).toContain("crossVerse");
    alignmentDetached.set(false);
    expect(get(openTabs)).toEqual(expect.arrayContaining(["alignment", "crossVerse"]));
  });

  it("holds busy per editor, so one finishing does not clear the other's save", () => {
    const word = {}, cross = {};
    holdAlignmentBusy(word, true);
    holdAlignmentBusy(cross, true);
    expect(alignmentBusyElsewhere(word)).toBe(true);
    holdAlignmentBusy(cross, false);
    expect(get(alignmentBusy)).toBe(true);
    expect(alignmentBusyElsewhere(word)).toBe(false);
    holdAlignmentBusy(word, false);
    expect(get(alignmentBusy)).toBe(false);
  });

  it("tells an editor when a verse it shows was saved somewhere else, not its own saves", () => {
    alignmentRevisionByVerse.set({});
    let own = false, told = 0;
    const stop = watchAlignmentChanges(() => ["1:6"], () => own, () => { told += 1; });
    noteAlignmentChanged("1:7");
    expect(told).toBe(0);
    own = true;
    noteAlignmentChanged("1:6");
    expect(told).toBe(0);
    own = false;
    noteAlignmentChanged("1:6");
    expect(told).toBe(1);
    stop();
    noteAlignmentChanged("1:6");
    expect(told).toBe(1);
  });

  it("is not a tab while the editor is in its own window, and is again when docked", () => {
    openAlignment("1", "6");
    alignmentDetached.set(true);
    expect(get(openTabs)).not.toContain("alignment");
    alignmentDetached.set(false);
    expect(get(openTabs)).toContain("alignment");
  });

  it("a click on another verse while it is behind a tab brings it forward", () => {
    openAlignment("1", "6");
    const gid = groupOf(get(tabLayout), "alignment")!;
    tabLayout.update((layout) => ({ ...layout, groups: { ...layout.groups, [gid]: { ...layout.groups[gid], active: "editor" } } }));
    expect(get(visibleTabs).has("alignment")).toBe(false);
    openAlignment("1", "7");
    expect(get(visibleTabs).has("alignment")).toBe(true);
  });
});
