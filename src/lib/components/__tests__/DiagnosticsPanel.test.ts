import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import DiagnosticsPanel from "../DiagnosticsPanel.svelte";
import { longTasks } from "../../perf";

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

describe("DiagnosticsPanel long tasks (#260)", () => {
  it("says when the WebView records no long tasks, then shows the tally", async () => {
    longTasks.set({ supported: false, count: 0, longestMs: 0, totalMs: 0 });
    const { unmount } = render(DiagnosticsPanel, { props: { onClose: vi.fn() } });
    expect(screen.getByTestId("long-tasks")).toHaveTextContent("Long tasks are not recorded");

    longTasks.set({ supported: true, count: 0, longestMs: 0, totalMs: 0 });
    await Promise.resolve();
    expect(screen.getByTestId("long-tasks")).toHaveTextContent("Long tasks over 250 ms this session: 0");

    longTasks.set({ supported: true, count: 3, longestMs: 812.4, totalMs: 1500 });
    await Promise.resolve();
    expect(screen.getByTestId("long-tasks")).toHaveTextContent(/Long tasks over 250 ms this session: 3\s+\(longest 812.4 ms, 1500 ms in all\)/);
    unmount();
  });
});
