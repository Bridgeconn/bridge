import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const {
  paratextNotesForVerse, paratextLinkStatus, paratextRefresh, paratextNotesForChapter,
  paratextCreateNote, paratextReplyThread, paratextResolveThread, paratextQueueRecord,
} = vi.hoisted(() => ({
  paratextNotesForVerse: vi.fn(),
  paratextLinkStatus: vi.fn(),
  paratextRefresh: vi.fn(),
  paratextNotesForChapter: vi.fn(),
  paratextCreateNote: vi.fn(),
  paratextReplyThread: vi.fn(),
  paratextResolveThread: vi.fn(),
  paratextQueueRecord: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    paratextNotesForVerse, paratextLinkStatus, paratextRefresh, paratextNotesForChapter,
    paratextCreateNote, paratextReplyThread, paratextResolveThread, paratextQueueRecord,
  },
}));

import { get } from "svelte/store";
import ParatextNotesPanel from "../ParatextNotesPanel.svelte";
import { currentChapter, project, selectedVerse } from "../../stores";
import { paratextNoteRequest, requestParatextNote, dropDraft, draftKey } from "../../paratextNotes";
import { sidePanels } from "../../editorPrefs";
import type { ParatextNoteThread, ParatextOutboxItem, ParatextProposal } from "../../types/paratext";

const PROJECT = { path: "C:/p/jos", bookId: "jos", bookName: "Joshua", targetLanguage: "Tamil", tcVersion: "",
                  chapters: ["3"], checkTypes: {} };

function thread(overrides: Partial<ParatextNoteThread> = {}): ParatextNoteThread {
  return {
    id: "8a14411f", kind: "note", status: "todo", resolved: false, verseRef: "JOS 3:4", verse: "4",
    users: ["Yesu Selva Benz"], firstDate: "2025-10-21T14:40:12+05:30", lastDate: "2025-10-21T14:40:12+05:30",
    lastUser: "Yesu Selva Benz", excerpt: "ஒரு கிலோமீட்டர்", selectedText: "3,000 அடிகள்", assignedUser: "",
    tags: [], hidden: false, commentCount: 1, contextBefore: "", contextAfter: "",
    proposals: { total: 0, outstanding: 0, unreadable: 0,
                 byRoute: { literal: 0, review: 0, structure: 0, noChange: 0, legacy: 0, unreadable: 0 } },
    proposalItems: [],
    comments: [{ user: "Yesu Selva Benz", date: "2025-10-21T14:40:12+05:30", contents: "ஒரு கிலோமீட்டர்",
                 status: "", type: "", assignedUser: null, replyToUser: "", language: "ta", tagsAdded: [], tagsRemoved: [] }],
    ...overrides,
  };
}

function verseAnswer(state: string, threads: ParatextNoteThread[] = [], pending: ParatextOutboxItem[] = []) {
  return { state, book: "JOS", chapter: "3", verse: "4", threads, pending };
}

function outboxItem(overrides: Partial<ParatextOutboxItem> = {}): ParatextOutboxItem {
  return {
    messageId: "bridge-abc", op: "create_thread", threadId: "", status: "queued", attempts: 1,
    lastError: "Paratext is offline", sentAt: "", resultKey: "", createdAt: "2026-11-02T08:00:00Z",
    kind: "note", localId: "bridge-abc", reference: "JOS 3:4", selectedText: "",
    text: "Please look at the measure.\n\n[Bridge ref bridge-abc]", ...overrides,
  };
}

function proposal(overrides: Partial<ParatextProposal> = {}): ParatextProposal {
  return {
    proposalId: "p1", commentIndex: 0, block: 0, route: "literal", operation: "replace", region: "body",
    pass: "R2", topic: "Sandhi", category: "Sandhi / word-joining", categoryKnown: true,
    original: "ஒரு கிலோ", suggested: "ஒருகிலோ", reason: "The words join.", location: "", reference: "",
    severity: "low", confidence: "0.93", reviewerDecision: false, anchorWarning: false, historical: false,
    outstanding: true, alternatives: [], structural: null, diagnostics: [], author: "QA", date: "2026-10-20",
    ...overrides,
  };
}

describe("ParatextNotesPanel (#357)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(PROJECT);
    currentChapter.set("3");
    selectedVerse.set("4");
    paratextNotesForChapter.mockResolvedValue({ state: "ready", book: "JOS", chapter: "3", verses: {}, counts: {} });
  });
  afterEach(() => {
    vi.useRealTimers();
    project.set(null);
    selectedVerse.set(null);
  });

  it("asks for a verse when none is selected", async () => {
    selectedVerse.set(null);
    render(ParatextNotesPanel);
    expect(await screen.findByText("Select a verse to see its Paratext notes.")).toBeTruthy();
    expect(paratextNotesForVerse).not.toHaveBeenCalled();
  });

  it("shows the verse's threads with their comments in order", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready", [
      thread(),
      thread({
        id: "c1", kind: "conflict", resolved: true, status: "done", assignedUser: "Uma Johnson",
        tags: [{ id: "3", name: "Accuracy" }], selectedText: "",
        comments: [
          { user: "A", date: "2026-01-01T00:00:00Z", contents: "first", status: "todo", type: "conflict",
            assignedUser: null, replyToUser: "", language: "", tagsAdded: [], tagsRemoved: [] },
          { user: "B", date: "2026-01-02T00:00:00Z", contents: "second", status: "done", type: "",
            assignedUser: null, replyToUser: "A", language: "", tagsAdded: [], tagsRemoved: [] },
        ],
      }),
    ]));
    render(ParatextNotesPanel);

    const first = await screen.findByText("3,000 அடிகள்");
    const article = first.closest("article")!;
    expect(within(article as HTMLElement).getByText("ஒரு கிலோமீட்டர்")).toBeTruthy();
    expect(within(article as HTMLElement).getByText("Open")).toBeTruthy();
    expect(paratextNotesForVerse).toHaveBeenCalledWith("3", "4");

    const conflict = document.querySelector('[data-thread-id="c1"]') as HTMLElement;
    expect(conflict).toHaveTextContent("Conflict");
    expect(conflict).toHaveTextContent("Resolved");
    expect(conflict).toHaveTextContent("Assigned to Uma Johnson");
    expect(conflict).toHaveTextContent("Accuracy");
    const bodies = [...conflict.querySelectorAll(".pt-body")].map((node) => node.textContent);
    expect(bodies).toEqual(["first", "second"]);
  });

  it("says so when the verse has no notes", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready"));
    render(ParatextNotesPanel);
    expect(await screen.findByText("No Paratext notes on this verse.")).toBeTruthy();
  });

  it("explains a book that is not from Paratext, and a missing folder", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("unavailable"));
    paratextLinkStatus.mockResolvedValueOnce({ state: "notParatext" });
    const { unmount } = render(ParatextNotesPanel);
    expect(await screen.findByText(/not imported from a Paratext project/)).toBeTruthy();
    unmount();

    paratextLinkStatus.mockResolvedValueOnce({ state: "folderMissing" });
    render(ParatextNotesPanel);
    expect(await screen.findByText(/Relink it on Project Home/)).toBeTruthy();
  });

  it("waits while the index builds, then shows the notes", async () => {
    vi.useFakeTimers();
    paratextNotesForVerse
      .mockResolvedValueOnce(verseAnswer("building"))
      .mockResolvedValueOnce(verseAnswer("ready", [thread()]));
    render(ParatextNotesPanel);
    await vi.advanceTimersByTimeAsync(10);
    expect(screen.getByText("Reading the Paratext notes…")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(1600);
    expect(screen.getByText("3,000 அடிகள்")).toBeTruthy();
  });

  it("Refresh re-reads Paratext and the verse", async () => {
    paratextNotesForVerse
      .mockResolvedValueOnce(verseAnswer("ready", [thread()]))
      .mockResolvedValueOnce(verseAnswer("ready", [thread({ comments: [{ ...thread().comments[0], contents: "edited in Paratext" }] })]));
    paratextRefresh.mockResolvedValue({ state: "linked" });
    render(ParatextNotesPanel);
    await screen.findByText("ஒரு கிலோமீட்டர்", { selector: ".pt-body" });

    await fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByText("edited in Paratext")).toBeTruthy());
    expect(paratextRefresh).toHaveBeenCalledTimes(1);
    expect(paratextNotesForChapter).toHaveBeenCalledWith("3");
  });
});

describe("ParatextNotesPanel writes (#426) and QA proposals (#427)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(PROJECT);
    currentChapter.set("3");
    selectedVerse.set("4");
    paratextNoteRequest.set(null);
    paratextNotesForChapter.mockResolvedValue({ state: "ready", book: "JOS", chapter: "3", verses: {}, counts: {} });
  });
  afterEach(() => {
    vi.useRealTimers();
    project.set(null);
    selectedVerse.set(null);
  });

  it("writes a new note on the verse through the engine and reports a sent note as pending, not as a thread", async () => {
    paratextNotesForVerse
      .mockResolvedValueOnce(verseAnswer("ready"))
      .mockResolvedValueOnce(verseAnswer("ready", [], [outboxItem({ status: "sent", lastError: "" })]));
    paratextCreateNote.mockResolvedValue({ item: outboxItem({ status: "sent", lastError: "" }) });
    render(ParatextNotesPanel);
    await screen.findByText("No Paratext notes on this verse.");

    await fireEvent.click(await screen.findByRole("button", { name: "New note…" }));
    const box = screen.getByPlaceholderText("Your note, as the Paratext user on this PC") as HTMLTextAreaElement;
    await fireEvent.input(box, { target: { value: "Please look at the measure." } });
    await fireEvent.input(screen.getByLabelText(/Attach to text/), { target: { value: "3,000 அடிகள்" } });
    await fireEvent.click(screen.getByRole("button", { name: "Send to Paratext" }));

    await waitFor(() => expect(paratextCreateNote).toHaveBeenCalledWith("3", "4", "Please look at the measure.", "3,000 அடிகள்"));
    expect(await screen.findByText(/Note sent to Paratext/)).toBeTruthy();
    const pending = document.querySelector('[data-message-id="bridge-abc"]') as HTMLElement;
    expect(pending).toHaveTextContent("Note sent. It shows here once Bridge has read Paratext's notes file again.");
    expect(pending).toHaveTextContent("Please look at the measure.");
    expect(pending).not.toHaveTextContent("[Bridge ref");
    expect(document.querySelector("article.pt-thread")).toBeNull();
    expect(screen.queryByText("No Paratext notes on this verse.")).toBeNull();
  });

  it("keeps a queued note visible with its reason and an engine refusal as the notice", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready", [], [outboxItem()]));
    render(ParatextNotesPanel);
    expect(await screen.findByText(/Note queued for Paratext\. Paratext is offline/)).toBeTruthy();

    paratextCreateNote.mockRejectedValue(new Error("The selected target text is not present in the current verse."));
    await fireEvent.click(screen.getByRole("button", { name: "New note…" }));
    await fireEvent.input(screen.getByPlaceholderText("Your note, as the Paratext user on this PC"), { target: { value: "x" } });
    await fireEvent.click(screen.getByRole("button", { name: "Send to Paratext" }));
    expect(await screen.findByText("The selected target text is not present in the current verse.")).toBeTruthy();
    // The draft is still there to fix.
    expect((screen.getByPlaceholderText("Your note, as the Paratext user on this PC") as HTMLTextAreaElement).value).toBe("x");
  });

  it("replies to and resolves any thread on the verse, with no Bridge record behind it", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready", [thread()]));
    paratextReplyThread.mockResolvedValue({ item: outboxItem({ op: "add_comment", status: "sent", lastError: "" }) });
    paratextResolveThread.mockResolvedValue({ item: outboxItem({ op: "resolve", status: "queued" }) });
    render(ParatextNotesPanel);
    await screen.findByText("ஒரு கிலோமீட்டர்", { selector: ".pt-body" });

    await fireEvent.click(screen.getByRole("button", { name: "Reply" }));
    await fireEvent.input(screen.getByPlaceholderText("Your reply, as the Paratext user on this PC"), { target: { value: "Agreed." } });
    await fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(paratextReplyThread).toHaveBeenCalledWith("8a14411f", "Agreed.", "note", "8a14411f"));
    expect(await screen.findByText("Reply sent to Paratext.")).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Resolve in Paratext" }));
    await waitFor(() => expect(paratextResolveThread).toHaveBeenCalledWith("8a14411f", "note", "8a14411f"));
    expect(await screen.findByText(/Queued for Paratext\. Paratext is offline/)).toBeTruthy();
  });

  it("opens the composer on the selection when the verse menu asks for a note, and keeps the draft across verses", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready"));
    sidePanels.update((all) => ({ ...all, paratext: { ...all.paratext, open: false } }));
    render(ParatextNotesPanel);
    await screen.findByText("No Paratext notes on this verse.");

    requestParatextNote("3", "4", "3,000 அடிகள்");
    const target = await screen.findByLabelText(/Attach to text/) as HTMLInputElement;
    expect(target.value).toBe("3,000 அடிகள்");
    expect(get(paratextNoteRequest)).toBeNull();
    let opened = false;
    sidePanels.subscribe((all) => { opened = all.paratext.open; })();
    expect(opened).toBe(true);
    await fireEvent.input(screen.getByPlaceholderText("Your note, as the Paratext user on this PC"), { target: { value: "draft words" } });

    selectedVerse.set("5");
    await waitFor(() => expect(screen.queryByPlaceholderText("Your note, as the Paratext user on this PC")).toBeNull());
    selectedVerse.set("4");
    const back = await screen.findByPlaceholderText("Your note, as the Paratext user on this PC") as HTMLTextAreaElement;
    expect(back.value).toBe("draft words");
    expect(paratextCreateNote).not.toHaveBeenCalled();
  });

  it("keeps a composer draft across closing and reopening Bridge (localStorage), and drops it once sent (#426)", async () => {
    dropDraft(draftKey("C:/p/jos", "3", "4"));     // the earlier test's draft, now persisted too
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready"));
    paratextCreateNote.mockResolvedValue({ item: { messageId: "m1", status: "sent", lastError: "" } });
    const first = render(ParatextNotesPanel);
    await screen.findByText("No Paratext notes on this verse.");
    await fireEvent.click(await screen.findByRole("button", { name: "New note…" }));
    await fireEvent.input(screen.getByPlaceholderText("Your note, as the Paratext user on this PC"), { target: { value: "kept words" } });
    selectedVerse.set("5");
    await waitFor(() => expect(screen.queryByPlaceholderText("Your note, as the Paratext user on this PC")).toBeNull());
    first.unmount();
    expect(JSON.parse(localStorage.getItem("bridge.paratextNoteDrafts.v1") ?? "{}")["C:/p/jos|3:4"]).toEqual({ text: "kept words", selectedText: "" });

    selectedVerse.set("4");
    render(ParatextNotesPanel);
    const back = await screen.findByPlaceholderText("Your note, as the Paratext user on this PC") as HTMLTextAreaElement;
    expect(back.value).toBe("kept words");
    await fireEvent.click(screen.getByRole("button", { name: "Send to Paratext" }));
    await waitFor(() => expect(paratextCreateNote).toHaveBeenCalledWith("3", "4", "kept words", ""));
    await waitFor(() => expect(JSON.parse(localStorage.getItem("bridge.paratextNoteDrafts.v1") ?? "{}")["C:/p/jos|3:4"]).toBeUndefined());
  });

  it("sends a note for a finding through queueRecord with the card's lines, and shows a linked thread's closure (#433)", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready", [thread({
      links: [{ kind: "finding", localId: "f1", closure: { status: "resolved in Paratext", origin: "paratext",
        actor: "Reviewer Uma", resolvedAt: "2026-10-27T09:00:00+05:30", seenAt: "2026-10-27T09:05:00+05:30" } }],
    })]));
    paratextQueueRecord.mockResolvedValue({ item: outboxItem({ status: "sent", lastError: "" }), state: "ready", links: [], pending: [] });
    render(ParatextNotesPanel);
    expect(await screen.findByText("finding · resolved in Paratext")).toBeTruthy();

    requestParatextNote("3", "4", "3,000 அடிகள்", {
      kind: "finding", localId: "f1", title: "names.spelling_similarity · greekroom",
      lines: ["Bridge finding · names.spelling_similarity (greekroom)", "Text: 3,000 அடிகள்"],
    });
    const record = await screen.findByTestId("note-record");
    expect(record).toHaveTextContent("Linked to finding: names.spelling_similarity · greekroom");
    expect(screen.getByText("Text: 3,000 அடிகள்")).toBeTruthy();
    // The reviewer's own words are optional for a record: Send is enabled with an empty box.
    const send = screen.getByRole("button", { name: "Send to Paratext" }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    await fireEvent.input(screen.getByPlaceholderText("Your note, as the Paratext user on this PC"), { target: { value: "Please look." } });
    await fireEvent.click(send);
    await waitFor(() => expect(paratextQueueRecord).toHaveBeenCalledWith("finding", "f1", "3", "4", "Please look.",
      ["Bridge finding · names.spelling_similarity (greekroom)", "Text: 3,000 அடிகள்"], "3,000 அடிகள்"));
    expect(paratextCreateNote).not.toHaveBeenCalled();
    expect(await screen.findByText(/Note sent to Paratext/)).toBeTruthy();
  });

  it("shows a thread's QA proposals read-only, with what the parser could say about each", async () => {
    paratextNotesForVerse.mockResolvedValue(verseAnswer("ready", [thread({
      proposals: { total: 3, outstanding: 2, unreadable: 0,
                   byRoute: { literal: 1, review: 1, structure: 0, noChange: 0, legacy: 1, unreadable: 0 } },
      proposalItems: [
        proposal(),
        proposal({ proposalId: "p2", route: "review", operation: "alternatives", alternatives: ["அ", "ஆ"],
                   suggested: "அ / ஆ", reviewerDecision: true, category: "Reviewer decision",
                   region: "footnote", diagnostics: [] }),
        proposal({ proposalId: "p3", route: "legacy", operation: "none", historical: true, category: "Unstructured / discussion",
                   original: "", suggested: "ஒருகிலோ", reason: "", outstanding: false,
                   diagnostics: ["Older note label \"Changed to\"; read the discussion before acting. A \"Changed to\" reports an edit already made."] }),
      ],
    })]));
    render(ParatextNotesPanel);
    await screen.findByText("ஒரு கிலோமீட்டர்", { selector: ".pt-body" });

    expect(screen.getByText("2 QA proposals")).toBeTruthy();
    const literal = document.querySelector('[data-proposal-id="p1"]') as HTMLElement;
    expect(literal).toHaveTextContent("Literal correction · review before use");
    expect(literal).toHaveTextContent("Sandhi / word-joining");
    expect(within(literal).getByText("ஒரு கிலோ")).toBeTruthy();
    expect(within(literal).getByText("ஒருகிலோ")).toBeTruthy();
    expect(literal).toHaveTextContent("The words join.");
    expect(literal).toHaveTextContent("Confidence 0.93");
    const alternatives = document.querySelector('[data-proposal-id="p2"]') as HTMLElement;
    expect(alternatives).toHaveTextContent("Needs a reviewer's decision");
    expect(alternatives).toHaveTextContent("alternatives");
    expect(alternatives).toHaveTextContent("in the footnote");
    expect([...alternatives.querySelectorAll(".pt-alts li")].map((li) => li.textContent)).toEqual(["அ", "ஆ"]);
    expect(alternatives).toHaveTextContent("Reviewer decision needed");
    const legacy = document.querySelector('[data-proposal-id="p3"]') as HTMLElement;
    expect(legacy).toHaveTextContent("Older note label");
    expect(legacy).toHaveTextContent("already made");
    // Nothing applies: no Apply control anywhere.
    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
  });
});
