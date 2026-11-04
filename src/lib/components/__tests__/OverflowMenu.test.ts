import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import OverflowMenu from "../OverflowMenu.svelte";
import IconButton from "../IconButton.svelte";
it("opens with the keyboard, skips disabled items, returns focus and reports the chosen command", async () => {
  const component = render(OverflowMenu, { label: "Panel tools", actions: [{ id: "disabled", label: "Disabled", disabled: true }, { id: "reset", label: "Reset layout" }] });
  const choose = vi.fn(); component.component.$on("action", choose);
  const trigger = screen.getByRole("button", { name: "Panel tools" });
  trigger.focus(); await fireEvent.keyDown(trigger, { key: "ArrowDown" });
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Reset layout" })));
  await fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(document.activeElement).toBe(trigger); expect(screen.queryByRole("menu")).toBeNull();
  await fireEvent.click(trigger); await fireEvent.click(await screen.findByRole("menuitem", { name: "Reset layout" }));
  expect(choose.mock.calls[0][0].detail.id).toBe("reset"); expect(document.activeElement).toBe(trigger);
});
it("provides state-aware tooltips on keyboard focus and bundled SVG icons", async () => {
  const component = render(IconButton, { icon: "pin", label: "Pin verse", pressed: false });
  const button = screen.getByRole("button", { name: "Pin verse" }); await fireEvent.focus(button);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Pin verse"); expect(button.querySelector("svg path")).toBeTruthy();
  await component.rerender({ label: "Follow editor", pressed: true });
  expect(screen.getByRole("tooltip")).toHaveTextContent("Follow editor"); expect(button).toHaveAttribute("aria-pressed", "true");
});
