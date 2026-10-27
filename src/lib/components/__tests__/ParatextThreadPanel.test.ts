import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

const { paratextThreadsFor, paratextReplyThread, paratextResolveThread, paratextLinkThread, paratextNotesForVerse } =
  vi.hoisted(() => ({
    paratextThreadsFor: vi.fn(),
    paratextReplyThread: vi.fn(),
    paratextResolveThread: vi.fn(),
    paratextLinkThread: vi.fn(),
    paratextNotesForVerse: vi.fn(),
  }));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { paratextThreadsFor, paratextReplyThread, paratextResolveThread, paratextLinkThread, paratextNotesForVerse },
}));

import ParatextThreadPanel from "../ParatextThreadPanel.svelte";
import type { ParatextNoteThread, ParatextThreadsFor } from "../../types/paratext";

function thread(overrides: Partial<ParatextNoteThread> = {}): ParatextNoteThread {
  return {
    id: "T1", kind: "note", status: "todo", resolved: false, verseRef: "TIT 1:1", verse: "1", users: ["Yesu Selva Benz"],
    firstDate: "2026-10-26T10:00:00+05:30", lastDate: "2026-10-26T10:00:00+05:30", lastUser: "Yesu Selva Benz",
    excerpt: "Bridge review", selectedText: "", assignedUser: "", tags: [], hidden: false, commentCount: 1,
    contextBefore: "", contextAfter: "",
    comments: [{ user: "Yesu Selva Benz", date: "2026-10-26T10:00:00+05:30",
      contents: "Bridge Translation Note review\n\nReviewer note: look again\n\n[Bridge ref bridge-r1-abc]",
      status: "todo", type: "", assignedUser: null, replyToUser: "", language: "ta", tagsAdded: [], tagsRemoved: [] }],
    ...overrides,
  };
}

function data(overrides: Partial<ParatextThreadsFor> = {}): ParatextThreadsFor {
  return {
    state: "ready",
    links: [{ kind: "issue_resolution", localId: "r1", threadId: "T1", messageId: "bridge-r1-abc",
      direction: "bridge_to_paratext", thread: thread() }],
    pending: [],
    ...overrides,
  };
}

const props = { kind: "issue_resolution" as const, localId: "r1", chapter: "1", verse: "1" };

describe("ParatextThreadPanel (#358)", () => {
  beforeEach(() => {
    for (const fn of [paratextThreadsFor, paratextReplyThread, paratextResolveThread, paratextLinkThread, paratextNotesForVerse]) {
      fn.mockReset();
    }
  });

  it("shows the linked thread without the Bridge footer, and replies and resolves through the outbox", async () => {
    paratextThreadsFor.mockResolvedValue(data());
    paratextReplyThread.mockResolvedValue({ item: { status: "sent", lastError: "" } });
    paratextResolveThread.mockResolvedValue({ item: { status: "queued", lastError: "Paratext is offline" } });
    render(ParatextThreadPanel, props);

    expect(await screen.findByText("Open in Paratext")).toBeTruthy();
    const text = screen.getByText(/Reviewer note: look again/).textContent ?? "";
    expect(text).not.toContain("[Bridge ref");

    await fireEvent.click(screen.getByRole("button", { name: "Reply" }));
    const box = screen.getByPlaceholderText("Your reply, as you");
    await fireEvent.input(box, { target: { value: "Changed in Bridge." } });
    await fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    expect(paratextReplyThread).toHaveBeenCalledWith("T1", "Changed in Bridge.", "issue_resolution", "r1");
    expect(await screen.findByText("Reply sent to Paratext.")).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Resolve in Paratext" }));
    expect(paratextResolveThread).toHaveBeenCalledWith("T1", "issue_resolution", "r1");
    expect(await screen.findByText(/Queued for Paratext\. Paratext is offline/)).toBeTruthy();
  });

  it("shows a Paratext done as Resolved in Paratext, offers no Resolve, and changes nothing else", async () => {
    paratextThreadsFor.mockResolvedValue(data({
      links: [{ kind: "issue_resolution", localId: "r1", threadId: "T1", messageId: "", direction: "bridge_to_paratext",
        thread: thread({ resolved: true, status: "deleted" }) }],
    }));
    render(ParatextThreadPanel, props);
    const badge = await screen.findByText("Resolved in Paratext");
    expect(badge.getAttribute("title")).toMatch(/status changes only if you mark it resolved/);
    expect(screen.queryByRole("button", { name: "Resolve in Paratext" })).toBeNull();
    // No owner callback: no one-click offer either.
    expect(screen.queryByRole("button", { name: "Mark resolved in Bridge" })).toBeNull();
    expect(paratextResolveThread).not.toHaveBeenCalled();
  });

  it("offers decision 3's one click on a Paratext done, and not once Bridge is resolved", async () => {
    paratextThreadsFor.mockResolvedValue(data({
      links: [{ kind: "issue_resolution", localId: "r1", threadId: "T1", messageId: "", direction: "bridge_to_paratext",
        thread: thread({ resolved: true, status: "deleted" }) }],
    }));
    const onResolveHere = vi.fn().mockRejectedValue(new Error("Paratext does not show that thread as resolved"));
    const view = render(ParatextThreadPanel, { ...props, onResolveHere });
    await fireEvent.click(await screen.findByRole("button", { name: "Mark resolved in Bridge" }));
    expect(onResolveHere).toHaveBeenCalledWith("T1");
    expect(await screen.findByText(/does not show that thread as resolved/)).toBeTruthy();
    expect(paratextResolveThread).not.toHaveBeenCalled();

    await view.component.$set({ bridgeResolved: true });
    expect(screen.queryByRole("button", { name: "Mark resolved in Bridge" })).toBeNull();
  });

  it("says a sent note is waiting for the notes file, and lists queued writes with their reason", async () => {
    paratextThreadsFor.mockResolvedValue(data({
      links: [{ kind: "issue_resolution", localId: "r1", threadId: "T1", messageId: "m", direction: "bridge_to_paratext", thread: null }],
      pending: [{ messageId: "m2", op: "add_comment", threadId: "T1", status: "queued", attempts: 1,
        lastError: "Paratext is offline", sentAt: "", resultKey: "", createdAt: "" }],
    }));
    render(ParatextThreadPanel, props);
    expect(await screen.findByText(/thread shows here once Bridge has read/)).toBeTruthy();
    expect(screen.getByText(/Reply queued for Paratext\.\s+Paratext is offline/)).toBeTruthy();
  });

  it("says a note Paratext refused waits for the reviewer's retry (#358 h)", async () => {
    paratextThreadsFor.mockResolvedValue(data({
      links: [],
      pending: [{ messageId: "m3", op: "create_thread", threadId: "", status: "refused", attempts: 1,
        lastError: "The selected text occurs more than once in this verse.", sentAt: "", resultKey: "", createdAt: "" }],
    }));
    render(ParatextThreadPanel, props);
    expect(await screen.findByText(/Note\s+refused by Paratext; it waits for Retry handoff\.\s+The selected text occurs more than once/)).toBeTruthy();
    expect(screen.queryByText(/queued for Paratext/)).toBeNull();
  });

  it("links an existing thread on the verse that is not linked yet", async () => {
    paratextThreadsFor.mockResolvedValue(data());
    paratextNotesForVerse.mockResolvedValue({ state: "ready", book: "TIT", chapter: "1", verse: "1",
      threads: [thread(), thread({ id: "T9", excerpt: "Is this the right word?", lastUser: "Translator" })] });
    paratextLinkThread.mockResolvedValue({ link: { threadId: "T9" } });
    render(ParatextThreadPanel, props);
    await fireEvent.click(await screen.findByRole("button", { name: "Link existing thread" }));
    expect(await screen.findByText(/Is this the right word\?/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Link" })).toHaveLength(1);
    await fireEvent.click(screen.getByRole("button", { name: "Link" }));
    expect(paratextLinkThread).toHaveBeenCalledWith("T9", "issue_resolution", "r1");
    expect(await screen.findByText("Linked to the Paratext thread.")).toBeTruthy();
  });
});
