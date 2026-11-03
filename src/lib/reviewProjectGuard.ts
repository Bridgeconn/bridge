// A queue instance keeps its original project even after another window navigates.
// The engine checks this precondition on the dispatcher thread before acting.
let expectedPath: string | undefined;

export function reviewProjectPath(): string | undefined { return expectedPath; }

export function bindReviewProject<T extends object>(api: T, path: string): T {
  return new Proxy(api, {
    get(target, key) {
      const method = Reflect.get(target, key);
      if (typeof method !== "function") return method;
      return (...args: unknown[]) => {
        const previous = expectedPath;
        expectedPath = path;
        try { return Reflect.apply(method, target, args); }
        finally { expectedPath = previous; }
      };
    },
  });
}
