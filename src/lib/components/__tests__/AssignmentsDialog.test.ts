import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import AssignmentsDialog from "../AssignmentsDialog.svelte";
import type { Assignment, WorkspaceUser } from "../../types/finding";

function user(userId: string, displayName: string, active = true): WorkspaceUser {
  return { userId, displayName, role: "editor", active, createdAt: "", updatedAt: "", current: false };
}

const users = [user("u-1", "Revant"), user("u-2", "Rina"), user("u-9", "Old", false)];
const assignments: Assignment[] = [
  { chapter: "", assigneeId: "u-1", assigneeName: "Revant", assignedBy: "u-1", assignedAt: "2026-10-14T09:00:00Z" },
  { chapter: "2", assigneeId: "u-2", assigneeName: "Rina", assignedBy: "u-1", assignedAt: "2026-10-14T09:30:00Z" },
];

describe("AssignmentsDialog (#240)", () => {
  it("shows the whole book and each chapter with its assignee, active users only", async () => {
    render(AssignmentsDialog, { props: {
      bookName: "Genesis", chapters: ["1", "2", "3"], users, assignments,
      onSet: vi.fn(), onClear: vi.fn(), onClose: vi.fn(),
    } });
    expect(screen.getByRole("heading", { name: "Assign Genesis" })).toBeInTheDocument();
    const book = screen.getByLabelText("Assignee for Whole book") as HTMLSelectElement;
    expect(book.value).toBe("u-1");
    expect((screen.getByLabelText("Assignee for Chapter 2") as HTMLSelectElement).value).toBe("u-2");
    expect((screen.getByLabelText("Assignee for Chapter 3") as HTMLSelectElement).value).toBe("");
    expect(Array.from(book.options).map((o) => o.textContent)).toEqual(["— nobody —", "Revant", "Rina"]);
  });

  it("sets and clears through the callbacks", async () => {
    const onSet = vi.fn();
    const onClear = vi.fn();
    render(AssignmentsDialog, { props: {
      bookName: "Genesis", chapters: ["1", "2"], users, assignments, onSet, onClear, onClose: vi.fn(),
    } });
    await fireEvent.change(screen.getByLabelText("Assignee for Chapter 1"), { target: { value: "u-2" } });
    expect(onSet).toHaveBeenCalledWith("1", "u-2");
    await fireEvent.change(screen.getByLabelText("Assignee for Chapter 2"), { target: { value: "" } });
    expect(onClear).toHaveBeenCalledWith("2");
  });

  it("says when there is nobody to assign to, and shows an error", async () => {
    const onClose = vi.fn();
    render(AssignmentsDialog, { props: {
      bookName: "Ruth", chapters: ["1"], users: [user("u-9", "Old", false)], assignments: [],
      error: "Only a project admin can assign.", onSet: vi.fn(), onClear: vi.fn(), onClose,
    } });
    expect(screen.getByText(/No active users/)).toBeInTheDocument();
    expect(screen.getByText("Only a project admin can assign.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Close assignments" }));
    expect(onClose).toHaveBeenCalled();
  });
});
