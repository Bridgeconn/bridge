import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

import AssignmentsDialog from "../AssignmentsDialog.svelte";
import type { Assignment, WorkspaceUser } from "../../types/finding";

function user(userId: string, displayName: string, active = true): WorkspaceUser {
  return { userId, displayName, role: "editor", active, createdAt: "", updatedAt: "", current: false };
}

const users = [user("u-1", "Revant"), user("u-2", "Rina Issac"), user("u-9", "Old", false)];
const assignments: Assignment[] = [
  { chapter: "", assigneeId: "u-1", assigneeName: "Revant", assignedBy: "u-1", assignedAt: "2026-10-14T09:00:00Z" },
  { chapter: "2", assigneeId: "u-2", assigneeName: "Rina Issac", assignedBy: "u-1", assignedAt: "2026-10-14T09:30:00Z" },
];

const chapters = (n: number) => Array.from({ length: n }, (_, i) => String(i + 1));

function mount(overrides: Record<string, unknown> = {}) {
  const onSet = vi.fn().mockResolvedValue(true);
  const onClear = vi.fn().mockResolvedValue(true);
  const onApplied = vi.fn();
  const onClose = vi.fn();
  const utils = render(AssignmentsDialog, { props: {
    bookName: "Genesis", chapters: chapters(5), users, assignments, onSet, onClear, onApplied, onClose, ...overrides,
  } });
  return { ...utils, onSet, onClear, onApplied, onClose };
}

const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
async function pickPerson(name: string) {
  const search = screen.getByRole("combobox", { name: "Person" });
  await fireEvent.focus(search);
  await fireEvent.mouseDown(screen.getByRole("option", { name }));
}

describe("AssignmentsDialog (#378: person once, chapters, one Apply)", () => {
  it("shows the whole book and each chapter with who holds it now, and lists active users plus Nobody", async () => {
    mount();
    expect(screen.getByRole("heading", { name: "Assign Genesis" })).toBeInTheDocument();
    expect(box("Whole book").closest(".cell")?.textContent).toContain("Revant");
    expect(box("Chapter 2").closest(".cell")?.textContent).toContain("RI");
    expect(box("Chapter 2").closest(".cell")?.getAttribute("title")).toBe("Chapter 2: Rina Issac");
    expect(box("Chapter 3").closest(".cell")?.getAttribute("title")).toBe("Chapter 3: nobody");

    await fireEvent.focus(screen.getByRole("combobox", { name: "Person" }));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Nobody (clear)", "Revant", "Rina Issac"]);
    await fireEvent.input(screen.getByRole("combobox", { name: "Person" }), { target: { value: "rin" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Rina Issac"]);
  });

  it("selects by tick, Shift-click range, from–to range, Select all and Clear selection", async () => {
    mount();
    await fireEvent.click(box("Chapter 1"));
    expect(box("Chapter 1").checked).toBe(true);
    // Shift-click from the last click to here ticks everything between.
    await fireEvent.click(box("Chapter 4"), { shiftKey: true });
    expect(chapters(5).map((c) => box(`Chapter ${c}`).checked)).toEqual([true, true, true, true, false]);
    await fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(chapters(5).map((c) => box(`Chapter ${c}`).checked)).toEqual([false, false, false, false, false]);

    await fireEvent.input(screen.getByRole("textbox", { name: "From chapter" }), { target: { value: "2" } });
    await fireEvent.input(screen.getByRole("textbox", { name: "To chapter" }), { target: { value: "3" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add range" }));
    expect(chapters(5).map((c) => box(`Chapter ${c}`).checked)).toEqual([false, true, true, false, false]);

    await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(chapters(5).map((c) => box(`Chapter ${c}`).checked)).toEqual([true, true, true, true, true]);
    expect(box("Whole book").checked).toBe(false);
  });

  it("sends nothing before Apply, then one call per changed chapter in order, skipping chapters the person already holds", async () => {
    const { onSet, onClear, onApplied } = mount();
    await pickPerson("Rina Issac");
    expect(screen.getByTestId("picked-person")).toHaveTextContent("Rina Issac");
    await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(onSet).not.toHaveBeenCalled();
    expect(onClear).not.toHaveBeenCalled();
    // Chapter 2 is Rina's already: it is not a change and is not marked as one.
    expect(screen.getByText("Rina Issac → 4 changes")).toBeInTheDocument();
    expect(box("Chapter 2").closest(".cell")?.classList.contains("changing")).toBe(false);
    expect(box("Chapter 3").closest(".cell")?.classList.contains("changing")).toBe(true);

    await fireEvent.click(screen.getByRole("button", { name: "Apply (4)" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
    expect(onSet.mock.calls).toEqual([["1", "u-2"], ["3", "u-2"], ["4", "u-2"], ["5", "u-2"]]);
    expect(onClear).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Applied 4 changes.");
    // The ticks are cleared after a successful Apply.
    expect(chapters(5).map((c) => box(`Chapter ${c}`).checked)).toEqual([false, false, false, false, false]);
  });

  it("Nobody clears the ticked chapters and the whole book through onClear, and stops when a save fails", async () => {
    const onClear = vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const { onSet, onApplied } = mount({ onClear });
    await pickPerson("Nobody (clear)");
    await fireEvent.click(box("Whole book"));
    await fireEvent.click(box("Chapter 2"));
    await fireEvent.click(box("Chapter 3")); // nobody's already: no change
    expect(screen.getByText("Nobody (clear) → 2 changes")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Apply (2)" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Stopped after 1 of 2: Chapter 2 was not saved."));
    expect(onClear.mock.calls).toEqual([[""], ["2"]]);
    expect(onSet).not.toHaveBeenCalled();
    expect(onApplied).toHaveBeenCalledOnce();
  });

  it("keeps Apply off until a person is picked and a change is ticked", async () => {
    mount();
    const apply = () => screen.getByRole("button", { name: /^Apply/ }) as HTMLButtonElement;
    expect(apply().disabled).toBe(true);
    expect(screen.getByText("Pick a person first.")).toBeInTheDocument();
    await pickPerson("Revant");
    expect(apply().disabled).toBe(true);
    expect(screen.getByText("Tick the chapters to give to Revant.")).toBeInTheDocument();
    await fireEvent.click(box("Whole book")); // Revant holds the book already
    expect(apply().disabled).toBe(true);
    expect(screen.getByText("Revant already holds the ticked chapter.")).toBeInTheDocument();
    await fireEvent.click(box("Chapter 2"));
    expect(apply().disabled).toBe(false);
  });

  it("picks from the keyboard: arrows move, Enter chooses", async () => {
    mount();
    const search = screen.getByRole("combobox", { name: "Person" });
    await fireEvent.keyDown(search, { key: "ArrowDown" });
    await fireEvent.keyDown(search, { key: "ArrowDown" });
    await fireEvent.keyDown(search, { key: "Enter" });
    expect(screen.getByTestId("picked-person")).toHaveTextContent("Rina Issac");
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

describe("AssignmentsDialog Escape (#321, #378)", () => {
  it("closes on Escape with nothing written, as × does, and returns focus to the invoker", async () => {
    const opener = document.createElement("button");
    opener.textContent = "Assign…";
    document.body.appendChild(opener);
    opener.focus();
    const { onSet, onClear, onClose, unmount } = mount();
    await pickPerson("Revant");
    await fireEvent.click(box("Chapter 3"));
    await fireEvent.keyDown(window, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(box("Chapter 1"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(onSet).not.toHaveBeenCalled();
    expect(onClear).not.toHaveBeenCalled();
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("a first Escape only closes an open people list", async () => {
    const { onClose } = mount();
    const search = screen.getByRole("combobox", { name: "Person" });
    await fireEvent.focus(search);
    expect(screen.getByRole("listbox", { name: "People" })).toBeInTheDocument();
    await fireEvent.keyDown(search, { key: "Escape" });
    expect(screen.queryByRole("listbox", { name: "People" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(search, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
