import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

// Three books make a collection, so the dashboard mounts the Collection QA
// bar and the Paratext chip; both read the engine, which is not here.
vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    collectionQaStatus: vi.fn(async () => ({ jobId: "", state: "idle", paused: false, collectionPath: "", checks: [],
      totalBooks: 3, completedBooks: 0, percent: 0, currentBook: null, books: [], finalStage: null,
      elapsedSeconds: 0, estimatedRemainingSeconds: null, error: null, createdAt: null, finishedAt: null })),
    paratextLinkStatus: vi.fn(async () => ({ state: "notParatext" })),
  },
}));

import ProjectDashboard from "../ProjectDashboard.svelte";
import type { Assignment, BookProgressEntry } from "../../types/finding";

function assignment(chapter: string, assigneeId: string, assigneeName: string): Assignment {
  return { chapter, assigneeId, assigneeName, assignedBy: "u-1", assignedAt: "2026-10-14T09:00:00Z" };
}

function book(bookId: string, assignments: Assignment[] = []): BookProgressEntry {
  const names: Record<string, string> = { gen: "Genesis", exo: "Exodus", lev: "Leviticus" };
  return { path: `/p/${bookId}`, bookId, bookName: names[bookId], lazy: false, missing: false, progress: null, assignments };
}

const books = [
  book("gen", [assignment("", "u-2", "Rina"), assignment("3", "u-1", "Revant")]),
  book("exo", [assignment("", "u-2", "Rina")]),
  book("lev"),
];

function mount(props: Record<string, unknown> = {}) {
  return render(ProjectDashboard, { props: {
    projectName: "NT", books, loading: false, error: "",
    onSelectBook: vi.fn(), onPreviewBook: vi.fn(), onRetry: vi.fn(), onLoadReport: vi.fn(),
    ...props,
  } });
}

describe("ProjectDashboard assignments (#240)", () => {
  it("shows who each book is assigned to and filters to my work", async () => {
    mount({ myUserId: "u-1" });
    expect(screen.getByText("book: Rina · ch 3: Revant")).toBeInTheDocument();
    expect(screen.getByText("book: Rina")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 of 3");

    await fireEvent.click(screen.getByLabelText("My work (1)"));
    expect(screen.getByRole("status")).toHaveTextContent("1 of 3");
    expect(screen.getByText("Genesis")).toBeInTheDocument();
    expect(screen.queryByText("Exodus")).toBeNull();
    expect(screen.queryByText("Leviticus")).toBeNull();
  });

  it("hides My work and Assign without a signed-in admin, and offers Assign to one", async () => {
    mount({ myUserId: "", canAssign: false });
    expect(screen.queryByLabelText(/My work/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Assign…" })).toBeNull();

    const onAssign = vi.fn();
    mount({ myUserId: "u-1", canAssign: true, onAssign });
    const buttons = screen.getAllByRole("button", { name: "Assign…" });
    expect(buttons).toHaveLength(3);
    await fireEvent.click(buttons[0]);
    expect(onAssign).toHaveBeenCalledWith("/p/gen");
  });
});
