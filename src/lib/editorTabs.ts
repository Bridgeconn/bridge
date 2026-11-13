import { derived, get, writable, type Readable } from "svelte/store";

import { dockPane, leaves, resizeDivider, without, type DockEdge, type Frame, type LayoutNode } from "./alignmentLayout";
import { setSidePanel, sidePanelOrder, sidePanels, tabRequest, versesOpen } from "./editorPrefs";
import type { SidePanelId } from "./editorPrefs";

/**
 * The editor's work area as tab groups (2026-11-14), after VS Code. The verse
 * list and every docked side panel that is open is one tab. Tabs sit in
 * groups; a group shows one of its tabs at a time, under its own tab strip.
 * The area starts as one or two groups and is split by dragging a tab to an
 * edge of a group (left, right, top, bottom); dragging it onto a group moves
 * it there; the line between two groups drags to resize them. A panel in its
 * own window is not a tab.
 *
 * Whether a pane is open at all stays where it always was (`versesOpen`,
 * `sidePanels`): this module only places the open ones, and is reconciled
 * every time that set changes, so every existing route that opens or closes a
 * panel keeps working.
 */
export type EditorTabId = "editor" | SidePanelId;

/** Name and icon (a UiIcon name) of each tab; the left rail uses the same. */
export const EDITOR_TABS: Readonly<Record<EditorTabId, { label: string; icon: string; title: string }>> = {
  editor: { label: "Verses", icon: "verses", title: "Verses: the text of this chapter" },
  source: { label: "Source", icon: "source", title: "Source: the Hebrew, Aramaic or Greek" },
  reference: { label: "Reference", icon: "open", title: "Reference: a reference Bible" },
  paratext: { label: "Paratext", icon: "notes", title: "Paratext: Project Notes on the selected verse" },
  review: { label: "Review", icon: "review", title: "Review: Greek Room, Core check, Language QA and AI review" },
};
const TAB_IDS = Object.keys(EDITOR_TABS) as EditorTabId[];

/** The tab strip's height in px: a pane starts this far below its group's top. */
export const TAB_STRIP_HEIGHT = 36;

export interface TabGroup { tabs: EditorTabId[]; active: EditorTabId }
/** `tree`'s leaves are the keys of `groups`; `focused` is the group last
 * used, where a newly opened tab goes. */
export interface TabLayout { tree: LayoutNode | null; groups: Record<string, TabGroup>; focused: string }

/** Every open tab: Verses first, then the panels in their saved order. */
export const openTabs: Readable<EditorTabId[]> = derived(
  [versesOpen, sidePanels, sidePanelOrder],
  ([verses, panels, order]) => [
    ...(verses ? ["editor" as const] : []),
    ...order.filter((id) => panels[id].open && !panels[id].detached),
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
      tree: { id: "split-default", axis: "horizontal", ratio: 0.6, first: "g-main", second: "g-side" },
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
    const gid = next.groups[next.focused] ? next.focused : gids[0];
    next = { ...next, focused: gid, groups: { ...next.groups, [gid]: { tabs: [...next.groups[gid].tabs, id], active: id } } };
  }
  return next;
}

function validTabLayout(value: unknown): value is TabLayout {
  const v = value as TabLayout;
  if (!v || typeof v !== "object" || typeof v.focused !== "string" || !v.groups || typeof v.groups !== "object") return false;
  const gids = Object.keys(v.groups);
  const seen = new Set<string>();
  for (const gid of gids) {
    const group = v.groups[gid];
    if (!group || !Array.isArray(group.tabs) || !group.tabs.length || !group.tabs.includes(group.active)) return false;
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
  tabLayout, (layout) => new Set(Object.values(layout.groups).map((group) => group.active)),
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
  wanted = id;
  if (id === "editor") versesOpen.set(true);
  else setSidePanel(id, { open: true, float: null, detached: false });
}

export function closeTab(id: EditorTabId): void {
  if (id === "editor") versesOpen.set(false);
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
