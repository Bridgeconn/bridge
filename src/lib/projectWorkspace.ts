import { editorTree, validEditorTree } from "./editorDocking";
import type { LayoutNode } from "./alignmentLayout";
import { get } from "svelte/store";
import { localUserId } from "./stores";
import { sidePanels, sidePanelOrder, resetPanelLayout, validPanelSnapshot, type SidePanels, type SidePanelId } from "./editorPrefs";
import type { ProjectInfo, RegisteredProject } from "./types/finding";

export interface WorkspaceSnapshot {
  version: 1; book: string; chapter: string; verse: string; view: "editor" | "review";
  books?: Record<string, { chapter: string; verse: string; scroll: number; view: "editor" | "review" }>;
  scroll: number; tree?: LayoutNode | null; panels: SidePanels; order: SidePanelId[];
}
const identity = (p: { collectionId?: string; projectId?: string; path: string }) => p.collectionId || p.projectId || p.path;
const key = (kind: string, id = "") => `bridge.${kind}.v1.${encodeURIComponent(get(localUserId) || "local")}.${encodeURIComponent(id)}`;
function read<T>(name: string): T | null { try { return JSON.parse(localStorage.getItem(name) || "null"); } catch { return null; } }
function write(name: string, value: unknown) { try { localStorage.setItem(name, JSON.stringify(value)); } catch { /* session only */ } }
export function savedWorkspace(p: ProjectInfo | RegisteredProject): WorkspaceSnapshot | null {
  const v = read<WorkspaceSnapshot>(key("workspace", identity(p)));
  return v?.version === 1 && typeof v.book === "string" && typeof v.chapter === "string" && typeof v.verse === "string"
    && ["editor", "review"].includes(v.view) && Number.isFinite(v.scroll) && v.scroll >= 0
    && validEditorTree(v.tree ?? null) && validPanelSnapshot(v.panels, v.order) ? v : null;
}
export function savedBookWorkspace(p: ProjectInfo): WorkspaceSnapshot | null {
  const saved = savedWorkspace(p);
  if (!saved) return null;
  const book = saved.books?.[p.bookId.toLowerCase()];
  if (book && typeof book.chapter === "string" && typeof book.verse === "string" && Number.isFinite(book.scroll) && book.scroll >= 0 && ["editor", "review"].includes(book.view)) return { ...saved, ...book, book: p.bookId };
  return saved.book.toLowerCase() === p.bookId.toLowerCase() ? saved : null;
}
const initialPanels = structuredClone(get(sidePanels));
const initialOrder = [...get(sidePanelOrder)];
let active: { project: ProjectInfo; key: string; snapshot: WorkspaceSnapshot } | null = null;
let restoring = false;
export function bindWorkspace(p: ProjectInfo) {
  flushWorkspace();
  const saved = savedWorkspace(p);
  restoring = true;
  active = { project: p, key: key("workspace", identity(p)), snapshot: saved ?? { version: 1, book: p.bookId, chapter: "", verse: "", view: "editor", scroll: 0,
    panels: structuredClone(initialPanels), order: [...initialOrder] } };
  sidePanels.set(structuredClone(saved?.panels ?? initialPanels)); sidePanelOrder.set([...(saved?.order ?? initialOrder)]);
  editorTree.set(saved?.tree ?? null);
  restoring = false;
  return saved;
}
export function releaseWorkspace() { flushWorkspace(); active = null; }
export function flushWorkspace() { if (active && !restoring) write(active.key, active.snapshot); }
function layoutChanged() {
  if (!active || restoring) return;
  active.snapshot = { ...active.snapshot, panels: structuredClone(get(sidePanels)), order: [...get(sidePanelOrder)], tree: get(editorTree) };
  flushWorkspace();
}
editorTree.subscribe(layoutChanged); sidePanels.subscribe(layoutChanged); sidePanelOrder.subscribe(layoutChanged);
export function rememberLocation(p: ProjectInfo, chapter: string, verse: string | null, view: "editor" | "review") {
  if (!active || active.project.path !== p.path || !p.chapters.includes(chapter) || !verse) return;
  const same = active.snapshot.book === p.bookId && active.snapshot.chapter === chapter;
  const scroll = same ? active.snapshot.scroll : active.snapshot.books?.[p.bookId.toLowerCase()]?.chapter === chapter ? active.snapshot.books[p.bookId.toLowerCase()].scroll : 0;
  active.snapshot = { ...active.snapshot, book: p.bookId, chapter, verse, view, scroll,
    books: { ...active.snapshot.books, [p.bookId.toLowerCase()]: { chapter, verse, view, scroll } } };
  flushWorkspace();
}
export function rememberScroll(path: string, chapter: string, scroll: number) {
  if (!active || active.project.path !== path || active.snapshot.chapter !== chapter) return;
  active.snapshot.scroll = Math.max(0, scroll);
  if (active.snapshot.books?.[active.snapshot.book.toLowerCase()]) active.snapshot.books[active.snapshot.book.toLowerCase()].scroll = active.snapshot.scroll; // flushed on navigation, layout, pagehide or bounded scroll timer
}
export function resetWorkspaceLayout() { editorTree.set(null); resetPanelLayout(); }
export function recordProjectOpen(p: ProjectInfo) {
  const name = key("recentProjects");
  const rows = read<Record<string, { at: number; book: string }>>(name) || {};
  write(name, { ...rows, [identity(p)]: { at: Date.now(), book: p.bookId } });
}
export function recentProjects(projects: RegisteredProject[], limit = 5, _user = ""): RegisteredProject[] {
  const rows = read<Record<string, { at: number }>>(key("recentProjects")) || {};
  const seen = new Set<string>();
  return projects.filter(p => !p.missing && !p.archivedAt && !p.conflict && Number.isFinite(rows[identity(p)]?.at))
    .sort((a, b) => rows[identity(b)].at - rows[identity(a)].at)
    .filter(p => { const id = identity(p); if (seen.has(id)) return false; seen.add(id); return true; }).slice(0, limit);
}
if (typeof window !== "undefined") window.addEventListener("pagehide", flushWorkspace);
