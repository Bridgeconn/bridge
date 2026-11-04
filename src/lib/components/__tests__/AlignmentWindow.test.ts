import { beforeEach, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { AlignmentWindowContext } from "../../alignmentWindow";
const mocks = vi.hoisted(() => ({ receive: null as ((value: AlignmentWindowContext) => void) | null }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({ onCloseRequested: async () => () => {} }) }));
vi.mock("../../alignmentWindow", async () => {
  const { writable } = await import("svelte/store");
  return { alignmentBusy: writable(false), alignmentPinned: writable(false), alignmentWindow: vi.fn(),
    sendAlignmentMessage: vi.fn().mockResolvedValue(undefined),
    onAlignmentContext: async (fn: (value: AlignmentWindowContext) => void) => { mocks.receive = fn; return () => {}; } };
});
import AlignmentWindow from "../AlignmentWindow.svelte";
import { alignmentBusy } from "../../alignmentWindow";
import { project } from "../../stores";
const context = (path: string, verse: string): AlignmentWindowContext => ({
  project: { path, bookId: "tit", bookName: "Titus", targetLanguage: "English", tcVersion: "7", chapters: ["1"], checkTypes: {} },
  chapter: "1", verse, verses: ["1", "2"], initialVerses: [], mode: "word", open: false, pinned: false, revision: 1 });
beforeEach(() => { mocks.receive = null; alignmentBusy.set(false); });
it("discards a deferred old-project context when the book changes during a mutation", async () => {
  render(AlignmentWindow);
  await waitFor(() => expect(mocks.receive).not.toBeNull());
  mocks.receive!(context("book-a", "1"));
  alignmentBusy.set(true);
  mocks.receive!(context("book-a", "2"));
  mocks.receive!(context("book-b", "1"));
  alignmentBusy.set(false);
  await waitFor(() => expect(get(project)?.path).toBe("book-b"));
});
