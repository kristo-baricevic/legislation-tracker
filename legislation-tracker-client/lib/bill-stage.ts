// Where a bill is on its path to becoming law, in plain words.
//
// Bill.status is not a controlled vocabulary. In production it is the latest
// Congress.gov action sentence cut to 100 characters ("Referred to the House
// Committee on Energy and Commerce."); fixtures use short codes ("passed_house").
// stageFor() reads either and returns null when it cannot tell, so callers can
// fall back to showing the original text instead of guessing.

export type StageKey = "introduced" | "committee" | "first_chamber" | "both_chambers" | "law";

export const STAGES: ReadonlyArray<{ key: StageKey; name: string }> = [
  { key: "introduced", name: "Introduced" },
  { key: "committee", name: "In committee" },
  { key: "first_chamber", name: "Passed one chamber" },
  { key: "both_chambers", name: "Passed both chambers" },
  { key: "law", name: "Became law" },
];

export type BillStage = {
  key: StageKey;
  /** 0-based position in STAGES. */
  index: number;
  /** Specific wording for this bill, e.g. "Passed the House". */
  label: string;
};

function stage(key: StageKey, label: string): BillStage {
  return { key, index: STAGES.findIndex(item => item.key === key), label };
}

export function stageFor(status: string | null | undefined): BillStage | null {
  const text = (status ?? "").replaceAll("_", " ").toLowerCase().trim();
  if (!text) return null;

  if (/became (public|private) law|signed by president|^enacted\b|^law$/.test(text)) return stage("law", "Became law");
  if (/^(?:motion|not passed)\b|\b(?:failed|rejected)\b/.test(text)) return null;
  if (/^vetoed\b/.test(text)) return stage("both_chambers", "Vetoed by the President");
  if (/^(?:presented|sent) to (?:the )?president/.test(text)) return stage("both_chambers", "Sent to the President");
  if (/^enrolled\b/.test(text)) return stage("both_chambers", "Passed both chambers");

  // A bill "received in" a chamber has passed the other one.
  const received = text.match(/received in the (house|senate)/);
  if (received) return stage("first_chamber", received[1] === "senate" ? "Passed the House" : "Passed the Senate");
  const passed = text.match(/(?:passed|agreed to)(?: house| senate)?(?:\/agreed to)? in (?:the )?(house|senate)|passed (?:the )?(house|senate)|engrossed/);
  if (passed) {
    const chamber = passed[1] ?? passed[2];
    return stage("first_chamber", chamber ? `Passed the ${chamber === "house" ? "House" : "Senate"}` : "Passed one chamber");
  }

  if (/reported|ordered to be reported|placed on .*calendar/.test(text)) return stage("committee", "Reported out of committee");
  if (/committee|markup|hearing|discharge|referred to/.test(text)) return stage("committee", "In committee");
  if (/^introduced|introduced in|sponsor introductory/.test(text)) return stage("introduced", "Introduced");
  return null;
}
