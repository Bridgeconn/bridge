import { derived, get, writable, type Readable } from "svelte/store";

import { dockPane, leaves, resizeDivider, without, type DockEdge, type Frame, type LayoutNode } from "./alignmentLayout";
import { setSidePanel, sidePanelOrder, sidePanels, tabRequest, versesOpen } from "./editorPrefs";
import type { SidePanelId } from "./editorPrefs";
import { across, down, presetOf, shapePlaces, shapeTree, type LayoutPreset } from "./layoutShapes";
import { alignmentDetachedMode, alignmentOpen, closeCrossVerse, closeWordAlignment, crossVerseOpen } from "./alignmentUi";
import { alignmentBusy, alignmentDetached } from "./alignmentWindow";

/**
 * The editor's work area as tab groups (2026-11-14), after VS Code. The verse
 * list and every docked side panel that is open is one tab. Tabs sit in
 * groups; a group shows one of its tabs at a time, under its own tab strip.
 * The area starts as one or two groups and is split by dragging a tab to an
 * edge of a group (left, right, top, bottom); dragging it onto a group moves
 * it there; the line between two groups drags to resize them. A panel in its
 * own window is not a tab. The two alignment editors, one verse
 * (`alignment`) and the cross-verse page (`crossVerse`), are a tab each while
 * open (2026-11-15), so they can sit side by side.
 *
 * Whether a pane is open at all stays where it always was (`versesOpen`,
 * `sidePanels`): this module only places the open ones, and is reconciled
 * every time that set changes, so every existing route that opens or closes a
 * panel keeps working.
 */
export type EditorTabId = "editor" | SidePanelId | "alignment" | "crossVerse";

/** Name and icon (a UiIcon name) of each tab; the left rail uses the same. */
export const EDITOR_TABS: Readonly<Record<EditorTabId, { label: string; icon: string; title: string }>> = {
  editor: { label: "Verses", icon: "verses", title: "Verses: the text of this chapter" },
  source: { label: "Source", icon: "source", title: "Source: the Hebrew, Aramaic or Greek" },
  reference: { label: "Reference", icon: "open", title: "Reference: a reference Bible" },
  // #519: a reference a reviewer added. Its tab shows the reference's own
  // name (referenceTabs.ts `tabLabels`); this is the name before one is chosen.
  reference2: { label: "Reference", icon: "open", title: "Reference: a reference Bible added for reading" },
  reference3: { label: "Reference", icon: "open", title: "Reference: a reference Bible added for reading" },
  reference4: { label: "Reference", icon: "open", title: "Reference: a reference Bible added for reading" },
  paratext: { label: "Paratext", icon: "notes", title: "Paratext: Project Notes on the selected verse" },
  review: { label: "Review", icon: "review", title: "Review: Greek Room, Core check, Language QA and AI review" },
  alignment: { label: "Word alignment", icon: "align", title: "Word alignment: align the words of one verse to the source" },
  crossVerse: { label: "Cross-verse", icon: "link", title: "Cross-verse alignment: link words whose counterpart is in another verse" },
};
const TAB_IDS = Object.keys(EDITOR_TABS) as EditorTabId[];

/** The tab strip's height in px: a pane starts this far below its group's top. */
export const TAB_STRIP_HEIGHT = 36;

/** A group may be empty (`tabs: []`, `active: null`), but only when a layout
 * preset made it (2026-11-16): a place waiting for a panel. A group whose
 * last tab is closed or dragged away still goes, as before. */
export interface TabGroup { tabs: EditorTabId[]; active: EditorTabId | null }
/** `tree`'s leaves are the keys of `groups`; `focused` is the group last
 * used, where a newly opened tab goes. */
export interface TabLayout { tree: LayoutNode | null; groups: Record<string, TabGroup>; focused: string }

/** Every open tab: Verses first, then the panels in their saved order, then
 * each alignment editor that is open in this window. */
export const openTabs: Readable<EditorTabId[]> = derived(
  [versesOpen, sidePanels, sidePanelOrder, alignmentOpen, crossVerseOpen, alignmentDetached, alignmentDetachedMode],
  ([verses, panels, order, word, cross, detached, detachedMode]) => [
    ...(verses ? ["editor" as const] : []),
    ...order.filter((id) => panels[id].open && !panels[id].detached),
    ...(word && !(detached && detachedMode === "word") ? ["alignment" as const] : []),
    ...(cross && !(detached && detachedMode === "cross") ? ["crossVerse" as const] : []),
  ],
);

let groupSeq = 0;
const newGroupId = (): string => `g${Date.now().toString(36)}${(groupSeq += 1)}`;

/** The first layout: the verses on the left with every other tab behind
 * them, Review on the right, as the editor always opened. One group when
 * either is closed. */
export function defaultTabLayout(tabs: readonly EditorTabId[]): TabLayout {
  if (!tabs.length) return { tree: null, groups: {}, focused: "" };
  if (tabs.includes("editor") && tabs.includes("review")) {
    return {
      tree: { id: "split-default", axis: "horizontal", ratio: 0.5, first: "g-main", second: "g-side" },
      groups: { "g-main": { tabs: tabs.filter((id) => id !== "review"), active: "editor" }, "g-side": { tabs: ["review"], active: "review" } },
      focused: "g-main",
    };
  }
  return { tree: "g-main", groups: { "g-main": { tabs: [...tabs], active: tabs[0] } }, focused: "g-main" };
}

export function groupOf(layout: TabLayout, id: EditorTabId): string | null {
  return Object.keys(layout.groups).find((gid) => layout.groups[gid].tabs.includes(id)) ?? null;
}

/** `layout` without `id`. A group left empty goes, and its neighbour takes
 * its room; the tab on the closed one's left shows in its place. */
function removeTab(layout: TabLayout, id: EditorTabId): TabLayout {
  const gid = groupOf(layout, id);
  if (!gid) return layout;
  const group = layout.groups[gid];
  const at = group.tabs.indexOf(id);
  const tabs = group.tabs.filter((other) => other !== id);
  const groups = { ...layout.groups };
  if (!tabs.length) {
    delete groups[gid];
    const tree = layout.tree ? without(layout.tree, [gid]) : null;
    const focused = layout.focused === gid ? Object.keys(groups)[0] ?? "" : layout.focused;
    return { tree, groups, focused };
  }
  groups[gid] = { tabs, active: group.active === id ? tabs[Math.max(0, at - 1)] : group.active };
  return { ...layout, groups };
}

/** Make `layout` hold exactly `tabs`: closed ones leave, newly opened ones
 * join the focused group and show. Returns `layout` itself when nothing
 * changed. */
export function reconcileTabs(layout: TabLayout, tabs: readonly EditorTabId[]): TabLayout {
  if (!Object.keys(layout.groups).length) return tabs.length ? defaultTabLayout(tabs) : layout;
  let next = layout;
  for (const gid of Object.keys(layout.groups)) {
    for (const id of layout.groups[gid].tabs) if (!tabs.includes(id)) next = removeTab(next, id);
  }
  for (const id of tabs) {
    if (groupOf(next, id)) continue;
    const gids = Object.keys(next.groups);
    if (!gids.length) { next = defaultTabLayout([id]); continue; }
    // An empty group is a place waiting for a panel: the focused one when it
    // is empty, else the first empty one in reading order, else the focused.
    const empty = (next.tree ? leaves(next.tree) : gids).filter((g) => next.groups[g] && !next.groups[g].tabs.length);
    const focusedGroup = next.groups[next.focused];
    const gid = focusedGroup && (!focusedGroup.tabs.length || !empty.length) ? next.focused : empty[0] ?? gids[0];
    next = { ...next, focused: gid, groups: { ...next.groups, [gid]: { tabs: [...next.groups[gid].tabs, id], active: id } } };
  }
  return next;
}

export function validTabLayout(value: unknown): value is TabLayout {
  const v = value as TabLayout;
  if (!v || typeof v !== "object" || typeof v.focused !== "string" || !v.groups || typeof v.groups !== "object") return false;
  const gids = Object.keys(v.groups);
  const seen = new Set<string>();
  for (const gid of gids) {
    const group = v.groups[gid];
    if (!group || !Array.isArray(group.tabs)) return false;
    if (group.tabs.length ? !group.tabs.includes(group.active as EditorTabId) : group.active !== null) return false;
    for (const id of group.tabs) {
      if (!TAB_IDS.includes(id) || seen.has(id)) return false;
      seen.add(id);
    }
  }
  const node = (n: unknown, depth = 0): boolean => depth < 12 && (typeof n === "string" ? gids.includes(n)
    : Boolean(n) && typeof (n as { id: unknown }).id === "string" && ["horizontal", "vertical"].includes((n as { axis: string }).axis)
      && Number.isFinite((n as { ratio: number }).ratio) && (n as { ratio: number }).ratio >= 0.15 && (n as { ratio: number }).ratio <= 0.85
      && node((n as { first: unknown }).first, depth + 1) && node((n as { second: unknown }).second, depth + 1));
  if (v.tree === null) return gids.length === 0;
  return node(v.tree) && leaves(v.tree).sort().join() === [...gids].sort().join();
}

const STORAGE_KEY = "bridge.editor.tabLayout.v1";
function loadLayout(): TabLayout {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (validTabLayout(saved)) return saved;
  } catch { /* a fresh layout */ }
  return { tree: null, groups: {}, focused: "" };
}

export const tabLayout = writable<TabLayout>(loadLayout());
// A tab asked for before it was open (editorPrefs opens after it asks).
let wanted: EditorTabId | null = null;
openTabs.subscribe((tabs) => {
  tabLayout.update((layout) => reconcileTabs(layout, tabs));
  if (wanted && tabs.includes(wanted)) { const id = wanted; wanted = null; selectTab(id); }
});
tabLayout.subscribe((layout) => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(layout)); } catch { /* this session only */ }
});
tabRequest.subscribe((request) => {
  if (!TAB_IDS.includes(request.id as EditorTabId)) return;
  const id = request.id as EditorTabId;
  if (groupOf(get(tabLayout), id)) selectTab(id);
  else wanted = id;
});

/** The tabs on screen: each group's chosen one. */
export const visibleTabs: Readable<ReadonlySet<EditorTabId>> = derived(
  tabLayout, (layout) => new Set(Object.values(layout.groups).flatMap((group) => (group.active ? [group.active] : []))),
);

/** Back to the first layout for the tabs that are open (Reset layout, tests). */
export function resetTabLayout(): void {
  tabLayout.set(defaultTabLayout(get(openTabs)));
}

/** Show a tab in its group, and make that group the one new tabs join. */
export function selectTab(id: EditorTabId): void {
  tabLayout.update((layout) => {
    const gid = groupOf(layout, id);
    if (!gid || (layout.groups[gid].active === id && layout.focused === gid)) return layout;
    return { ...layout, focused: gid, groups: { ...layout.groups, [gid]: { ...layout.groups[gid], active: id } } };
  });
}

/** Open a tab (if it is not one) and show it. */
export function showTab(id: EditorTabId): void {
  if (groupOf(get(tabLayout), id)) { selectTab(id); return; }
  // The alignment editors open on a verse (alignmentUi.ts), never from here.
  if (id === "alignment" || id === "crossVerse") return;
  wanted = id;
  if (id === "editor") versesOpen.set(true);
  else setSidePanel(id, { open: true, float: null, detached: false });
}

export function closeTab(id: EditorTabId): void {
  if (id === "editor") versesOpen.set(false);
  // Not in the middle of a save: the editor's own close is disabled then too.
  else if (id === "alignment") { if (!get(alignmentBusy)) closeWordAlignment(); }
  else if (id === "crossVerse") { if (!get(alignmentBusy)) closeCrossVerse(); }
  else setSidePanel(id, { open: false });
}

/** Move a tab into `target`, at `index` of its strip (the end when omitted). */
export function moveTab(id: EditorTabId, target: string, index?: number): void {
  tabLayout.update((layout) => {
    const source = groupOf(layout, id);
    if (!source || !layout.groups[target]) return layout;
    if (source === target) {
      const rest = layout.groups[target].tabs.filter((other) => other !== id);
      const at = Math.max(0, Math.min(index ?? rest.length, rest.length));
      const tabs = [...rest.slice(0, at), id, ...rest.slice(at)];
      return { ...layout, focused: target, groups: { ...layout.groups, [target]: { tabs, active: id } } };
    }
    const without_ = removeTab(layout, id);
    const group = without_.groups[target];
    const at = Math.max(0, Math.min(index ?? group.tabs.length, group.tabs.length));
    return { ...without_, focused: target,
      groups: { ...without_.groups, [target]: { tabs: [...group.tabs.slice(0, at), id, ...group.tabs.slice(at)], active: id } } };
  });
}

/** Split `target`: `id` becomes a new group on that edge of it. Nothing
 * happens when `id` is the only tab of `target` (there is nothing to split). */
export function splitTab(id: EditorTabId, target: string, edge: DockEdge): void {
  tabLayout.update((layout) => {
    const source = groupOf(layout, id);
    if (!source || !layout.groups[target] || !layout.tree) return layout;
    if (source === target && layout.groups[target].tabs.length === 1) return layout;
    const without_ = removeTab(layout, id);
    const gid = newGroupId();
    return {
      tree: dockPane(without_.tree!, gid, target, edge),
      groups: { ...without_.groups, [gid]: { tabs: [id], active: id } },
      focused: gid,
    };
  });
}

/** Make `group` the one a newly opened tab joins (a click on an empty group). */
export function focusGroup(group: string): void {
  tabLayout.update((layout) => (layout.groups[group] && layout.focused !== group ? { ...layout, focused: group } : layout));
}

/** Remove an empty group; its neighbour takes its room. */
export function closeGroup(group: string): void {
  tabLayout.update((layout) => {
    if (!layout.groups[group] || layout.groups[group].tabs.length) return layout;
    const groups = { ...layout.groups };
    delete groups[group];
    return { tree: layout.tree ? without(layout.tree, [group]) : null, groups,
      focused: layout.focused === group ? Object.keys(groups)[0] ?? "" : layout.focused };
  });
}

/**
 * Layout presets (2026-11-16, Joel), after VS Code's "Editor Layout": the
 * work area split a named way in one click. A shape's numbers are its places
 * in reading order. Dragging a tab still splits and moves as before.
 */
export const LAYOUT_PRESETS: readonly LayoutPreset[] = [
  { id: "single", label: "Single", shape: 0 },
  { id: "columns2", label: "Two columns", shape: across(0, 1) },
  { id: "columns3", label: "Three columns", shape: across(0, across(1, 2), 1 / 3) },
  { id: "rows2", label: "Two rows", shape: down(0, 1) },
  { id: "top1bottom2", label: "One on top, two below", shape: down(0, across(1, 2)) },
  { id: "top2bottom1", label: "Two on top, one below", shape: down(across(0, 1), 2) },
  { id: "left1right2", label: "One on the left, two on the right", shape: across(0, down(1, 2)) },
  { id: "left2right1", label: "Two on the left, one on the right", shape: across(down(0, 1), 2) },
  { id: "grid", label: "Grid: two by two", shape: down(across(0, 1), across(2, 3)) },
];

/** The preset the work area is split as now, if it is one of them. */
export const currentPreset = (layout: TabLayout): string | null => presetOf(layout.tree, LAYOUT_PRESETS);

/**
 * `layout` split as the preset `id`. The groups that hold tabs keep their
 * tabs and take the places in reading order; with more groups than places,
 * the rest join the last place; with fewer, the places left over are empty
 * groups, waiting for a panel (the left rail, or a dragged tab).
 */
export function withLayoutPreset(layout: TabLayout, id: string): TabLayout {
  const preset = LAYOUT_PRESETS.find((candidate) => candidate.id === id);
  if (!preset) return layout;
  const count = shapePlaces(preset.shape);
  const filled = (layout.tree ? leaves(layout.tree) : []).filter((gid) => layout.groups[gid]?.tabs.length);
  const groups: Record<string, TabGroup> = {};
  const gids: string[] = [];
  for (let place = 0; place < count; place += 1) {
    const gid = filled[place] ?? newGroupId();
    gids.push(gid);
    groups[gid] = filled[place] ? { ...layout.groups[gid] } : { tabs: [], active: null };
  }
  const last = gids[count - 1];
  for (const gid of filled.slice(count)) groups[last] = { tabs: [...groups[last].tabs, ...layout.groups[gid].tabs], active: groups[last].active };
  const focusedGone = !groups[layout.focused];
  const merged = filled.slice(count).includes(layout.focused);
  return { tree: shapeTree(preset.shape, gids, preset.id), groups, focused: merged ? last : focusedGone ? gids[0] : layout.focused };
}

export function applyLayoutPreset(id: string): void {
  tabLayout.update((layout) => withLayoutPreset(layout, id));
}

/** Set the share of the split `dividerId` (0.15 to 0.85). */
export function resizeSplit(dividerId: string, ratio: number): void {
  tabLayout.update((layout) => (layout.tree ? { ...layout, tree: resizeDivider(layout.tree, dividerId, ratio) } : layout));
}

/** A pane's box inside the work area: its group's frame, below the tab strip. */
export function paneStyle(frame: Frame | undefined): string {
  return frame
    ? `position:absolute;left:${frame.x}%;top:calc(${frame.y}% + ${TAB_STRIP_HEIGHT}px);width:${frame.width}%;height:calc(${frame.height}% - ${TAB_STRIP_HEIGHT}px);min-width:0`
    : "";
}
