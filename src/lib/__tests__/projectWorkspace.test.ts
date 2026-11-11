import { beforeEach, afterEach, expect, it } from "vitest";
import { get } from "svelte/store";
import { localUserId } from "../stores";
import { sidePanels, setSidePanel, resetPanelLayout } from "../editorPrefs";
import { editorTree, defaultEditorTree } from "../editorDocking";
import { bindWorkspace, savedWorkspace, savedBookWorkspace, rememberLocation, rememberScroll, flushWorkspace, releaseWorkspace, recordProjectOpen, recentProjects, resetWorkspaceLayout } from "../projectWorkspace";
import type { ProjectInfo, RegisteredProject } from "../types/finding";
const info = (id: string, book = "gen"): ProjectInfo => ({ path: `C:/${id}/${book}`, projectId: `${id}-${book}`, collectionId: id,
  bookId: book, bookName: book, targetLanguage: "Tamil", tcVersion: "3", chapters: ["1", "2"], checkTypes: {} });
const row = (id: string, patch = {}): RegisteredProject => ({ ...info(id), projectId: id, missing: false, managed: true, ...patch });
beforeEach(() => { releaseWorkspace(); localStorage.clear(); localUserId.set("alice"); resetPanelLayout(); editorTree.set(null); });
afterEach(releaseWorkspace);

it("restores exact references, reading position, layout and view independently for A → B → A", () => {
  const a = info("A"), b = info("B");
  bindWorkspace(a); rememberLocation(a, "2", "3-4", "review"); rememberScroll(a.path, "2", 412);
  setSidePanel("languageQa", { open: true, width: 620 }); editorTree.set(defaultEditorTree());
  bindWorkspace(b); rememberLocation(b, "1", "3a", "editor"); setSidePanel("languageQa", { width: 350 });
  const restored = bindWorkspace(a);
  expect(restored).toMatchObject({ chapter: "2", verse: "3-4", scroll: 412, view: "review" });
  expect(get(sidePanels).languageQa.width).toBe(620);
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
  setSidePanel("languageQa", { open: true, detached: true }); resetWorkspaceLayout();
  expect(savedWorkspace(a)).toMatchObject({ chapter: "2", verse: "3-4", view: "review" });
  expect(get(sidePanels).languageQa.detached).toBeUndefined();
  const name = Object.keys(localStorage).find(k => k.startsWith("bridge.workspace."))!;
  localStorage.setItem(name, "{"); expect(savedWorkspace(a)).toBeNull();
  localStorage.setItem(name, JSON.stringify({ version: 99 })); expect(savedWorkspace(a)).toBeNull();
});
it("Recent uses only this user's successful activity, filters unavailable rows and deduplicates collections", () => {
  recordProjectOpen(info("A")); recordProjectOpen(info("B"));
  const projects = [row("A"), row("A", { projectId: "A-exo" }), row("B", { archivedAt: "today" }), row("C")];
  expect(recentProjects(projects).map(p => p.collectionId)).toEqual(["A"]);
  expect(recentProjects([row("A", { missing: true })])).toEqual([]);
  localUserId.set("bob"); expect(recentProjects(projects)).toEqual([]);
});
