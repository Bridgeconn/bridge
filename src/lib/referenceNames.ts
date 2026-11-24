import { writable } from "svelte/store";

import { project } from "./stores";
import type { ReferenceChapter } from "./types/languageQa";

/**
 * What a reference Bible is called (#519), for its tab, its header and the
 * left rail's list. Apart from referenceTabs.ts, which places the tabs,
 * because a panel in its own window (PanelWindow) needs the names and must not
 * load the main window's tab layout with them.
 */

/** A reference's name as its tab and header show it: a bundled text says so. */
export function referenceHeading(source: ReferenceChapter["source"] | undefined): string {
  if (!source) return "";
  return source.origin === "bundled" ? `Built in: ${source.label.replace(/\s*\(bundled\)$/, "")}` : source.label;
}

/** The last part of a folder's path: the name the engine gives a reference. */
export function folderName(folder: string | undefined): string {
  return (folder ?? "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? "";
}

/** The project's reference Bible's name, once something has read it: its
 * panel, or the rail's list as it opens. Empty until then, and after a
 * change of project. The engine keeps the folder; this is only its name. */
export const projectReferenceName = writable("");
let boundProject = "";
project.subscribe((value) => {
  const identity = value ? value.collectionId || value.projectId || value.path : "";
  if (identity !== boundProject) { boundProject = identity; projectReferenceName.set(""); }
});
