import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { stageFor, STAGES } from "../lib/bill-stage.ts";
import { ordinal, topicColor, TOPIC_COLOR_COUNT } from "../lib/bill-format.ts";

const cases: Array<[string, string, string]> = [
  // Congress.gov latest-action sentences
  ["Introduced in House", "introduced", "Introduced"],
  ["Referred to the House Committee on Energy and Commerce.", "committee", "In committee"],
  ["Referred to the Subcommittee on Health.", "committee", "In committee"],
  ["Committee on Ways and Means. Ordered to be Reported.", "committee", "Reported out of committee"],
  ["Placed on the Union Calendar, Calendar No. 12.", "committee", "Reported out of committee"],
  ["Passed/agreed to in House: On passage Passed by the Yeas and Nays: 220 - 207.", "first_chamber", "Passed the House"],
  ["Passed Senate with an amendment by Yea-Nay Vote. 51 - 49.", "first_chamber", "Passed the Senate"],
  ["Received in the Senate and Read twice and referred to the Committee on Finance.", "first_chamber", "Passed the House"],
  ["Received in the House.", "first_chamber", "Passed the Senate"],
  ["Presented to President.", "both_chambers", "Sent to the President"],
  ["Vetoed by President.", "both_chambers", "Vetoed by the President"],
  ["Became Public Law No: 119-12.", "law", "Became law"],
  ["Signed by President.", "law", "Became law"],
  // short codes used by fixtures
  ["introduced", "introduced", "Introduced"],
  ["Introduced", "introduced", "Introduced"],
  ["passed_house", "first_chamber", "Passed the House"],
  ["Reported", "committee", "Reported out of committee"],
];

describe("stageFor", () => {
  for (const [input, key, label] of cases) {
    it(`reads "${input}"`, () => {
      const result = stageFor(input);
      assert.equal(result?.key, key);
      assert.equal(result?.label, label);
      assert.equal(STAGES[result!.index].key, key);
    });
  }

  it("returns null instead of guessing", () => {
    for (const value of ["", "pending", "unavailable", "Status unavailable", null, undefined]) {
      assert.equal(stageFor(value), null);
    }
  });

  it("does not mistake failed motions or presidential communications for bill progress", () => {
    for (const value of ["Motion to override veto failed in House", "Not passed House", "Message from the White House received", "Motion to discharge committee rejected"]) {
      assert.equal(stageFor(value), null, value);
    }
    assert.equal(stageFor("Enrolled bill")?.label, "Passed both chambers");
  });
});

describe("format helpers", () => {
  it("formats ordinals", () => {
    assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 101, 112, 119].map(ordinal), ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "101st", "112th", "119th"]);
  });
  it("gives a topic the same colour every time and stays inside the palette", () => {
    assert.equal(topicColor(7), topicColor(7));
    assert.equal(topicColor(3), "var(--topic-3)");
    assert.equal(topicColor(3 + TOPIC_COLOR_COUNT), topicColor(3));
    assert.equal(topicColor(-4), "var(--topic-4)");
  });
});
