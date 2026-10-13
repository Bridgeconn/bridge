import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { usersList, usersCreate, usersRename, usersDeactivate, usersSetRole } = vi.hoisted(() => ({
  usersList: vi.fn(),
  usersCreate: vi.fn(),
  usersRename: vi.fn(),
  usersDeactivate: vi.fn(),
  usersSetRole: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: { usersList, usersCreate, usersRename, usersDeactivate, usersSetRole } }));

import UsersPane from "../UsersPane.svelte";
import type { WorkspaceUser } from "../../types/finding";

function user(overrides: Partial<WorkspaceUser> = {}): WorkspaceUser {
  return {
    userId: "u-1", displayName: "Revant", role: "project_admin", active: true,
    createdAt: "2026-10-14T00:00:00Z", updatedAt: "2026-10-14T00:00:00Z", current: true, ...overrides,
  };
}

const two = [user(), user({ userId: "u-2", displayName: "Rina", role: "reporter", current: false })];

describe("UsersPane (#237)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usersList.mockResolvedValue({ users: two, currentUserId: "u-1" });
    usersCreate.mockResolvedValue(user({ userId: "u-3", displayName: "Anju", role: "editor" }));
    usersRename.mockResolvedValue({ userId: "u-2", displayName: "Rina S" });
    usersDeactivate.mockResolvedValue({ userId: "u-2", active: false });
    usersSetRole.mockResolvedValue({ userId: "u-2", role: "editor" });
  });

  it("a project admin adds, renames, re-roles and deactivates; never themselves", async () => {
    render(UsersPane, { props: { myRole: "project_admin" } });
    await screen.findByText("Rina");
    expect(screen.getByText("(you)")).toBeInTheDocument();

    await fireEvent.input(screen.getByLabelText("Display name"), { target: { value: "Anju" } });
    await fireEvent.change(screen.getByLabelText("Role for the new user"), { target: { value: "editor" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(usersCreate).toHaveBeenCalledWith("Anju", "editor"));
    await screen.findByText("Anju added.");

    await fireEvent.click(screen.getAllByRole("button", { name: "Rename" })[1]);
    const input = screen.getByLabelText("New name for Rina") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "Rina S" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(usersRename).toHaveBeenCalledWith("u-2", "Rina S"));
    await screen.findByText(/history is unchanged/);

    await fireEvent.change(screen.getByLabelText("Role for Rina"), { target: { value: "editor" } });
    await waitFor(() => expect(usersSetRole).toHaveBeenCalledWith("u-2", "editor"));

    const deactivateButtons = screen.getAllByRole("button", { name: "Deactivate" });
    expect(deactivateButtons[0]).toBeDisabled(); // themselves
    await fireEvent.click(deactivateButtons[1]);
    await waitFor(() => expect(usersDeactivate).toHaveBeenCalledWith("u-2"));
    await screen.findByText(/what they wrote stays under their name/);
  });

  it("an editor sees the list read-only", async () => {
    render(UsersPane, { props: { myRole: "editor" } });
    await screen.findByText("Rina");
    expect(screen.getByText("Only a project admin can change this list.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
    expect(screen.queryByLabelText("Role for Rina")).toBeNull();
    expect(screen.getByText("reporter")).toBeInTheDocument();
  });

  it("hides deactivated users behind a filter", async () => {
    usersList.mockResolvedValue({ users: [...two, user({ userId: "u-9", displayName: "Old", active: false, current: false })], currentUserId: "u-1" });
    render(UsersPane, { props: { myRole: "project_admin" } });
    await screen.findByText("Rina");
    expect(screen.queryByText("Old")).toBeNull();
    await fireEvent.click(screen.getByLabelText("Show deactivated (1)"));
    expect(screen.getByText("Old")).toBeInTheDocument();
    expect(screen.getByText("deactivated")).toBeInTheDocument();
  });

  it("shows the engine's refusal", async () => {
    usersDeactivate.mockRejectedValue(new Error("The last project admin cannot be deactivated."));
    render(UsersPane, { props: { myRole: "project_admin" } });
    await screen.findByText("Rina");
    await fireEvent.click(screen.getAllByRole("button", { name: "Deactivate" })[1]);
    await screen.findByText("The last project admin cannot be deactivated.");
  });
});
