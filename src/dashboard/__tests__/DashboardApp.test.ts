import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const api = vi.hoisted(() => ({
  join: vi.fn(), me: vi.fn(), projects: vi.fn(), users: vi.fn(), assign: vi.fn(), joinCode: vi.fn(),
  signedIn: vi.fn(), signOut: vi.fn(),
}));

vi.mock("../hubApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../hubApi")>();
  return {
    ...actual,
    hubApi: { join: api.join, me: api.me, projects: api.projects, users: api.users, assign: api.assign, joinCode: api.joinCode },
    signedIn: api.signedIn,
    signOut: api.signOut,
  };
});

import DashboardApp from "../DashboardApp.svelte";
import { projectsCsv, type HubProject } from "../hubApi";

function project(overrides: Partial<HubProject> = {}): HubProject {
  return {
    hubProjectId: "p-tit", bookId: "tit", bookName: "Titus", projectName: "Pastorals", chapters: ["1", "2"],
    totals: { chapterCount: 2, checkedChapterCount: 1, verseCount: 40, reviewedVerseCount: 10,
      alignedVerseCount: 10, alignedKnownVerseCount: 20 },
    progressPostedAt: "2026-10-14T09:00:00Z", lastActivityAt: "2026-10-14T09:00:00Z", events: 3,
    assignments: [{ chapter: "2", assigneeId: "u-1", assigneeName: "Revant", assignedBy: "u-9", assignedAt: "" }],
    ...overrides,
  };
}

describe("DashboardApp (#81)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.projects.mockResolvedValue({ projects: [project()] });
    api.users.mockResolvedValue({ users: [
      { userId: "u-1", displayName: "Revant", role: "project_admin", lastSeenAt: null, devices: 1 },
      { userId: "u-2", displayName: "Rina", role: "editor", lastSeenAt: null, devices: 1 },
    ] });
  });

  it("signs in with a join code and lists the projects with their progress", async () => {
    api.signedIn.mockReturnValueOnce(false).mockReturnValue(true);
    api.join.mockResolvedValue({ userId: "u-3", displayName: "Rina", role: "reporter" });
    api.me.mockResolvedValue({ userId: "u-3", displayName: "Rina", role: "reporter" });
    render(DashboardApp);
    await fireEvent.input(await screen.findByLabelText("Join code"), { target: { value: " AB-CD " } });
    await fireEvent.input(screen.getByLabelText("Your name"), { target: { value: "Rina" } });
    await fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(api.join).toHaveBeenCalledWith("AB-CD", "Rina"));
    expect(await screen.findByText("Titus")).toBeInTheDocument();
    expect(screen.getByText("1/2 ch")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("ch 2: Revant")).toBeInTheDocument();
    // A reporter: no Users tab, no Assign, but the export is there.
    expect(screen.queryByRole("button", { name: "Users" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Assign…" })).toBeNull();
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeEnabled();
    expect(api.users).not.toHaveBeenCalled();
  });

  it("lets a project admin assign a chapter and invite a user", async () => {
    api.signedIn.mockReturnValue(true);
    api.me.mockResolvedValue({ userId: "u-1", displayName: "Revant", role: "project_admin" });
    api.assign.mockResolvedValue({ changed: true });
    api.joinCode.mockResolvedValue({ joinCode: "1A2B-3C4D-5E6F", role: "reporter" });
    render(DashboardApp);
    await fireEvent.click(await screen.findByRole("button", { name: "Assign…" }));
    await fireEvent.change(screen.getByLabelText("Assignee for Chapter 1"), { target: { value: "u-2" } });
    await waitFor(() => expect(api.assign).toHaveBeenCalledWith("p-tit", "1", "u-2"));
    await screen.findByText("Saved. Devices pick it up on their next sync.");

    await fireEvent.click(screen.getByRole("button", { name: "Users" }));
    expect(screen.getByText("Rina")).toBeInTheDocument();
    await fireEvent.change(screen.getByLabelText("Role for the invitation"), { target: { value: "reporter" } });
    await fireEvent.click(screen.getByRole("button", { name: "Create join code" }));
    expect(await screen.findByText("1A2B-3C4D-5E6F")).toBeInTheDocument();
    expect(api.joinCode).toHaveBeenCalledWith("reporter");
  });

  it("explains an empty hub", async () => {
    api.signedIn.mockReturnValue(true);
    api.me.mockResolvedValue({ userId: "u-1", displayName: "Revant", role: "editor" });
    api.projects.mockResolvedValue({ projects: [] });
    render(DashboardApp);
    expect(await screen.findByText(/No book is linked to this hub yet/)).toBeInTheDocument();
  });
});

describe("projectsCsv", () => {
  it("writes one row per book with quoting where needed", () => {
    const csv = projectsCsv([project({ projectName: "Pastorals, part 1" })]);
    const lines = csv.trim().split("\n");
    expect(lines[0]).toBe("Book,Project,Chapters,Checked chapters,Verses,Reviewed verses,Aligned verses,Language QA clean verses,Assigned to,Last activity");
    expect(lines[1]).toBe('Titus,"Pastorals, part 1",2,1,40,10,10,0,ch 2: Revant,2026-10-14T09:00:00Z');
  });
});
