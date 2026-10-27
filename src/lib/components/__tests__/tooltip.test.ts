import { describe, expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/svelte";
import { tooltip } from "../../tooltip";

describe("instant action tooltips", () => {
  it("appears immediately on hover and focus, updates and dismisses with Escape", async () => {
    const button = document.createElement("button");
    document.body.append(button);
    const action = tooltip(button, "Open");
    await fireEvent.mouseEnter(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Open");
    expect(button.getAttribute("aria-describedby")).toBe(screen.getByRole("tooltip").id);
    action.update("Settings");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Settings");
    await fireEvent.mouseLeave(button);
    expect(screen.queryByRole("tooltip")).toBeNull();
    await fireEvent.focus(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Settings");
    await fireEvent.keyDown(button, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    action.destroy();
    button.remove();
  });

  it("renders dialog hints inside the dialog so they appear above its backdrop", async () => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("open", "");
    const button = document.createElement("button");
    dialog.append(button);
    document.body.append(dialog);
    const action = tooltip(button, "Open project");
    await fireEvent.mouseEnter(button);
    expect(screen.getByRole("tooltip").parentElement).toBe(dialog);
    action.destroy();
    dialog.remove();
  });

  it("removes the tooltip when its button is destroyed", async () => {
    const button = document.createElement("button");
    button.setAttribute("aria-describedby", "existing-description");
    document.body.append(button);
    const action = tooltip(button, "Delete");
    await fireEvent.focus(button);
    action.destroy();
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button.getAttribute("aria-describedby")).toBe("existing-description");
    button.remove();
  });
});
