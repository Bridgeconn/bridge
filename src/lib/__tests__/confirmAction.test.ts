/**
 * #372: the in-app confirmation. The answer is a resolved boolean the caller
 * awaits; the dialog's Cancel, Escape and a replacing question all resolve
 * false, so no action can ever read "not answered" as "yes" the way the
 * callers once read the dialog plugin's Promise-returning window.confirm.
 */
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { answerConfirmation, askConfirmation, confirmRequest } from "../confirmAction";
import ConfirmDialog from "../components/ConfirmDialog.svelte";

afterEach(() => answerConfirmation(false));

async function settled<T>(promise: Promise<T>): Promise<T | "pending"> {
  return Promise.race([promise, new Promise<"pending">((resolve) => setTimeout(() => resolve("pending"), 0))]);
}

describe("askConfirmation", () => {
  it("stays unanswered until the dialog answers, then resolves with the answer", async () => {
    const asked = askConfirmation({ title: "Do it?", body: "It costs.", confirmLabel: "Do it" });
    expect(get(confirmRequest)?.title).toBe("Do it?");
    expect(await settled(asked)).toBe("pending");
    answerConfirmation(true);
    expect(await asked).toBe(true);
    expect(get(confirmRequest)).toBeNull();
  });

  it("a question replaced by another is a no", async () => {
    const first = askConfirmation({ title: "First?", body: "", confirmLabel: "Yes" });
    const second = askConfirmation({ title: "Second?", body: "", confirmLabel: "Yes" });
    expect(await first).toBe(false);
    expect(get(confirmRequest)?.title).toBe("Second?");
    answerConfirmation(false);
    expect(await second).toBe(false);
  });

  it("answering with no question open does nothing", () => {
    expect(() => answerConfirmation(true)).not.toThrow();
    expect(get(confirmRequest)).toBeNull();
  });
});

describe("ConfirmDialog", () => {
  it("shows the question, focuses Cancel, and its buttons answer it", async () => {
    const asked = askConfirmation({ title: "Remove the saved API key?", body: "AI stops.", confirmLabel: "Remove key", danger: true });
    render(ConfirmDialog);
    const dialog = screen.getByRole("alertdialog", { name: "Remove the saved API key?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("AI stops.")).toBeInTheDocument();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.activeElement).toBe(cancel);
    const remove = screen.getByRole("button", { name: "Remove key" });
    expect(remove.classList.contains("danger")).toBe(true);
    await fireEvent.click(remove);
    expect(await asked).toBe(true);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("Cancel and Escape both answer no", async () => {
    const byButton = askConfirmation({ title: "Run?", body: "", confirmLabel: "Run" });
    render(ConfirmDialog);
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await byButton).toBe(false);

    const byKey = askConfirmation({ title: "Run again?", body: "", confirmLabel: "Run" });
    await screen.findByRole("alertdialog", { name: "Run again?" });
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(await byKey).toBe(false);
  });
});
