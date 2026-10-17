import { defineConfig } from "vitest/config";

// The Workers runtime pool (cloudflareTest from @cloudflare/vitest-pool-workers) is wired in
// once suggest/ and inbox/ have entry points; until then this runs plain vitest.
export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    passWithNoTests: true,
  },
});
