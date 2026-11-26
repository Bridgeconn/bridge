import { editorTree, validEditorTree } from "./editorDocking";
import type { LayoutNode } from "./alignmentLayout";
import { get } from "svelte/store";
import { currentChapter, localUserId, project as openProject, selectedVerse } from "./stores";
import { REFERENCE_EXTRA_IDS, RETIRED_PANEL_IDS, versesOpen, sidePanels, sidePanelOrder, resetPanelLayout, validPanelSnapshot, withAddedPanels, withoutRetiredPanels, type SidePanels, type SidePanelId } from "./editorPrefs";
import { without } from "./alignmentLayout";
import { openTabs, reconcileTabs, resetTabLayout, tabLayout, validTabLayout, type TabLayout } from "./editorTabs";
import { alignmentOpen, crossVerseOpen, openAlignment, openCrossVerse } from "./alignmentUi";
import type { ProjectInfo, RegisteredProject } from "./types/finding";

/** What a book was left with (2026-11-16, Joel): whether the two alignment
 *  tabs were open, and how the work area's tabs were arranged. Kept per book
 *  beside its reading place, so coming back to the book (the next day, after
 *  another book or project) opens the same tabs in the same layout. */
export interface BookSession { alignment?: { word: boolean; cross: boolean }; tabs?: TabLayout }
export interface WorkspaceSnapshot {
  version: 1; book: string; chapter: string; verse: string; view: "editor" | "review";
  books?: Record<string, { chapter: string; verse: string; scroll: number; view: "editor" | "review" } & BookSession>;
  scroll: number; tree?: LayoutNode | null; panels: SidePanels; order: SidePanelId[];
  /** #525: the project was left on its dashboard (the book closed with the ×
   *  beside its name, or never entered), so it opens there again. Absent in a
   *  workspace saved before this existed, which opens inside its book. */
  onDashboard?: boolean;
}
const identity = (p: { collectionId?: string; projectId?: string; path: string }) => p.collectionId || p.projectId || p.path;
const key = (kind: string, id = "") => `bridge.${kind}.v1.${encodeURIComponent(get(localUserId) || "local")}.${encodeURIComponent(id)}`;
function read<T>(name: string): T | null { try { return JSON.parse(localStorage.getItem(name) || "null"); } catch { return null; } }
function write(name: string, value: unknown) { try { localStorage.setItem(name, JSON.stringify(value)); } catch { /* session only */ } }
export function savedWorkspace(p: ProjectInfo | RegisteredProject): WorkspaceSnapshot | null {
  const raw = read<WorkspaceSnapshot>(key("workspace", identity(p)));
  // #487: a workspace saved while Language QA was a panel keeps its place,
  // widths, order and arrangement; only the retired panel is taken out.
  // #519: one saved before the added reference tabs existed gains them, closed.
  const kept = raw && typeof raw === "object" ? withoutRetiredPanels(raw.panels, raw.order) : null;
  const v = raw && kept
    ? { ...raw, ...withAddedPanels(kept.panels, kept.order), tree: raw.tree ? without(raw.tree, RETIRED_PANEL_IDS) : raw.tree }
    : raw;
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
// What a project with no saved workspace starts from: the layout the app
// started with. The added reference tabs (#519) are a project's own, so they
// start closed and without a folder: the last project's must not carry over.
function withoutAddedReferences(panels: SidePanels): SidePanels {
  const next = structuredClone(panels);
  for (const id of REFERENCE_EXTRA_IDS) next[id] = { open: false, width: next[id].width };
  return next;
}
const initialPanels = withoutAddedReferences(get(sidePanels));
const initialOrder = [...get(sidePanelOrder)];
let active: { project: ProjectInfo; key: string; snapshot: WorkspaceSnapshot } | null = null;
let restoring = false;
// True from the moment a book is bound until its tabs are back
// (restoreBookSession): what happens in between is the app tidying up and
// putting things back, not the reviewer's doing, and must not be saved. A
// book switch, for one, closes the alignment tabs of the book being left
// after the new book is already bound.
let settling = false;
let restoreSeq = 0;
// The bound book's tabs are still to be put back: done at its first reading place.
let sessionDue = false;
export function bindWorkspace(p: ProjectInfo) {
  flushWorkspace();
  const saved = savedWorkspace(p);
  settling = true;
  sessionDue = true;
  restoreSeq += 1;
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
  // The book's first reading place since it was opened: the editor is on a
  // verse, whichever way it got there, so the book's tabs go back now.
  const restore = sessionDue;
  sessionDue = false;
  const same = active.snapshot.book === p.bookId && active.snapshot.chapter === chapter;
  const scroll = same ? active.snapshot.scroll : active.snapshot.books?.[p.bookId.toLowerCase()]?.chapter === chapter ? active.snapshot.books[p.bookId.toLowerCase()].scroll : 0;
  active.snapshot = { ...active.snapshot, book: p.bookId, chapter, verse, view, scroll,
    books: { ...active.snapshot.books, [p.bookId.toLowerCase()]: { ...active.snapshot.books?.[p.bookId.toLowerCase()], chapter, verse, view, scroll } } };
  flushWorkspace();
  if (restore) restoreBookSession(p);
}
/** #525: note whether the open project is showing its dashboard. Kept with the
 *  project's workspace, so each project (and each user) remembers its own; the
 *  reading place of every book is left as it was. */
export function rememberDashboard(p: ProjectInfo, onDashboard: boolean) {
  if (!active || active.project.path !== p.path || Boolean(active.snapshot.onDashboard) === onDashboard) return;
  active.snapshot = { ...active.snapshot, onDashboard };
  flushWorkspace();
}
/** #525: where a project opens: on its dashboard when it has no saved
 *  workspace or was left on the dashboard, inside its saved book otherwise. */
export function reopensOnDashboard(saved: WorkspaceSnapshot | null): boolean {
  return !saved || saved.onDashboard === true;
}
export function rememberScroll(path: string, chapter: string, scroll: number) {
  if (!active || active.project.path !== path || active.snapshot.chapter !== chapter) return;
  active.snapshot.scroll = Math.max(0, scroll);
  if (active.snapshot.books?.[active.snapshot.book.toLowerCase()]) active.snapshot.books[active.snapshot.book.toLowerCase()].scroll = active.snapshot.scroll; // flushed on navigation, layout, pagehide or bounded scroll timer
}
/** Note the open book's alignment tabs and tab layout, once it has settled. */
function recordSession(): void {
  if (!active || restoring || settling) return;
  const book = active.project.bookId.toLowerCase();
  const entry = active.snapshot.books?.[book];
  if (!entry) return; // no reading place yet: nothing to come back to
  active.snapshot = { ...active.snapshot, books: { ...active.snapshot.books,
    [book]: { ...entry, alignment: { word: get(alignmentOpen), cross: get(crossVerseOpen) }, tabs: get(tabLayout) } } };
  flushWorkspace();
}
alignmentOpen.subscribe(recordSession); crossVerseOpen.subscribe(recordSession); tabLayout.subscribe(recordSession);

/** What `p` was left with, or null. */
export function savedBookSession(p: ProjectInfo): BookSession | null {
  const entry = savedWorkspace(p)?.books?.[p.bookId.toLowerCase()];
  if (!entry) return null;
  const alignment = entry.alignment && typeof entry.alignment === "object"
    ? { word: Boolean(entry.alignment.word), cross: Boolean(entry.alignment.cross) } : undefined;
  return { alignment, tabs: validTabLayout(entry.tabs) ? entry.tabs : undefined };
}

/**
 * Put the open book's tabs back as it was left (2026-11-16, Joel): the tab
 * layout, and the Word alignment and Cross-verse tabs on the verse the editor
 * landed on. Runs at the book's first reading place (rememberLocation). An
 * alignment tab cannot open while a check run is going, so that is waited
 * for, a short while; saving starts again when this is done.
 */
export function restoreBookSession(p: ProjectInfo, options: { retryMs?: number; tries?: number } = {}): void {
  const token = ++restoreSeq;
  const session = savedBookSession(p);
  const wanted = session?.alignment;
  const applyTabs = (): void => { if (session?.tabs) tabLayout.set(reconcileTabs(session.tabs, get(openTabs))); };
  const done = (): void => { if (token === restoreSeq) { settling = false; recordSession(); } };
  applyTabs();
  if (!wanted?.word && !wanted?.cross) { done(); return; }
  const retryMs = options.retryMs ?? 500, limit = options.tries ?? 40;
  let tries = 0;
  const attempt = (): void => {
    if (token !== restoreSeq || get(openProject)?.path !== p.path) return; // another book since
    const chapter = get(currentChapter), verse = get(selectedVerse);
    let waiting = !verse;
    if (verse) {
      if (wanted.word && !get(alignmentOpen)) waiting = !openAlignment(chapter, verse) || waiting;
      if (wanted.cross && !get(crossVerseOpen)) waiting = !openCrossVerse(verse) || waiting;
    }
    if (waiting && (tries += 1) < limit) { setTimeout(attempt, retryMs); return; }
    // The tabs are open: now the saved layout has somewhere to put them.
    applyTabs();
    done();
  };
  attempt();
}

/** Reset layout (the last row of the top bar's layout picker): Verses and Review open, side by
 * side, every other panel closed and back in the Bridge window. */
export function resetWorkspaceLayout() { editorTree.set(null); resetPanelLayout(); versesOpen.set(true); resetTabLayout(); }
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
