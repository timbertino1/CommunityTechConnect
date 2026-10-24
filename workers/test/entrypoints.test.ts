// The Workers runtime treats every named export of a Worker's main module as an entry point and
// refuses to start one that exports anything but its handler (found by T135's `wrangler dev`).

import { describe, expect, it } from "vitest";

describe.each([["suggest"], ["inbox"]])("the %s Worker's main module", (name) => {
  it("exports only its handler", async () => {
    const module = await import(`../${name}/index.ts`);
    expect(Object.keys(module)).toEqual(["default"]);
  });
});
