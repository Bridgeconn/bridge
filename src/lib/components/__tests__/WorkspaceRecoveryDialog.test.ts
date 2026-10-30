import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import WorkspaceRecoveryDialog from "../WorkspaceRecoveryDialog.svelte";
import type { RecoverySummary } from "../../workspaceRecovery";

const summary: RecoverySummary = {
  title: "Workspace restored",
  headline: "Your workspace was restored from its last-good backup.",
  facts: [
    { label: "Damaged file set aside as", value: "workspace.quarantined-20261029T062654Z.sqlite3" },
    { label: "Rediscovered in the projects folder", value: "202 project books" },
  ],
  lost: ["changes made since the backup was written"],
  hub: "",
  needsAction: false,
};

describe("WorkspaceRecoveryDialog (#338)", () => {
  it("shows the title, the facts and what was lost, as a modal alert", () => {
    render(WorkspaceRecoveryDialog, { summary, onClose: vi.fn() });
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAccessibleName("Workspace restored");
    expect(dialog).toHaveTextContent("workspace.quarantined-20261029T062654Z.sqlite3");
    expect(dialog).toHaveTextContent("202 project books");
    expect(dialog).toHaveTextContent("Not recovered");
    expect(dialog).toHaveTextContent("changes made since the backup was written");
    expect(dialog).toHaveTextContent("Nothing was deleted");
  });

  it("continues on the button and on Escape", async () => {
    const onClose = vi.fn();
    render(WorkspaceRecoveryDialog, { summary, onClose });
    await fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("highlights a hub line that needs the reviewer to act", () => {
    render(WorkspaceRecoveryDialog, {
      summary: { ...summary, title: "Workspace rebuilt", hub: "Rejoin the hub from Settings > Team.", needsAction: true }, onClose: vi.fn(),
    });
    expect(screen.getByText("Rejoin the hub from Settings > Team.")).toHaveClass("action");
  });
});
