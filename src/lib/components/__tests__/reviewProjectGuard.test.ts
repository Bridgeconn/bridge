import { describe, expect, it, vi } from "vitest";
import { bindReviewProject, reviewProjectPath, setWindowProjectPath } from "../../reviewProjectGuard";

describe("review queue request project identity", () => {
  it("guards detached calls and lets each component retain its original project across a context switch", async () => {
    setWindowProjectPath("A");
    const old = bindReviewProject({ request: () => reviewProjectPath() }, "A");
    setWindowProjectPath("B");
    expect(reviewProjectPath()).toBe("B"); expect(old.request()).toBe("A"); expect(reviewProjectPath()).toBe("B");
    setWindowProjectPath(undefined);
  });
  it("captures the instance's project synchronously without leaking it to editor calls", async () => {
    const submit = vi.fn(async () => {
      const captured = reviewProjectPath();
      await Promise.resolve();
      return captured;
    });
    const api = { submit };
    const oldQueue = bindReviewProject(api, "old-book");
    const newQueue = bindReviewProject(api, "new-book");
    const old = oldQueue.submit();
    const current = newQueue.submit();
    expect(reviewProjectPath()).toBeUndefined();
    expect(await old).toBe("old-book");
    expect(await current).toBe("new-book");
    expect(await api.submit()).toBeUndefined();
  });

  it("restores the request context when submission throws", () => {
    const queue = bindReviewProject({ submit() { throw new Error("offline"); } }, "book");
    expect(() => queue.submit()).toThrow("offline");
    expect(reviewProjectPath()).toBeUndefined();
  });
});
