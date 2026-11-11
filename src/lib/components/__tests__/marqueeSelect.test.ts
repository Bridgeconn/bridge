import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { createMarquee } from "../../marqueeSelect";

function pointer(x: number, y: number, extra: Partial<PointerEvent> = {}): PointerEvent {
  return { clientX: x, clientY: y, button: 0, target: null, ...extra } as unknown as PointerEvent;
}

/** A word bank with three items laid out on one row, 60px apart, plus a
 *  rect lookup standing in for layout (jsdom has none). */
function bank() {
  const host = document.createElement("div");
  const rects = new Map<Element, { left: number; top: number; right: number; bottom: number }>();
  ["T001", "T002", "T003"].forEach((id, i) => {
    const item = document.createElement("button");
    item.setAttribute("data-marquee-item", id);
    host.appendChild(item);
    rects.set(item, { left: i * 60, top: 0, right: i * 60 + 50, bottom: 30 });
  });
  return { host, rectOf: (el: Element) => rects.get(el)! };
}

describe("createMarquee (#410)", () => {
  it("picks the items the rectangle touches as the pointer moves, and swallows the trailing click once", () => {
    const { host, rectOf } = bank();
    const onStart = vi.fn(), onChange = vi.fn(), onEnd = vi.fn();
    const marquee = createMarquee({ rectOf, onStart, onChange, onEnd });
    marquee.start(pointer(200, 50), host);
    marquee.move(pointer(198, 49)); // under the threshold: a click so far
    expect(onStart).not.toHaveBeenCalled();
    marquee.move(pointer(100, 10));
    expect(onStart).toHaveBeenCalledWith(false);
    expect(onChange).toHaveBeenLastCalledWith(["T002", "T003"], false);
    expect(get(marquee.state)).toMatchObject({ moved: true, rect: { left: 100, top: 10, width: 100, height: 40 }, hits: ["T002", "T003"] });
    marquee.move(pointer(10, 10));
    expect(onChange).toHaveBeenLastCalledWith(["T001", "T002", "T003"], false);
    marquee.up();
    expect(onEnd).toHaveBeenCalledWith(["T001", "T002", "T003"], false);
    expect(get(marquee.state)).toMatchObject({ active: false, moved: false, rect: null, hits: [] });
    expect(marquee.consumeSuppressedClick()).toBe(true);
    expect(marquee.consumeSuppressedClick()).toBe(false);
  });

  it("is additive when the press holds Ctrl", () => {
    const { host, rectOf } = bank();
    const onChange = vi.fn();
    const marquee = createMarquee({ rectOf, onChange });
    marquee.start(pointer(200, 50, { ctrlKey: true }), host);
    marquee.move(pointer(130, 10));
    expect(onChange).toHaveBeenLastCalledWith(["T003"], true);
  });

  it("a press without movement is a plain click: no selection, no swallowed click", () => {
    const { host, rectOf } = bank();
    const onChange = vi.fn(), onEnd = vi.fn();
    const marquee = createMarquee({ rectOf, onChange, onEnd });
    marquee.start(pointer(200, 50), host);
    marquee.up();
    expect(onChange).not.toHaveBeenCalled();
    expect(onEnd).not.toHaveBeenCalled();
    expect(marquee.consumeSuppressedClick()).toBe(false);
  });

  it("does not start on an item or a button (their own pointerdown starts a drag), nor on a secondary button", () => {
    const { host, rectOf } = bank();
    const marquee = createMarquee({ rectOf, onChange: vi.fn() });
    marquee.start(pointer(0, 0, { target: host.firstElementChild } as Partial<PointerEvent>), host);
    expect(get(marquee.state).active).toBe(false);
    marquee.start({ ...pointer(0, 0), button: 2 } as PointerEvent, host);
    expect(get(marquee.state).active).toBe(false);
    marquee.start(pointer(0, 0), host);
    expect(get(marquee.state).active).toBe(true);
  });

  it("attaches window listeners and detaches them", () => {
    const listeners = new Map<string, (event: Event) => void>();
    const target = {
      addEventListener: (type: string, fn: EventListenerOrEventListenerObject) => listeners.set(type, fn as (event: Event) => void),
      removeEventListener: (type: string) => listeners.delete(type),
    };
    const { host, rectOf } = bank();
    const onEnd = vi.fn();
    const marquee = createMarquee({ rectOf, onChange: vi.fn(), onEnd });
    const detach = marquee.attach(target);
    marquee.start(pointer(200, 50), host);
    listeners.get("pointermove")!(pointer(10, 10) as unknown as Event);
    listeners.get("pointerup")!(new Event("pointerup"));
    expect(onEnd).toHaveBeenCalledWith(["T001", "T002", "T003"], false);
    detach();
    expect(listeners.size).toBe(0);
  });
});
