import assert from "node:assert/strict";
import { describe, it } from "node:test";

import * as api from "../lib/api.ts";

describe("bill filter URL parameters", () => {
  it("accepts a positive topic id and rejects malformed values", () => {
    const parseTopicId = (api as typeof api & {
      parseTopicIdFromSearchParam: (value: string | null) => number | undefined;
    }).parseTopicIdFromSearchParam;

    assert.equal(parseTopicId("42"), 42);
    assert.equal(parseTopicId("0"), undefined);
    assert.equal(parseTopicId("not-a-topic"), undefined);
    assert.equal(parseTopicId(null), undefined);
  });
});
