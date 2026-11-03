import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { ReviewMessage } from "../../reviewWindow";

const mocks = vi.hoisted(() => ({
  open: vi.fn(), hide: vi.fn(), context: vi.fn(), error: vi.fn(), refresh: vi.fn(),
  receive: null as ((message: ReviewMessage) => void) | null,
  stop: vi.fn(),
}));
vi.mock("../../reviewWindow", () => ({
  desktopReviewAvailable: () => true,
  openReviewWindow: mocks.open, hideReviewWindow: mocks.hide,
  sendReviewContext: mocks.context, reviewWindowError: mocks.error,
  onReviewMessage: async (receive: (message: ReviewMessage) => void) => { mocks.receive = receive; return mocks.stop; },
}));
vi.mock("../../paratextReviewRefresh", () => ({ refreshParatextReviewEditor: mocks.refresh }));
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  paratextReviewQueue: async () => ({ items: [], book: "TIT", books: [], booksInScope: ["TIT"], status: "unresolved",
    state: { position: "", drafts: {}, scope: { books: ["TIT"] }, sessionStartedAt: "now" },
    counts: { total: 0, undecided: 0, applied: 0, rejected: 0, manual: 0, deferred: 0 } }),
} }));
import ReviewQueueHost from "../ReviewQueueHost.svelte";
import { project } from "../../stores";
import { paratextReviewQueueOpen } from "../../paratextNotes";

describe("review queue desktop ownership", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.open.mockResolvedValue(undefined);
    mocks.hide.mockResolvedValue(undefined);
    mocks.context.mockResolvedValue(undefined);
    project.set({ path: "book-a", bookId: "tit" } as never);
    paratextReviewQueueOpen.set(true);
  });

  it("moves one queue out, closes it independently, and reopens in the same window mode", async () => {
    render(ReviewQueueHost, { onNavigate: vi.fn() });
    const detach = await screen.findByRole("button", { name: "Move to separate window" });
    await waitFor(() => expect(detach).not.toBeDisabled());
    await fireEvent.click(detach);
    await waitFor(() => expect(mocks.open).toHaveBeenCalledOnce());
    expect(screen.queryByRole("dialog")).toBeNull();
    mocks.receive!({ kind: "ready" });
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ open: true, project: expect.objectContaining({ path: "book-a" }) })));
    mocks.receive!({ kind: "close", path: "book-a" });
    await waitFor(() => expect(get(paratextReviewQueueOpen)).toBe(false));
    paratextReviewQueueOpen.set(true);
    await waitFor(() => expect(mocks.open).toHaveBeenCalledTimes(2));
  });

  it("ignores old-window events after a project switch and refreshes only the current editor", async () => {
    localStorage.setItem("bridge.reviewQueue.detached", "true");
    const navigate = vi.fn();
    render(ReviewQueueHost, { onNavigate: navigate });
    await waitFor(() => expect(mocks.open).toHaveBeenCalledOnce());
    project.set({ path: "book-b", bookId: "phm" } as never);
    await waitFor(() => expect(mocks.context).toHaveBeenLastCalledWith(expect.objectContaining({ project: expect.objectContaining({ path: "book-b" }) })));
    mocks.receive!({ kind: "saved", path: "book-a", decision: {} as never });
    mocks.receive!({ kind: "navigate", path: "book-a", book: "TIT", chapter: "1", verse: "3-4" });
    mocks.receive!({ kind: "close", path: "book-a" });
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    expect(get(paratextReviewQueueOpen)).toBe(true);
    const decision = { chapter: "1", verse: "3-4", book: "PHM" } as never;
    mocks.receive!({ kind: "saved", path: "book-b", decision });
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledWith("book-b", decision));
    mocks.receive!({ kind: "dock", path: "book-b" });
    await screen.findByRole("dialog");
    expect(localStorage.getItem("bridge.reviewQueue.detached")).toBe("false");
  });

  it("falls back to the main panel when a native window cannot open", async () => {
    localStorage.setItem("bridge.reviewQueue.detached", "true");
    mocks.open.mockRejectedValueOnce(new Error("Window unavailable"));
    render(ReviewQueueHost, { onNavigate: vi.fn() });
    await screen.findByRole("alert");
    await screen.findByRole("dialog");
    expect(get(paratextReviewQueueOpen)).toBe(true);
  });
});
