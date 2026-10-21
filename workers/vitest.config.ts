import { defineConfig } from "vitest/config";

// Plain vitest: the tests hand each Worker fake messages and a fake KV namespace. Switch to the
// Workers runtime pool (@cloudflare/vitest-pool-workers) if a test ever needs the real runtime.
export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    passWithNoTests: true,
  },
});
