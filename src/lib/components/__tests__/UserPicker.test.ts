import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { usersList, usersSetCurrent, usersCreate } = vi.hoisted(() => ({
  usersList: vi.fn(),
  usersSetCurrent: vi.fn(),
  usersCreate: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: { usersList, usersSetCurrent, usersCreate } }));

import UserPicker from "../UserPicker.svelte";
import type { WorkspaceUser } from "../../types/finding";

function user(overrides: Partial<WorkspaceUser> = {}): WorkspaceUser {
  return {
    userId: "u-1", displayName: "Revant", role: "project_admin", active: true,
    createdAt: "2026-10-14T00:00:00Z", updatedAt: "2026-10-14T00:00:00Z", current: false, ...overrides,
  };
}

describe("UserPicker (#237)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usersSetCurrent.mockResolvedValue({ currentUserId: "u-2" });
    usersCreate.mockImplementation(async (displayName: string, role: string) => user({ userId: "u-new", displayName, role: role as never }));
  });

  it("lists active users with their role and picks one", async () => {
    usersList.mockResolvedValue({ users: [user(), user({ userId: "u-2", displayName: "Rina", role: "reporter" }), user({ userId: "u-3", displayName: "Old", active: false })], currentUserId: "" });
    const onDone = vi.fn();
    render(UserPicker, { props: { onDone } });

    await screen.findByRole("heading", { name: "Pick your name" });
    expect(await screen.findByRole("button", { name: /Revant/ })).toHaveTextContent("project admin");
    expect(screen.getByRole("button", { name: /Rina/ })).toHaveTextContent("reporter");
    expect(screen.queryByRole("button", { name: /Old/ })).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: /Rina/ }));
    await waitFor(() => expect(usersSetCurrent).toHaveBeenCalledWith("u-2"));
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ userId: "u-2", current: true }));
  });

  it("chooses the only user silently when none is chosen yet", async () => {
    usersList.mockResolvedValue({ users: [user()], currentUserId: "" });
    const onDone = vi.fn();
    render(UserPicker, { props: { onDone } });
    await waitFor(() => expect(usersSetCurrent).toHaveBeenCalledWith("u-1"));
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ userId: "u-1" }));
  });

  it("creates a new name with a role and signs in as it", async () => {
    usersList.mockResolvedValue({ users: [user(), user({ userId: "u-2", displayName: "Rina" })], currentUserId: "" });
    const onDone = vi.fn();
    render(UserPicker, { props: { onDone } });
    await screen.findByRole("button", { name: /Revant/ });

    await fireEvent.click(screen.getByRole("button", { name: "New name" }));
    const input = screen.getByPlaceholderText("e.g. Rina");
    await fireEvent.input(input, { target: { value: "  Anju " } });
    await fireEvent.change(screen.getByRole("combobox"), { target: { value: "reporter" } });
    await fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(usersCreate).toHaveBeenCalledWith("Anju", "reporter"));
    await waitFor(() => expect(usersSetCurrent).toHaveBeenCalledWith("u-new"));
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ userId: "u-new", displayName: "Anju" }));
  });

  it("shows the engine's refusal and stays open", async () => {
    usersList.mockResolvedValue({ users: [user(), user({ userId: "u-2", displayName: "Rina" })], currentUserId: "" });
    usersSetCurrent.mockRejectedValue(new Error("Rina is deactivated."));
    const onDone = vi.fn();
    render(UserPicker, { props: { onDone } });
    await fireEvent.click(await screen.findByRole("button", { name: /Rina/ }));
    await screen.findByText("Rina is deactivated.");
    expect(onDone).not.toHaveBeenCalled();
  });
});
