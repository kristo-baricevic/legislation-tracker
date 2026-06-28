import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

const publicPagePaths = [
  "app/bills/page.tsx",
  "app/bills/[id]/page.tsx",
  "app/representatives/page.tsx",
];

describe("public data pages", () => {
  for (const pagePath of publicPagePaths) {
    it(`${pagePath} is not wrapped in RequireAuth`, async () => {
      const source = await readFile(pagePath, "utf8");

      assert.equal(source.includes("RequireAuth"), false);
    });
  }
});
