import { beforeEach, afterEach, expect, it } from "vitest";
import { get } from "svelte/store";
import { localUserId } from "../stores";
import { REFERENCE_EXTRA_IDS, sidePanels, setSidePanel, resetPanelLayout } from "../editorPrefs";
import { leaves } from "../alignmentLayout";
import { editorTree, defaultEditorTree } from "../editorDocking";
import { bindWorkspace, savedWorkspace, savedBookWorkspace, rememberLocation, rememberDashboard, reopensOnDashboard, rememberScroll, flushWorkspace, releaseWorkspace, recordProjectOpen, recentProjects, resetWorkspaceLayout } from "../projectWorkspace";
import type { ProjectInfo, RegisteredProject } from "../types/finding";
const info = (id: string, book = "gen"): ProjectInfo => ({ path: `C:/${id}/${book}`, projectId: `${id}-${book}`, collectionId: id,
  bookId: book, bookName: book, targetLanguage: "Tamil", tcVersion: "3", chapters: ["1", "2"], checkTypes: {} });
const row = (id: string, patch = {}): RegisteredProject => ({ ...info(id), projectId: id, missing: false, managed: true, ...patch });
beforeEach(() => { releaseWorkspace(); localStorage.clear(); localUserId.set("alice"); resetPanelLayout(); editorTree.set(null); });
afterEach(releaseWorkspace);

it("restores exact references, reading position, layout and view independently for A → B → A", () => {
  const a = info("A"), b = info("B");
  bindWorkspace(a); rememberLocation(a, "2", "3-4", "review"); rememberScroll(a.path, "2", 412);
  setSidePanel("paratext", { open: true, width: 620 }); editorTree.set(defaultEditorTree());
  bindWorkspace(b); rememberLocation(b, "1", "3a", "editor"); setSidePanel("paratext", { width: 350 });
  const restored = bindWorkspace(a);
  expect(restored).toMatchObject({ chapter: "2", verse: "3-4", scroll: 412, view: "review" });
  expect(get(sidePanels).paratext.width).toBe(620);
  expect(get(editorTree)).toEqual(defaultEditorTree());
  expect(savedWorkspace(b)?.verse).toBe("3a");
});
it("rejects stale navigation and scroll writes from a different book", () => {
  const a = info("A"), b = info("B"); bindWorkspace(a); rememberLocation(a, "2", "3a", "editor");
  bindWorkspace(b); rememberLocation(b, "1", "1", "editor");
  rememberLocation(a, "2", "9", "review"); rememberScroll(a.path, "2", 800); flushWorkspace();
  expect(savedWorkspace(b)).toMatchObject({ chapter: "1", verse: "1", scroll: 0 });
});
it("retains independent reading locations when switching sibling books within a collection", () => {
  const gen = info("A", "gen"), exo = info("A", "exo");
  bindWorkspace(gen); rememberLocation(gen, "2", "3a", "editor"); rememberScroll(gen.path, "2", 220);
  bindWorkspace(exo); rememberLocation(exo, "1", "3-4", "review");
  bindWorkspace(gen);
  expect(savedBookWorkspace(gen)).toMatchObject({ chapter: "2", verse: "3a", scroll: 220 });
  expect(savedBookWorkspace(exo)).toMatchObject({ chapter: "1", verse: "3-4", view: "review" });
});
it("keeps local users independent and never writes Alice's active layout under Bob's key", () => {
  const a = info("A"); bindWorkspace(a); rememberLocation(a, "2", "3a", "editor");
  localUserId.set("bob"); setSidePanel("reference", { width: 400 });
  expect(savedWorkspace(a)).toBeNull();
  bindWorkspace(a); rememberLocation(a, "1", "1", "editor");
  localUserId.set("alice"); expect(savedWorkspace(a)?.verse).toBe("3a");
});
it("invalid or corrupt saved state cannot block opening, and reset only changes layout", () => {
  const a = info("A"); bindWorkspace(a); rememberLocation(a, "2", "3-4", "review");
  setSidePanel("paratext", { open: true, detached: true }); resetWorkspaceLayout();
  expect(savedWorkspace(a)).toMatchObject({ chapter: "2", verse: "3-4", view: "review" });
  expect(get(sidePanels).paratext.detached).toBeUndefined();
  const name = Object.keys(localStorage).find(k => k.startsWith("bridge.workspace."))!;
  localStorage.setItem(name, "{"); expect(savedWorkspace(a)).toBeNull();
  localStorage.setItem(name, JSON.stringify({ version: 99 })); expect(savedWorkspace(a)).toBeNull();
});
// #487: Language QA was a panel when this workspace was saved.
it("reads a workspace saved with the retired Language QA panel, keeping its place, widths, order and arrangement", () => {
  const a = info("A"); bindWorkspace(a); rememberLocation(a, "2", "3-4", "review");
  setSidePanel("reference", { open: true, width: 410 }); flushWorkspace();
  const name = Object.keys(localStorage).find(k => k.startsWith("bridge.workspace."))!;
  const old = JSON.parse(localStorage.getItem(name)!);
  old.panels.languageQa = { open: false, width: 440 };
  old.order = ["source", "reference", "languageQa", "paratext", "review"];
  old.tree = { id: "x", axis: "horizontal", ratio: .5, first: defaultEditorTree(), second: "languageQa" };
  releaseWorkspace(); localStorage.setItem(name, JSON.stringify(old));
  const saved = savedWorkspace(a);
  expect(saved).toMatchObject({ chapter: "2", verse: "3-4", view: "review", order: ["source", "reference", "paratext", "review", "reference2", "reference3", "reference4"] });
  expect(saved!.panels.reference).toMatchObject({ open: true, width: 410 });
  expect("languageQa" in saved!.panels).toBe(false);
  expect(saved!.tree).toEqual(defaultEditorTree());
});
// #519: the added reference tabs are new panel ids. A workspace saved before
// them is validated whole, so without care its reading place would be lost.
it("reads a workspace saved before the added reference tabs, with its place, its panels and its older arrangement", () => {
  const a = info("A"); bindWorkspace(a); rememberLocation(a, "2", "3-4", "review");
  setSidePanel("reference", { open: true, width: 410 }); editorTree.set(defaultEditorTree()); flushWorkspace();
  const name = Object.keys(localStorage).find(k => k.startsWith("bridge.workspace."))!;
  const old = JSON.parse(localStorage.getItem(name)!);
  for (const id of REFERENCE_EXTRA_IDS) delete old.panels[id];
  old.order = ["source", "reference", "paratext", "review"];
  expect(leaves(old.tree).sort()).toEqual(["editor", "paratext", "reference", "review", "source"]);
  releaseWorkspace(); localStorage.setItem(name, JSON.stringify(old));
  const saved = savedWorkspace(a);
  expect(saved).toMatchObject({ chapter: "2", verse: "3-4", view: "review" });
  expect(saved!.panels.reference).toMatchObject({ open: true, width: 410 });
  for (const id of REFERENCE_EXTRA_IDS) expect(saved!.panels[id], id).toEqual({ open: false, width: 300 });
  expect(saved!.order).toEqual(["source", "reference", "paratext", "review", ...REFERENCE_EXTRA_IDS]);
  expect(saved!.tree).toEqual(defaultEditorTree());
  bindWorkspace(a);
  expect(get(sidePanels).reference).toMatchObject({ open: true, width: 410 });
});
it("keeps an added reference's folder with its project, and a project with no saved workspace starts without any", () => {
  const a = info("A"), b = info("B"), c = info("C");
  bindWorkspace(a); rememberLocation(a, "1", "1", "editor");
  setSidePanel("reference2", { open: true, folder: "D:/bibles/esv" });
  setSidePanel("reference3", { folder: "D:/bibles/niv" });
  // B has its own: A's do not follow the reviewer there.
  bindWorkspace(b); rememberLocation(b, "1", "1", "editor");
  expect(get(sidePanels).reference2).toMatchObject({ open: false });
  expect(get(sidePanels).reference2.folder).toBeUndefined();
  expect(get(sidePanels).reference3.folder).toBeUndefined();
  setSidePanel("reference2", { open: true, folder: "D:/bibles/kjv" });
  // Back on A, also from a sibling book of the same collection.
  bindWorkspace(info("A", "exo"));
  expect(get(sidePanels).reference2).toMatchObject({ open: true, folder: "D:/bibles/esv" });
  expect(get(sidePanels).reference3).toMatchObject({ open: false, folder: "D:/bibles/niv" });
  expect(savedWorkspace(b)!.panels.reference2.folder).toBe("D:/bibles/kjv");
  bindWorkspace(c);
  for (const id of REFERENCE_EXTRA_IDS) { expect(get(sidePanels)[id].open, id).toBe(false); expect(get(sidePanels)[id].folder, id).toBeUndefined(); }
});
it("Recent uses only this user's successful activity, filters unavailable rows and deduplicates collections", () => {
  recordProjectOpen(info("A")); recordProjectOpen(info("B"));
  const projects = [row("A"), row("A", { projectId: "A-exo" }), row("B", { archivedAt: "today" }), row("C")];
  expect(recentProjects(projects).map(p => p.collectionId)).toEqual(["A"]);
  expect(recentProjects([row("A", { missing: true })])).toEqual([]);
  localUserId.set("bob"); expect(recentProjects(projects)).toEqual([]);
});
// #525: a project left on its dashboard (the book closed with the x beside its
// name) opens there again; one left inside a book opens inside it.
it("remembers, per project, that it was left on its dashboard, and keeps every book's reading place", () => {
  const a = info("A"), b = info("B");
  expect(reopensOnDashboard(bindWorkspace(a))).toBe(true); // never opened: the dashboard
  rememberLocation(a, "2", "3a", "editor");
  bindWorkspace(b); rememberLocation(b, "1", "1", "editor");
  expect(reopensOnDashboard(bindWorkspace(a))).toBe(false); // left inside a book, as before
  rememberDashboard(a, true); // the book is closed to the dashboard
  expect(reopensOnDashboard(bindWorkspace(b))).toBe(false); // B keeps its own state
  const saved = bindWorkspace(a);
  expect(reopensOnDashboard(saved)).toBe(true);
  expect(saved).toMatchObject({ chapter: "2", verse: "3a" });
  expect(savedBookWorkspace(a)).toMatchObject({ chapter: "2", verse: "3a" });
  rememberDashboard(a, false); // the book is opened from the dashboard
  releaseWorkspace();
  expect(reopensOnDashboard(savedWorkspace(a))).toBe(false);
});
it("keeps the dashboard note per user, drops one for a book that is not bound, and reads an older workspace as inside its book", () => {
  const a = info("A"), b = info("B");
  bindWorkspace(a); rememberLocation(a, "2", "3a", "editor");
  rememberDashboard(b, true); // a late call for another project
  flushWorkspace();
  expect(savedWorkspace(a)?.onDashboard).toBeUndefined(); // as a workspace saved before #525
  expect(reopensOnDashboard(savedWorkspace(a))).toBe(false);
  expect(savedWorkspace(b)).toBeNull();
  rememberDashboard(a, true);
  localUserId.set("bob");
  expect(reopensOnDashboard(bindWorkspace(a))).toBe(true); // Bob never opened it
  rememberLocation(a, "1", "1", "editor");
  localUserId.set("alice");
  expect(savedWorkspace(a)).toMatchObject({ onDashboard: true, chapter: "2", verse: "3a" });
});
