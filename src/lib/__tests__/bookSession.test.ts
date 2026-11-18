import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { leaves } from "../alignmentLayout";
import { alignmentOpen, closeAlignment, closeWordAlignment, crossVerseOpen, openAlignment, openCrossVerse } from "../alignmentUi";
import { resetPanelLayout, setSidePanel, versesOpen } from "../editorPrefs";
import { editorTree } from "../editorDocking";
import { groupOf, openTabs, resetTabLayout, splitTab, tabLayout } from "../editorTabs";
import { bindWorkspace, releaseWorkspace, rememberLocation, savedBookSession } from "../projectWorkspace";
import { checkingProgress, currentChapter, localUserId, project, selectedVerse } from "../stores";
import type { ProjectInfo } from "../types/finding";

// 2026-11-16 (Joel): a book comes back as it was left: its alignment tabs
// open again, in the layout they were in.
const info = (id: string, book = "gen"): ProjectInfo => ({ path: `C:/${id}/${book}`, projectId: `${id}-${book}`, collectionId: id,
  bookId: book, bookName: book, targetLanguage: "Tamil", tcVersion: "3", chapters: ["1", "2"], checkTypes: {} });

/** Open `p` as the app does: bind it, make it the project, land on a verse. */
function open(p: ProjectInfo, chapter = "1", verse = "1"): void {
  bindWorkspace(p);
  project.set(p);
  // AlignmentHost closes the editors when the project changes; it is not mounted here.
  closeAlignment();
  currentChapter.set(chapter); selectedVerse.set(verse);
  rememberLocation(p, chapter, verse, "editor");
}
const groupsInOrder = () => { const layout = get(tabLayout); return (layout.tree ? leaves(layout.tree) : []).map((gid) => layout.groups[gid].tabs); };

beforeEach(() => {
  releaseWorkspace(); localStorage.clear(); localUserId.set("alice");
  closeAlignment(); resetPanelLayout(); editorTree.set(null); versesOpen.set(true);
  for (const id of ["source", "reference", "paratext", "review"] as const) setSidePanel(id, { open: false });
  resetTabLayout();
  checkingProgress.set({ ...get(checkingProgress), running: false });
});
afterEach(() => { releaseWorkspace(); vi.useRealTimers(); });

it("reopens a book's alignment tabs in the layout they were left in", () => {
  const a = info("A");
  open(a, "2", "5");
  expect(openAlignment("2", "5")).toBe(true);
  expect(openCrossVerse("5")).toBe(true);
  splitTab("alignment", groupOf(get(tabLayout), "alignment")!, "right");
  splitTab("crossVerse", groupOf(get(tabLayout), "crossVerse")!, "bottom");
  // Each alignment tab has a group of its own now, beside the book's other tabs.
  const left = groupsInOrder();
  expect(left).toContainEqual(["alignment"]);
  expect(left).toContainEqual(["crossVerse"]);
  expect(savedBookSession(a)?.alignment).toEqual({ word: true, cross: true });

  // Back to the project list: the project is released first, then its editors close.
  releaseWorkspace(); project.set(null); closeAlignment(); resetTabLayout();
  expect(get(openTabs)).not.toContain("alignment");
  expect(groupsInOrder()).not.toEqual(left);
  // Closing the app's tabs on the way out was not the reviewer's doing.
  expect(savedBookSession(a)?.alignment).toEqual({ word: true, cross: true });

  open(a, "2", "5");
  expect(get(alignmentOpen)).toBe(true);
  expect(get(crossVerseOpen)).toBe(true);
  // The same groups, in the same places, as when the book was left.
  expect(groupsInOrder()).toEqual(left);
});

it("remembers that a tab was closed, and keeps each book's tabs apart", () => {
  const gen = info("A", "gen"), exo = info("A", "exo");
  open(gen);
  openAlignment("1", "1");
  // A sibling book: the app binds it, then the first book's editors close. That is not saved for either.
  open(exo);
  expect(get(alignmentOpen)).toBe(false);
  expect(savedBookSession(gen)?.alignment).toEqual({ word: true, cross: false });
  openCrossVerse("1");
  open(gen);
  expect(get(alignmentOpen)).toBe(true);
  expect(get(crossVerseOpen)).toBe(false);
  // The reviewer closes the tab: that is remembered.
  closeWordAlignment();
  expect(savedBookSession(gen)?.alignment).toEqual({ word: false, cross: false });
  open(exo);
  expect(get(alignmentOpen)).toBe(false);
  expect(get(crossVerseOpen)).toBe(true);
});

it("waits for a check run to end before reopening an alignment tab", () => {
  vi.useFakeTimers();
  const a = info("A");
  open(a);
  openAlignment("1", "1");
  releaseWorkspace(); project.set(null); closeAlignment();
  checkingProgress.set({ ...get(checkingProgress), running: true });
  open(a);
  expect(get(alignmentOpen)).toBe(false);
  vi.advanceTimersByTime(1200);
  expect(get(alignmentOpen)).toBe(false);
  checkingProgress.set({ ...get(checkingProgress), running: false });
  vi.advanceTimersByTime(600);
  expect(get(alignmentOpen)).toBe(true);
});

it("opens a book that was never worked on with no alignment tab, and a stored layout that is not valid is ignored", () => {
  const a = info("A");
  open(a);
  expect(get(alignmentOpen)).toBe(false);
  expect(savedBookSession(a)).toMatchObject({ alignment: { word: false, cross: false } });
  const name = Object.keys(localStorage).find((k) => k.startsWith("bridge.workspace."))!;
  const stored = JSON.parse(localStorage.getItem(name)!);
  stored.books.gen.tabs = { tree: "nope", groups: {}, focused: 3 };
  releaseWorkspace(); localStorage.setItem(name, JSON.stringify(stored));
  expect(savedBookSession(a)?.tabs).toBeUndefined();
  open(a);
  expect(groupsInOrder().flat()).toEqual(get(openTabs));
  expect(get(openTabs)).not.toContain("alignment");
});
