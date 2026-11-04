import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { project } from "../../stores";
const mock = vi.hoisted(() => ({ preview: vi.fn(), start: vi.fn(), step: vi.fn(), status: vi.fn(), cancel: vi.fn(), confirm: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  previewChapterReset: mock.preview, startChapterReset: mock.start, stepChapterReset: mock.step,
  chapterResetStatus: mock.status, cancelChapterReset: mock.cancel,
} }));
vi.mock("../../confirmAction", () => ({ askConfirmation: mock.confirm }));
import AlignmentChapterReset from "../AlignmentChapterReset.svelte";
describe("chapter reset requires an explicit confirmed preview", () => {
  beforeEach(() => {
    vi.clearAllMocks(); project.set({ path: "book", bookId: "php" } as never);
    mock.status.mockResolvedValue({ state: "idle", completed: 0, total: 0 });
    mock.preview.mockResolvedValue({ token: "fresh", verses: ["3", "6"], groups: 7, links: 2, decisions: 1 });
    mock.start.mockResolvedValue({ id: "job", chapter: "1", state: "running", completed: 0, total: 2 });
  });
  it("does not start or clear anything when the reviewer declines", async () => {
    mock.confirm.mockResolvedValue(false);
    render(AlignmentChapterReset, { chapter: "1", onBusy: vi.fn(), onChanged: vi.fn() });
    await fireEvent.click(screen.getByRole("button", { name: "Reset chapter alignment" }));
    await waitFor(() => expect(mock.confirm).toHaveBeenCalledWith(expect.objectContaining({ body: expect.stringContaining("7 groups, 2 cross-verse groups") })));
    expect(mock.start).not.toHaveBeenCalled(); expect(mock.step).not.toHaveBeenCalled();
  });
  it("advances one verse at a time and reports completion", async () => {
    mock.confirm.mockResolvedValue(true);
    mock.step.mockResolvedValueOnce({ job: { id: "job", chapter: "1", state: "running", completed: 1, total: 2 }, contexts: [] })
      .mockResolvedValueOnce({ job: { id: "job", chapter: "1", state: "succeeded", completed: 2, total: 2 }, contexts: [] });
    const changed = vi.fn();
    render(AlignmentChapterReset, { chapter: "1", onBusy: vi.fn(), onChanged: changed });
    await fireEvent.click(screen.getByRole("button", { name: "Reset chapter alignment" }));
    await screen.findByText(/2\/2 verses · succeeded/);
    expect(mock.start).toHaveBeenCalledWith("1", "fresh"); expect(mock.step).toHaveBeenCalledTimes(2); expect(changed).toHaveBeenCalledTimes(2);
  });
});
