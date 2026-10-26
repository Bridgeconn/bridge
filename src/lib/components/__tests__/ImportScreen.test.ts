import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { listProjects, inspectImport, importStart, importStatus, importCancel, openProject } = vi.hoisted(() => ({
  listProjects: vi.fn(),
  inspectImport: vi.fn(),
  importStart: vi.fn(),
  importStatus: vi.fn(),
  importCancel: vi.fn(),
  openProject: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    listProjects, inspectImport, importStart, importStatus, importCancel, openProject,
    pickImportFile: vi.fn(), pickProjectFolder: vi.fn(), forgetProject: vi.fn(), deleteProject: vi.fn(),
  },
}));

import ImportScreen, { forgetHandledDrops } from "../ImportScreen.svelte";
import { project } from "../../stores";
import type { ImportJobSnapshot, ImportPreview, ProjectInfo } from "../../types/finding";

const SOURCE = "C:/sources/TIT.usfm";
const PRIMARY = "C:/projects/eng_test_bible_tit";

function preview(): ImportPreview {
  return {
    sourcePath: SOURCE,
    kind: "usfm",
    metadata: {
      languageId: "eng", languageName: "English", languageDirection: "ltr",
      projectName: "Titus review", bibleName: "Test Bible",
    },
    books: [{ bookId: "tit", bookName: "Titus", sourceFile: SOURCE, verseCount: 3, hasAlignments: false }],
    missingFields: [],
    warnings: [],
    duplicates: {
      classification: "new", matches: [], inputBookCount: 1, exactBookCount: 0, missingExactBookCount: 0,
      possibleBookCount: 0, overlapBookCount: 0, matchingGroupCount: 0, exactMatchGroupId: "",
      sourceFingerprints: {}, collectionFingerprint: "",
    },
  };
}

function snapshot(overrides: Partial<ImportJobSnapshot> = {}): ImportJobSnapshot {
  return {
    jobId: "job-1", sourcePath: SOURCE, state: "queued", phase: "queued", phaseLabel: "Starting",
    totalBooks: 0, completedBooks: 0, currentBook: null, chapter: null, chapterCount: null, percent: 0,
    result: null, error: null, createdAt: "2026-10-14T09:00:00Z", finishedAt: null, ...overrides,
  };
}

const succeeded = snapshot({
  state: "succeeded", phase: "register", phaseLabel: "Registering", totalBooks: 1, completedBooks: 1,
  percent: 100, finishedAt: "2026-10-14T09:00:03Z",
  result: {
    sourcePath: SOURCE, kind: "usfm", projectName: "Titus review", bibleName: "Test Bible",
    primaryProjectPath: PRIMARY,
    projects: [{ path: PRIMARY, bookId: "tit", bookName: "Titus", projectId: "p-1", collectionId: "" }],
  },
});

const opened: ProjectInfo = {
  path: PRIMARY, bookId: "tit", bookName: "Titus", targetLanguage: "English", tcVersion: "0.8.0",
  chapters: ["1", "2"], checkTypes: {},
};

async function renderWithPreview() {
  const onOpened = vi.fn();
  render(ImportScreen, { props: { onOpened, droppedPath: SOURCE, dropSequence: 1 } });
  await screen.findByText("Confirm project details");
  return onOpened;
}

// #301: App.svelte keeps the last drop's props, and closing a book mounts a
// fresh ImportScreen with them. Found on the 0.18.0 walk.
describe("ImportScreen drops (#301)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    forgetHandledDrops();
    project.set(null);
    listProjects.mockResolvedValue({ projects: [] });
    inspectImport.mockResolvedValue(preview());
  });

  it("does not reopen a handled drop when a fresh screen mounts with the same props", async () => {
    const first = render(ImportScreen, { props: { onOpened: vi.fn(), droppedPath: SOURCE, dropSequence: 1 } });
    await screen.findByText("Confirm project details");
    expect(inspectImport).toHaveBeenCalledTimes(1);
    first.unmount();
    // Back to Projects after the import: App passes the same path and sequence.
    render(ImportScreen, { props: { onOpened: vi.fn(), droppedPath: SOURCE, dropSequence: 1 } });
    await screen.findByText("Import a file");
    expect(inspectImport).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Confirm project details")).toBeNull();
  });

  it("inspects the new file when a drop arrives while a book was open, not the previous one", async () => {
    const first = render(ImportScreen, { props: { onOpened: vi.fn(), droppedPath: SOURCE, dropSequence: 1 } });
    await screen.findByText("Confirm project details");
    first.unmount();
    // The book closes first (the screen mounts with the old drop), then App sets the new one.
    const second = render(ImportScreen, { props: { onOpened: vi.fn(), droppedPath: SOURCE, dropSequence: 1 } });
    await second.component.$set({ droppedPath: "C:/sources/3JN.usfm", dropSequence: 2 });
    await waitFor(() => expect(inspectImport).toHaveBeenCalledTimes(2));
    expect(inspectImport).toHaveBeenLastCalledWith("C:/sources/3JN.usfm");
  });
});

describe("ImportScreen background import (#231)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    forgetHandledDrops();
    project.set(null);
    listProjects.mockResolvedValue({ projects: [] });
    inspectImport.mockResolvedValue(preview());
    importStart.mockResolvedValue(snapshot());
    openProject.mockResolvedValue({ ...opened });
  });

  it("hides project search when there are no registered projects", async () => {
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    await screen.findByText(/No projects are registered yet/);
    expect(screen.queryByRole("searchbox", { name: "Search projects" })).toBeNull();
  });

  it("selects all books initially, supports bulk selection, and imports only checked books", async () => {
    const multi = preview();
    multi.books.push({ bookId: "phm", bookName: "Philemon", sourceFile: "C:/sources/PHM.usfm", verseCount: 1, hasAlignments: false });
    inspectImport.mockImplementation(async (_path, _metadata, selected) => selected
      ? { ...multi, books: multi.books.filter((book) => selected.includes(book.bookId)) } : multi);
    importStatus.mockResolvedValue(snapshot({ state: "cancelled" }));
    await renderWithPreview();
    expect(screen.getByRole("checkbox", { name: "Import Titus" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Import Philemon" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Unselect all" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Select all" })).toBeNull();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Unselect all" }));
    expect(screen.getByRole("checkbox", { name: "Select all" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Unselect all" })).toBeNull();
    expect(screen.getByRole("button", { name: "Import 0 books" })).toBeDisabled();
    expect(screen.getByText("Select at least one book.")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByRole("checkbox", { name: "Import Titus" })).toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Import Titus" }));
    expect(screen.getByRole("checkbox", { name: "Select all" })).not.toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByRole("checkbox", { name: "Unselect all" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Import Titus" })).toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Import Titus" }));
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await waitFor(() => expect(importStart).toHaveBeenCalledWith(SOURCE, expect.anything(), false, ["phm"]));
    expect(inspectImport).toHaveBeenLastCalledWith(SOURCE, expect.anything(), ["phm"]);
    expect(screen.getByRole("checkbox", { name: "Import Titus" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Import Philemon" })).toBeChecked();
  });

  it("refuses a partial import when an older engine ignores the selection", async () => {
    const multi = preview();
    multi.books.push({ bookId: "phm", bookName: "Philemon", sourceFile: "C:/sources/PHM.usfm", verseCount: 1, hasAlignments: false });
    inspectImport.mockResolvedValue(multi);
    await renderWithPreview();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Import Titus" }));
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await screen.findByText(/Book selection requires the updated engine/);
    expect(importStart).not.toHaveBeenCalled();
  });

  it("shows the bar and Cancel as soon as the job starts, then opens the primary book", async () => {
    // The first poll is held back so the banner can be checked as drawn from
    // the start snapshot alone, before any status has answered.
    let answerFirstPoll: (value: ImportJobSnapshot) => void = () => {};
    importStatus
      .mockImplementationOnce(() => new Promise<ImportJobSnapshot>((resolve) => { answerFirstPoll = resolve; }))
      .mockResolvedValue(succeeded);
    const onOpened = await renderWithPreview();

    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));

    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent("Importing: Starting — 0%");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(importStart).toHaveBeenCalledWith(SOURCE, expect.objectContaining({ languageId: "eng" }), false);
    // The screen itself is not modal: Back stays available while it runs.
    expect(screen.getByRole("button", { name: "Back to projects" })).toBeEnabled();

    answerFirstPoll(snapshot({
      state: "running", phase: "normalize", phaseLabel: "Preparing TIT", totalBooks: 1,
      currentBook: "tit", chapter: 2, chapterCount: 2, percent: 50,
    }));
    await waitFor(() => expect(banner).toHaveTextContent("Preparing TIT, chapter 2 of 2 — 50%"));
    await waitFor(() => expect(onOpened).toHaveBeenCalledTimes(1));
    expect(openProject).toHaveBeenCalledWith(PRIMARY, "p-1");
    expect(get(project)?.importedProjects).toEqual(succeeded.result?.projects);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("cancel asks the engine, nothing opens, and the import can be started again", async () => {
    const running = snapshot({ state: "running", phase: "normalize", phaseLabel: "Preparing TIT", totalBooks: 1, currentBook: "tit", percent: 20 });
    let cancelled = false;
    importStatus.mockImplementation(async () => (cancelled
      ? snapshot({ state: "cancelled", phase: "normalize", finishedAt: "2026-10-14T09:00:01Z" })
      : running));
    importCancel.mockImplementation(async () => {
      cancelled = true;
      return snapshot({ ...running, state: "cancelling" });
    });
    const onOpened = await renderWithPreview();

    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    const cancel = await screen.findByRole("button", { name: "Cancel" });
    await fireEvent.click(cancel);

    expect(importCancel).toHaveBeenCalledWith("job-1");
    await screen.findByText("Import cancelled. Nothing was written.");
    expect(onOpened).not.toHaveBeenCalled();
    expect(openProject).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button", { name: "Import book" })).toBeEnabled();
  });

  it("reports a failed job as an error and leaves the form usable", async () => {
    importStatus.mockResolvedValue(snapshot({ state: "failed", error: "Import metadata is incomplete: projectName" }));
    const onOpened = await renderWithPreview();

    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));

    await screen.findByText("Import metadata is incomplete: projectName");
    expect(onOpened).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Import book" })).toBeEnabled();
  });
});

// #308: a Paratext folder gives the engine only an ISO code, no name.
describe("ImportScreen detected language code (#308)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    forgetHandledDrops();
    project.set(null);
    listProjects.mockResolvedValue({ projects: [] });
  });

  it("names a known ISO 639-3 code from the language table, so import is not blocked", async () => {
    const base = preview();
    inspectImport.mockResolvedValue({ ...base, kind: "paratext", metadata: { ...base.metadata, languageId: "san", languageName: "" } });
    await renderWithPreview();

    expect(screen.getByPlaceholderText("Search language or code")).toHaveValue("Sanskrit");
    expect(screen.getByPlaceholderText("ISO 639-3")).toHaveValue("san");
    expect(screen.queryByText("Choose a language and enter both names.")).toBeNull();
  });

  it("falls back to Paratext's own language name only for a code not in the table (#355)", async () => {
    const base = preview();
    inspectImport.mockResolvedValue({
      ...base, kind: "paratext", paratextLanguageName: "Somelang",
      metadata: { ...base.metadata, languageId: "qqq", languageName: "" },
    });
    await renderWithPreview();

    expect(screen.getByPlaceholderText("Search language or code")).toHaveValue("Somelang");
  });

  it("prefers the ISO name over Paratext's free-text <Language> (#355)", async () => {
    const base = preview();
    inspectImport.mockResolvedValue({
      ...base, kind: "paratext", paratextLanguageName: "TestDeva",
      metadata: { ...base.metadata, languageId: "san", languageName: "" },
    });
    await renderWithPreview();

    expect(screen.getByPlaceholderText("Search language or code")).toHaveValue("Sanskrit");
  });

  it("shows the Paratext project name and Guid (#355)", async () => {
    const base = preview();
    inspectImport.mockResolvedValue({
      ...base, kind: "paratext",
      paratext: {
        schemaVersion: 1, guid: "03a0211850", folder: "C:/PT/TSTP", name: "TSTP", fullName: "Synthetic Test",
        versification: "eng", naming: { prePart: "", postPart: "TSTP.SFM", bookNameForm: "41MAT" },
        booksPresent: ["TIT"], settingsSha256: "x", linkedAt: "2026-10-22T00:00:00+00:00",
      },
    });
    await renderWithPreview();

    const link = screen.getByTestId("paratext-link");
    expect(link).toHaveTextContent("Paratext project TSTP (Synthetic Test)");
    expect(link).toHaveTextContent("Guid 03a0211850");
  });

  it("shows no Paratext line for a plain USFM source", async () => {
    inspectImport.mockResolvedValue(preview());
    await renderWithPreview();
    expect(screen.queryByTestId("paratext-link")).toBeNull();
  });

  it("leaves an unknown code unnamed for the reviewer", async () => {
    const base = preview();
    inspectImport.mockResolvedValue({ ...base, kind: "paratext", metadata: { ...base.metadata, languageId: "qqq", languageName: "" } });
    await renderWithPreview();

    expect(screen.getByText("Choose a language and enter both names.")).toBeInTheDocument();
  });
});
