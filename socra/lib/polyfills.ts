/**
 * Polyfills for features not yet available in all Node.js versions.
 * Import this file early in server-side code paths that need these features.
 */

// Promise.try polyfill (ES2025 / TC39 Stage 4)
// Some libraries like unpdf use it internally. Node 22 has it but it may not
// be available in all environments or when running under certain runtimes.
if (typeof Promise.try !== "function") {
  // @ts-expect-error -- adding polyfill to global Promise
  Promise.try = function <T>(fn: () => T | PromiseLike<T>): Promise<T> {
    return new Promise<T>((resolve) => resolve(fn()))
  }
}

export {}
