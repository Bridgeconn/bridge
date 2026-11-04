import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { AlignmentMessage } from "../../alignmentWindow";
const mocks = vi.hoisted(() => ({
  window: vi.fn(), context: vi.fn(), receive: null as ((value: AlignmentMessage) => void) | null,
}));
vi.mock("../../alignmentWindow", async () => {
  const { writable } = await import("svelte/store");
  return { alignmentBusy: writable(false), alignmentPinned: writable(false), alignmentDetached: writable(true),
    alignmentDesktop: () => true, alignmentWindow: mocks.window, sendAlignmentContext: mocks.context,
    onAlignmentMessage: async (fn: (value: AlignmentMessage) => void) => { mocks.receive = fn; return () => {}; } };
});
vi.mock("../../api/bridgeClient", () => ({ bridge: { getAlignment: vi.fn() } }));
import AlignmentHost from "../AlignmentHost.svelte";
import { alignmentOpen, alignmentKey, crossVerseOpen } from "../../alignmentUi";
import { alignmentBusy, alignmentPinned, alignmentDetached } from "../../alignmentWindow";
import { project, currentChapter, selectedVerse, chapterVerseNums } from "../../stores";

describe("alignment window ownership and navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks(); mocks.window.mockResolvedValue(undefined); mocks.context.mockResolvedValue(undefined);
    project.set({ path: "book-a", bookId: "tit" } as never);
    currentChapter.set("1"); selectedVerse.set("1"); chapterVerseNums.set({ "1": ["1", "2", "3-4"] });
    alignmentKey.set("1:1"); crossVerseOpen.set(false); alignmentOpen.set(true);
    alignmentPinned.set(false); alignmentBusy.set(false); alignmentDetached.set(true);
  });
  it("follows editor changes, pins a reference, and resynchronizes when unpinned", async () => {
    render(AlignmentHost);
    await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("open"));
    selectedVerse.set("2");
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ verse: "2", pinned: false })));
    mocks.receive!({ kind: "pin", path: "book-a" });
    await waitFor(() => expect(get(alignmentPinned)).toBe(true));
    selectedVerse.set("3-4");
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ verse: "2", pinned: true })));
    mocks.receive!({ kind: "pin", path: "book-a" });
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ verse: "3-4", pinned: false })));
  });
  it("defers following during a mutation and ignores messages from another project", async () => {
    render(AlignmentHost);
    await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("open"));
    mocks.receive!({ kind: "busy", path: "book-a", busy: true }); selectedVerse.set("2");
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ verse: "1" })));
    mocks.receive!({ kind: "close", path: "old-book" }); expect(get(alignmentOpen)).toBe(true);
    mocks.receive!({ kind: "busy", path: "book-a", busy: false });
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ verse: "2" })));
    project.set({ path: "book-b", bookId: "phm" } as never);
    await waitFor(() => expect(get(alignmentOpen)).toBe(false));
    await waitFor(() => expect(mocks.window).toHaveBeenCalledWith("hide"));
  });
});
