import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { paratextLinkStatus } = vi.hoisted(() => ({ paratextLinkStatus: vi.fn() }));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { paratextLinkStatus, paratextRelink: vi.fn(), paratextRefresh: vi.fn(), pickFolder: vi.fn() },
}));

import ProjectDashboard from "../ProjectDashboard.svelte";
import { projectDetailsCollapsed } from "../../editorPrefs";
import type { ProjectReport } from "../../types/finding";

const books = [{
  path: "/projects/rut", bookId: "rut", bookName: "ரூத்", missing: false, lazy: false,
  progress: {
    chapterCount: 4, checkedChapterCount: 2, verseCount: 85, reviewedVerseCount: 10, alignedVerseCount: 7,
    alignedKnownVerseCount: 40, languageQaCheckedVerseCount: 40, languageQaCleanVerseCount: 31, updatedAt: "",
  },
}] as never;

const report = {
  project: "Ruth", bookId: "rut", exceptionQueue: [], qaSeverityCounts: {}, needsDiscussion: [],
  publicationGate: { readyForHumanPublicationSignoff: true, criticalFindings: 0, highFindings: 0, staleAIReviews: 0, openDiscussions: 0 },
  coverage: { verses: { counts: { PASS: 1, ISSUE: 0, REVIEW_REQUIRED: 0, NOT_CHECKED: 0 }, totalVerses: 1, checkedPercent: 100 }, resources: {} },
} as unknown as ProjectReport;

function mount() {
  return render(ProjectDashboard, {
    props: {
      projectName: "IRV Tamil", subtitle: "Tamil · 66 books", books, loading: false, error: "",
      onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report, reportLoading: false, reportError: "", openBookName: "ரூத்",
    },
  });
}

const KEY = "bridge.dashboard.projectDetailsCollapsed.v1";

// #374: the project details block folds to one row, like Collection QA.
describe("ProjectDashboard project details fold (#374)", () => {
  beforeEach(() => {
    paratextLinkStatus.mockResolvedValue({
      state: "linked", folder: "C:/PT/TSTP", guid: "abc", name: "TSTP", fullName: "Synthetic", versification: "eng",
      encoding: "65001", booksPresent: ["RUT"], linkedAt: "",
      files: { notes: { count: 0, users: [] }, bookNames: true, commentTags: false, userAccess: false,
        termRenderings: false, errorDenials: false, spellingStatus: false, checkingStatus: false, progress: false },
      notesIndex: { state: "ready", threads: 0, builtAt: "", buildSeconds: 0, source: "files", error: "" },
    });
    projectDetailsCollapsed.set(false);
  });

  it("opens by default with the eyebrow, the book heading and the Paratext strip", async () => {
    mount();
    const fold = screen.getByRole("button", { name: "Collapse project details" });
    expect(fold.getAttribute("aria-expanded")).toBe("true");
    expect(fold.getAttribute("aria-controls")).toBe("project-details");
    expect(screen.getByText("PROJECT")).toBeInTheDocument();
    expect(screen.getByTitle("ரூத்")).toBeInTheDocument();
    expect(await screen.findByTestId("paratext-link-status")).toBeInTheDocument();
  });

  it("folds to the name and subtitle, hides the strip and the book heading, and remembers the choice", async () => {
    mount();
    await screen.findByTestId("paratext-link-status");
    await fireEvent.click(screen.getByRole("button", { name: "Collapse project details" }));

    const fold = screen.getByRole("button", { name: "Expand project details" });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    expect(fold.textContent).toBe("▸");
    expect(screen.getByRole("heading", { level: 1, name: "IRV Tamil" })).toBeInTheDocument();
    expect(screen.getByText("· Tamil · 66 books")).toBeInTheDocument();
    expect(screen.queryByText("PROJECT")).toBeNull();
    expect(screen.queryByTitle("ரூத்")).toBeNull();
    expect(screen.queryByTestId("paratext-link-status")).toBeNull();
    expect(get(projectDetailsCollapsed)).toBe(true);
    expect(localStorage.getItem(KEY)).toBe("true");

    await fireEvent.click(fold);
    expect(screen.getByRole("button", { name: "Collapse project details" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("PROJECT")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("paratext-link-status")).toBeInTheDocument());
    expect(localStorage.getItem(KEY)).toBe("false");
  });

  it("starts folded when the device remembered it", () => {
    projectDetailsCollapsed.set(true);
    mount();
    expect(screen.getByRole("button", { name: "Expand project details" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("PROJECT")).toBeNull();
  });

  it("is a native button, so Tab reaches it and Enter or Space toggle it", async () => {
    mount();
    const fold = screen.getByRole("button", { name: "Collapse project details" });
    expect(fold.tagName).toBe("BUTTON");
    expect(fold.getAttribute("tabindex")).not.toBe("-1");
    // jsdom synthesises no click from Enter or Space; a native <button> does in the webview.
    await fireEvent.click(fold);
    expect(get(projectDetailsCollapsed)).toBe(true);
  });
});
