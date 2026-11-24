import { derived, get, type Readable } from "svelte/store";

import {
  REFERENCE_EXTRA_IDS, REFERENCE_PANEL_IDS, isReferencePanel, setSidePanel, sidePanels,
  type AddedReferenceId, type ReferencePanelId, type SidePanels,
} from "./editorPrefs";
import { EDITOR_TABS, showTab, type EditorTabId } from "./editorTabs";
import { panelDesktop, panelWindow } from "./panelWindow";
import { folderName, projectReferenceName } from "./referenceNames";

export { folderName, projectReferenceName, referenceHeading } from "./referenceNames";

/**
 * Several reference Bibles side by side (#519). The first reference tab
 * (`reference`) is the project's reference Bible, the one Language QA checks
 * against (#289); a reviewer can add up to three more, each a folder of their
 * own, for reading only. An added reference is a fixed place (`reference2` to
 * `reference4`, editorPrefs.ts) that holds its folder in the panel's saved
 * state, so it comes back with the project and stays in the left rail's list
 * after its tab is closed, until it is removed there.
 */

function nameOf(id: ReferencePanelId, panels: SidePanels, projectName: string): string {
  return id === "reference" ? projectName : folderName(panels[id].folder);
}

/** Each tab's name. A reference tab is named after its reference ("esv"),
 * or "Reference" until one is chosen; every other tab keeps its fixed name. */
export const tabLabels: Readable<Record<EditorTabId, string>> = derived([sidePanels, projectReferenceName], ([panels, projectName]) =>
  Object.fromEntries((Object.keys(EDITOR_TABS) as EditorTabId[]).map((id) =>
    [id, (isReferencePanel(id) && nameOf(id, panels, projectName)) || EDITOR_TABS[id].label])) as Record<EditorTabId, string>);

export interface ReferenceEntry {
  id: ReferencePanelId;
  /** Its name, or "" when none is chosen yet. */
  name: string;
  /** Its tab is open, or it is in its own window. */
  open: boolean;
  detached: boolean;
  /** Added by a reviewer (it can be removed), not the project's own. */
  added: boolean;
}

/** The left rail's list: the project's reference first, then each added one
 * (open, or closed with its folder kept), in the order of their places. */
export const referenceEntries: Readable<ReferenceEntry[]> = derived([sidePanels, projectReferenceName], ([panels, projectName]) =>
  REFERENCE_PANEL_IDS.filter((id) => id === "reference" || panels[id].open || Boolean(panels[id].folder)).map((id) => ({
    id, name: nameOf(id, panels, projectName), open: panels[id].open, detached: panels[id].open && Boolean(panels[id].detached), added: id !== "reference",
  })));

/** The rail's icon opens the list rather than the tab: something is open, or
 * a reference was added. Otherwise a click opens the project's reference. */
export const referenceListNeeded: Readable<boolean> = derived(referenceEntries, (entries) => entries.some((entry) => entry.open || entry.added));

const freeSlot = (panels: SidePanels): AddedReferenceId | null =>
  REFERENCE_EXTRA_IDS.find((id) => !panels[id].open && !panels[id].folder) ?? null;

/** There is a place left for one more reference (four in all). */
export const canAddReference: Readable<boolean> = derived(sidePanels, (panels) => freeSlot(panels) !== null);

/** Open a new, empty reference tab, where a folder is then chosen. Returns
 * its id, or null when all four places are taken. */
export function addReference(): AddedReferenceId | null {
  const id = freeSlot(get(sidePanels));
  if (id) showTab(id);
  return id;
}

/** Take an added reference out of the list: its tab or window closes and its
 * folder is forgotten. The folder itself is not touched. */
export function removeReference(id: AddedReferenceId): void {
  setSidePanel(id, { open: false, detached: false, folder: undefined });
}

/** Show a reference: its tab (opened if it was closed), or its own window
 * brought to the front. */
export function showReference(id: ReferencePanelId): void {
  const state = get(sidePanels)[id];
  if (state.open && state.detached) {
    if (panelDesktop()) void panelWindow(id, "focus").catch(() => { /* it stays where it is */ });
    return;
  }
  showTab(id);
}
