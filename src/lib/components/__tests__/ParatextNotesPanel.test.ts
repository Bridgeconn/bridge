import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const { paratextNotesForVerse, paratextLinkStatus, paratextRefresh, paratextNotesForChapter } = vi.hoisted(() => ({
  paratextNotesForVerse: vi.fn(),
  paratextLinkStatus: vi.fn(),
  paratextRefresh: vi.fn(),
  paratextNotesForChapter: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: { paratextNotesForVerse, paratextLinkStatus, paratextRefresh, paratextNotesForChapter },
}));

import ParatextNotesPanel from "../ParatextNotesPanel.svelte";
import { currentChapter, project, selectedVerse } from "../../stores";
import type { ParatextNoteThread } from "../../types/paratext";

const PROJECT = { path: "C:/p/jos", bookId: "jos", bookName: "Joshua", targetLanguage: "Tamil", tcVersion: "",
                  chapters: ["3"], checkTypes: {} };

function thread(overrides: Partial<ParatextNoteThread> = {}): ParatextNoteThread {
  return {
    id: "8a14411f", kind: "note", status: "todo", resolved: false, verseRef: "JOS 3:4", verse: "4",
    users: ["Yesu Selva Benz"], firstDate: "2025-10-21T14:40:12+05:30", lastDate: "2025-10-21T14:40:12+05:30",
    lastUser: "Yesu Selva Benz", excerpt: "ஒரு கிலோமீட்டர்", selectedText: "3,000 அடிகள்", assignedUser: "",
    tags: [], hidden: false, commentCount: 1, contextBefore: "", contextAfter: "",
    comments: [{ user: "Yesu Selva Benz", date: "2025-10-21T14:40:12+05:30", contents: "ஒரு கிலோமீட்டர்",
                 status: "", type: "", assignedUser: null, replyToUser: "", language: "ta", tagsAdded: [], tagsRemoved: [] }],
    ...overrides,
  };
}

function verseAnswer(state: string, threads: ParatextNoteThread[] = []) {
  return { state, book: "JOS", chapter: "3", verse: "4", threads };
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
