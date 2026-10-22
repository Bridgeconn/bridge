import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/svelte";

import DiagnosticsPanel from "../DiagnosticsPanel.svelte";

describe("DiagnosticsPanel Escape (#321)", () => {
  it("closes on Escape, as the close button does, and returns focus to the invoker", async () => {
    const opener = document.createElement("button");
    opener.textContent = "Diagnostics";
    document.body.appendChild(opener);
    opener.focus();
    const onClose = vi.fn();
    const { unmount } = render(DiagnosticsPanel, { props: { onClose } });
    await fireEvent.keyDown(window, { key: "a" });
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
