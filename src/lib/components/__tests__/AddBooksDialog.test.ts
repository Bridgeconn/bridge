import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const { pickImportFiles, pickProjectFolder, inspectAddBooks, addBooksStart, importStatus, importCancel } = vi.hoisted(() => ({
  pickImportFiles: vi.fn(), pickProjectFolder: vi.fn(), inspectAddBooks: vi.fn(),
  addBooksStart: vi.fn(), importStatus: vi.fn(), importCancel: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: { pickImportFiles, pickProjectFolder, inspectAddBooks, addBooksStart, importStatus, importCancel },
}));

import AddBooksDialog, { booksToWrite } from "../AddBooksDialog.svelte";
import type { AddBooksBook, AddBooksPreview, ImportJobSnapshot, RegisteredProject } from "../../types/finding";

const PROJECT: RegisteredProject = {
  projectId: "p-1", collectionId: "", path: "C:/projects/eng_bible_tit", managed: true, missing: false,
  bookId: "tit", bookName: "Titus", targetLanguage: "English", projectName: "NT review", bibleName: "Test Bible",
};

function book(bookId: string, overrides: Partial<AddBooksBook> = {}): AddBooksBook {
  return {
    bookId, bookName: bookId.toUpperCase(), sourceFile: `C:/sources/${bookId}.usfm`, verseCount: 10, hasAlignments: false,
    exists: false, existingPath: "", existingLazy: false, ...overrides,
  };
}

function preview(books: AddBooksBook[], paths = ["C:/sources"]): AddBooksPreview {
  return {
    projectId: "p-1", projectPath: PROJECT.path, projectName: "NT review", bibleName: "Test Bible",
    sourcePaths: paths, existingBookIds: books.filter((b) => b.exists).map((b) => b.bookId), books, warnings: [],
  };
}

function snapshot(overrides: Partial<ImportJobSnapshot> = {}): ImportJobSnapshot {
  return {
    jobId: "job-1", sourcePath: PROJECT.path, state: "running", phase: "stage", phaseLabel: "Copying PHM",
    totalBooks: 2, completedBooks: 0, currentBook: "phm", chapter: null, chapterCount: null, percent: 40,
    result: null, error: null, createdAt: "2026-10-27T00:00:00Z", finishedAt: null, ...overrides,
  } as ImportJobSnapshot;
}

function mount() {
  const onClose = vi.fn();
  const onAdded = vi.fn();
  render(AddBooksDialog, { props: { project: PROJECT, onClose, onAdded } });
  return { onClose, onAdded };
}

describe("booksToWrite", () => {
  it("writes every new book and only the existing ones marked replace", () => {
    const books = [book("tit", { exists: true }), book("phm"), book("jud", { exists: true })];
    expect(booksToWrite(books, {}).map((b) => b.bookId)).toEqual(["phm"]);
    expect(booksToWrite(books, { tit: "replace", jud: "skip" }).map((b) => b.bookId)).toEqual(["tit", "phm"]);
  });
});

describe("AddBooksDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    importCancel.mockResolvedValue(snapshot({ state: "cancelling" }));
  });

  it("offers files or a folder, using the same pickers as the import, and cancels back", async () => {
    pickImportFiles.mockResolvedValue([]);
    const { onClose } = mount();
    expect(screen.getByRole("heading", { name: "Add books to NT review" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: /Add files/ }));
    expect(pickImportFiles).toHaveBeenCalledTimes(1);
    expect(inspectAddBooks).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("inspects a chosen folder and lists new books with the add button", async () => {
    pickProjectFolder.mockResolvedValue("C:/sources");
    inspectAddBooks.mockResolvedValue(preview([book("phm"), book("jud")]));
    mount();
    await fireEvent.click(screen.getByRole("button", { name: /Add a folder/ }));
    await screen.findByText("2 books were found. Nothing is written until you add them.");
    expect(inspectAddBooks).toHaveBeenCalledWith("p-1", ["C:/sources"]);
    const list = screen.getByRole("group", { name: "Books found" });
    expect(within(list).getAllByText("New")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Add 2 books" })).toBeEnabled();
  });

  it("asks about each existing book, skip or replace, and applies one answer to all when asked", async () => {
    pickImportFiles.mockResolvedValue(["C:/sources/tit.usfm", "C:/sources/jud.usfm", "C:/sources/phm.usfm"]);
    inspectAddBooks.mockResolvedValue(preview([
      book("tit", { exists: true, existingPath: PROJECT.path }), book("phm"), book("jud", { exists: true, existingPath: "C:/projects/eng_bible_jud" }),
    ], ["C:/sources/tit.usfm", "C:/sources/jud.usfm", "C:/sources/phm.usfm"]));
    mount();
    await fireEvent.click(screen.getByRole("button", { name: /Add files/ }));
    await screen.findByRole("heading", { name: "Book already in project" });
    expect(screen.getByText("1 of 2 already in the project")).toBeInTheDocument();
    // The first conflict is answered alone: skip TIT.
    await fireEvent.click(screen.getByRole("button", { name: /Skip this book/ }));
    await screen.findByText("2 of 2 already in the project");
    expect(screen.queryByText(/Do this for all/)).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: /Replace it/ }));

    await screen.findByRole("group", { name: "Books found" });
    expect(screen.getByText("1 new · 1 replace · 1 skip")).toBeInTheDocument();
    const tit = screen.getByRole("group", { name: "TIT is already in the project" });
    expect(within(tit).getByRole("button", { name: "Skip" })).toHaveAttribute("aria-pressed", "true");
    const jud = screen.getByRole("group", { name: "JUD is already in the project" });
    expect(within(jud).getByRole("button", { name: "Replace" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Replacing JUD removes the current text/)).toBeInTheDocument();
    // A choice can still be changed in the list.
    await fireEvent.click(within(tit).getByRole("button", { name: "Replace" }));
    expect(screen.getByText("1 new · 2 replace · 0 skip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add 3 books" })).toBeEnabled();
  });

  it("'do this for all' answers every remaining conflict at once", async () => {
    pickProjectFolder.mockResolvedValue("C:/sources");
    inspectAddBooks.mockResolvedValue(preview([
      book("tit", { exists: true }), book("phm", { exists: true }), book("jud", { exists: true }),
    ]));
    mount();
    await fireEvent.click(screen.getByRole("button", { name: /Add a folder/ }));
    await screen.findByRole("heading", { name: "Book already in project" });
    await fireEvent.click(screen.getByLabelText("Do this for all 3 books already in the project"));
    await fireEvent.click(screen.getByRole("button", { name: /Skip this book/ }));
    await screen.findByRole("group", { name: "Books found" });
    expect(screen.getByText("0 new · 0 replace · 3 skip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nothing to add" })).toBeDisabled();
  });

  it("starts the job with the replace list, shows progress, and reports the outcome", async () => {
    pickProjectFolder.mockResolvedValue("C:/sources");
    inspectAddBooks.mockResolvedValue(preview([book("tit", { exists: true }), book("phm")]));
    addBooksStart.mockResolvedValue(snapshot());
    importStatus
      .mockResolvedValueOnce(snapshot({ percent: 60 }))
      .mockResolvedValue(snapshot({
        state: "succeeded", percent: 100,
        result: {
          projectPath: PROJECT.path, collectionId: "c-1", skipped: [],
          added: [{ path: "C:/projects/eng_bible_phm", bookId: "phm", bookName: "Philemon" }],
          replaced: [{ path: PROJECT.path, bookId: "tit", bookName: "Titus" }],
          projects: [{ path: PROJECT.path, bookId: "tit", bookName: "Titus" }, { path: "C:/projects/eng_bible_phm", bookId: "phm", bookName: "Philemon" }],
        } as never,
      }));
    const { onAdded, onClose } = mount();
    await fireEvent.click(screen.getByRole("button", { name: /Add a folder/ }));
    await screen.findByRole("heading", { name: "Book already in project" });
    await fireEvent.click(screen.getByRole("button", { name: /Replace it/ }));
    await fireEvent.click(await screen.findByRole("button", { name: "Add 2 books" }));
    expect(addBooksStart).toHaveBeenCalledWith("p-1", ["C:/sources"], ["tit"]);
    await screen.findByRole("heading", { name: "Adding books" });
    await screen.findByRole("heading", { name: "Books added" });
    expect(screen.getByText("The project now has 2 books.")).toBeInTheDocument();
    expect(screen.getByText("PHM")).toBeInTheDocument();
    expect(screen.getByText("TIT")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onAdded).toHaveBeenCalledTimes(1);
    expect(onAdded.mock.calls[0][0].collectionId).toBe("c-1");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("returns to the review with the engine's message when the job fails", async () => {
    pickProjectFolder.mockResolvedValue("C:/sources");
    inspectAddBooks.mockResolvedValue(preview([book("phm")]));
    addBooksStart.mockResolvedValue(snapshot());
    importStatus.mockResolvedValue(snapshot({ state: "failed", error: "Disk full." }));
    mount();
    await fireEvent.click(screen.getByRole("button", { name: /Add a folder/ }));
    await fireEvent.click(await screen.findByRole("button", { name: "Add 1 book" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Disk full."));
    expect(screen.getByRole("button", { name: "Add 1 book" })).toBeEnabled();
  });

  it("shows the engine's refusal on the chooser when the source cannot be added", async () => {
    pickImportFiles.mockResolvedValue(["C:/sources/project.tcore"]);
    inspectAddBooks.mockRejectedValue(new Error("project.tcore is a translationCore project."));
    mount();
    await fireEvent.click(screen.getByRole("button", { name: /Add files/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("translationCore project"));
    expect(screen.getByRole("button", { name: /Add files/ })).toBeEnabled();
  });
});
