import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { listProjects, renameProject, archiveProject, unarchiveProject, openProject } = vi.hoisted(() => ({
  listProjects: vi.fn(),
  renameProject: vi.fn(),
  archiveProject: vi.fn(),
  unarchiveProject: vi.fn(),
  openProject: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    listProjects, renameProject, archiveProject, unarchiveProject, openProject,
    inspectImport: vi.fn(), importStart: vi.fn(), importStatus: vi.fn(), importCancel: vi.fn(),
    pickImportFile: vi.fn(), pickProjectFolder: vi.fn(), forgetProject: vi.fn(), deleteProject: vi.fn(),
  },
}));

import ImportScreen from "../ImportScreen.svelte";
import type { RegisteredProject } from "../../types/finding";

function project(overrides: Partial<RegisteredProject> = {}): RegisteredProject {
  return {
    projectId: "p-1", collectionId: "c-1", path: "C:/projects/eng_bible_gen", managed: true, missing: false,
    bookId: "gen", bookName: "Genesis", targetLanguageId: "eng", targetLanguage: "English",
    projectName: "NT review", bibleName: "Test Bible", lastOpenedAt: "2026-10-14T09:00:00Z", bookCount: 2,
    lastOpenedBy: "u-1", lastOpenedByName: "Revant",
    progress: {
      chapterCount: 50, checkedChapterCount: 3, verseCount: 1533, checkedVerseCount: 90, reviewedVerseCount: 40,
      alignedVerseCount: 20, alignedKnownVerseCount: 90, languageQaCheckedVerseCount: 90, languageQaCleanVerseCount: 70,
      booksWithProgress: 1,
    },
    ...overrides,
  };
}

describe("ImportScreen projects list (#238)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listProjects.mockResolvedValue({ projects: [project()] });
    renameProject.mockResolvedValue({ projectId: "p-1", displayName: "Genesis study", books: 2 });
    archiveProject.mockResolvedValue({ projectId: "p-1", archived: true, books: 2 });
    unarchiveProject.mockResolvedValue({ projectId: "p-1", archived: false, books: 2 });
  });

  it("shows name, language, books, the four progress stages and last opened by", async () => {
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");
    expect(screen.getByText(/2-book collection · Test Bible · English/)).toBeInTheDocument();
    expect(screen.getByText("checked 3/50 ch · reviewed 40/1533 · aligned 20/90 · LQA clean 70/90")).toBeInTheDocument();
    expect(screen.getByText(/opened .* by Revant/)).toBeInTheDocument();
  });

  it("keeps progress and location collapsed until project details are expanded", async () => {
    const { container } = render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");
    const details = container.querySelector("details")!;
    expect(details.open).toBe(false);
    expect(screen.getByRole("button", { name: "Open NT review" })).toBeVisible();
    await fireEvent.click(screen.getByText("Project details"));
    expect(details.open).toBe(true);
    expect(screen.getByText("checked 3/50 ch · reviewed 40/1533 · aligned 20/90 · LQA clean 70/90")).toBeVisible();
    expect(screen.getByText("C:/projects/eng_bible_gen")).toBeVisible();
    await fireEvent.click(screen.getByText("Project details"));
    expect(details.open).toBe(false);
  });

  it("says when nothing has been recorded or opened", async () => {
    listProjects.mockResolvedValue({ projects: [project({ progress: null, lastOpenedAt: "", lastOpenedByName: "" })] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("no progress recorded yet");
    expect(screen.getByText("never opened")).toBeInTheDocument();
  });

  it("renames through the engine and shows the display name over the import's name", async () => {
    listProjects
      .mockResolvedValueOnce({ projects: [project()] })
      .mockResolvedValue({ projects: [project({ displayName: "Genesis study" })] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");

    await fireEvent.click(screen.getByRole("button", { name: "Rename NT review" }));
    const input = screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement;
    expect(input.value).toBe("NT review");
    await fireEvent.input(input, { target: { value: "Genesis study" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(renameProject).toHaveBeenCalledWith("p-1", "Genesis study"));
    await screen.findByText("Genesis study");
    expect(screen.queryByText("NT review")).toBeNull();
  });

  it("archives behind the filter and unarchives from there", async () => {
    listProjects
      .mockResolvedValueOnce({ projects: [project()] })
      .mockResolvedValueOnce({ projects: [project({ archivedAt: "2026-10-14T10:00:00Z" })] })
      .mockResolvedValue({ projects: [project()] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");

    await fireEvent.click(screen.getByRole("button", { name: "Archive NT review" }));
    await waitFor(() => expect(archiveProject).toHaveBeenCalledWith("p-1"));
    // Hidden until the filter is on; the empty-list copy does not appear.
    await waitFor(() => expect(screen.queryByText("NT review")).toBeNull());
    expect(screen.queryByText(/No projects are registered yet/)).toBeNull();
    await fireEvent.click(screen.getByLabelText("Show archived (1)"));
    await screen.findByText("NT review (archived)");

    await fireEvent.click(screen.getByRole("button", { name: "Unarchive NT review" }));
    await waitFor(() => expect(unarchiveProject).toHaveBeenCalledWith("p-1"));
    await screen.findByText("NT review");
    expect(screen.queryByLabelText(/Show archived/)).toBeNull();
  });

  it("filters projects across name, book and language and restores them when cleared", async () => {
    listProjects.mockResolvedValue({ projects: [project(), project({
      projectId: "p-2", displayName: "Tamil study", bookName: "Titus", bookId: "tit", targetLanguage: "தமிழ்", targetLanguageId: "tam",
    })] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");
    const search = screen.getByRole("searchbox", { name: "Search projects" });
    await fireEvent.input(search, { target: { value: "  GEN english  " } });
    expect(screen.getByText("NT review")).toBeInTheDocument();
    expect(screen.queryByText("Tamil study")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 projects");
    await fireEvent.input(search, { target: { value: "தமிழ்" } });
    expect(screen.getByText("Tamil study")).toBeInTheDocument();
    expect(screen.queryByText("NT review")).toBeNull();
    await fireEvent.input(search, { target: { value: "TAMIL STUDY" } });
    expect(screen.getByText("Tamil study")).toBeInTheDocument();
    await fireEvent.input(search, { target: { value: "unknown project" } });
    expect(screen.getByText(/No projects match your search/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Import a file/ })).toBeVisible();
    await fireEvent.click(screen.getByRole("button", { name: "Clear project search" }));
    expect(search).toHaveValue("");
    expect(screen.getByText("NT review")).toBeInTheDocument();
    expect(screen.getByText("Tamil study")).toBeInTheDocument();
  });

  it("searches archived projects only when the archived filter is enabled", async () => {
    listProjects.mockResolvedValue({ projects: [project(), project({
      projectId: "p-2", displayName: "Archived study", archivedAt: "2026-10-14T10:00:00Z",
    })] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");
    await fireEvent.input(screen.getByRole("searchbox", { name: "Search projects" }), { target: { value: "Archived study" } });
    expect(screen.queryByText("Archived study (archived)")).toBeNull();
    await fireEvent.click(screen.getByLabelText("Show archived (1)"));
    expect(screen.getByText("Archived study (archived)")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 projects");
  });

  it("keeps Delete behind its confirmation", async () => {
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");
    await fireEvent.click(screen.getByRole("button", { name: "Delete NT review" }));
    expect(screen.getByText("Delete permanently?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Delete permanently?")).toBeNull();
  });

  // #375: glyph buttons with the action and the project as tooltip and name.
  it("offers icon actions with immediate tooltips and accessible names for each project", async () => {
    listProjects.mockResolvedValue({ projects: [project(), project({ projectId: "p-2", collectionId: "c-2",
      path: "C:/projects/tam_bible_rut", projectName: "IRV Tamil", bookId: "rut", bookName: "Ruth", managed: false })] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("IRV Tamil");
    const open = screen.getByRole("button", { name: "Open IRV Tamil" });
    for (const name of ["Open IRV Tamil", "Rename IRV Tamil", "Archive IRV Tamil", "Rename NT review", "Delete NT review"]) {
      const button = screen.getByRole("button", { name });
      expect(button.tagName).toBe("BUTTON");
      expect(button.querySelector("svg")).not.toBeNull();
      await fireEvent.mouseEnter(button);
      expect(screen.getByRole("tooltip")).toHaveTextContent(name);
      await fireEvent.mouseLeave(button);
      expect(screen.queryByRole("tooltip")).toBeNull();
    }
    // Delete is offered only for a managed project; the order is Open, Add books, Rename, Archive, Delete.
    expect(screen.queryByRole("button", { name: "Delete IRV Tamil" })).toBeNull();
    const row = screen.getByText("NT review").closest(".project-row") as HTMLElement;
    expect([...row.querySelectorAll("button")].map((b) => b.getAttribute("aria-label")))
      .toEqual(["Open NT review", "Add books to NT review", "Rename NT review", "Archive NT review", "Delete NT review"]);
    await fireEvent.click(open);
    await waitFor(() => expect(openProject).toHaveBeenCalled());
  });

  it("gives a missing project Locate and Forget glyphs with their own tooltips", async () => {
    listProjects.mockResolvedValue({ projects: [project({ missing: true })] });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("Project folder is missing");
    expect(screen.getByRole("button", { name: "Locate NT review" }).getAttribute("title")).toBe("Locate NT review");
    expect(screen.getByRole("button", { name: "Forget NT review" }).getAttribute("title")).toBe("Forget NT review");
    expect(screen.queryByRole("button", { name: "Open NT review" })).toBeNull();
  });
});

// #309: a managed copy whose identity is already registered elsewhere.
describe("ImportScreen identity conflict row (#309)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the conflict beside the other projects, with its message and no actions", async () => {
    const message = "The same Bridge project identity exists at two accessible paths; choose which copy is authoritative.";
    listProjects.mockResolvedValue({
      projects: [
        project(),
        project({
          projectId: "", collectionId: "", path: "C:/projects/eng_bible_gen-copy", bookCount: 2,
          projectName: "NT copy", progress: null, lastOpenedAt: "",
          conflict: { message, projectId: "p-1", collectionId: "c-1", registeredPath: "C:/projects/eng_bible_gen" },
        }),
        project({
          projectId: "", path: "C:/projects/second-copy", projectName: "Second copy",
          conflict: { message, projectId: "p-1", collectionId: "c-1", registeredPath: "C:/projects/eng_bible_gen" },
        }),
      ],
    });
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText("NT review");

    expect(screen.getByText("NT copy")).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(message);
    expect(screen.getByText("This copy: C:/projects/eng_bible_gen-copy")).toBeInTheDocument();
    // Only the registered row offers actions.
    expect(screen.getAllByRole("button", { name: "Open NT review" })).toHaveLength(1);
    expect(screen.queryByText("Delete permanently?")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull();
    await fireEvent.input(screen.getByRole("searchbox", { name: "Search projects" }), { target: { value: "Second copy" } });
    expect(screen.getByText("Second copy")).toBeInTheDocument();
    expect(screen.queryByText("NT copy")).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByRole("button", { name: "Open NT review" })).toBeNull();
  });
});
