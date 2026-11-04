import { describe, expect, it, vi } from "vitest";
import { bindReviewProject, reviewProjectPath } from "../../reviewProjectGuard";

describe("review queue request project identity", () => {
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
