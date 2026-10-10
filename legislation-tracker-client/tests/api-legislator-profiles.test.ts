import assert from "node:assert/strict";
import { afterEach, it } from "node:test";
import { getIntroducedBills, getLegislatorBiography, getLegislatorProfile, getRecordedVotes, profileHref, safeSourceUrl } from "../lib/legislator-profile.ts";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const scope = { representativeId: 1, congress: 119 };
const coverage = { scope: { congress: 119, chamber: null }, stored_record_count: 0, member_position_completeness: "unknown", unknown_session_record_count: 0, provider_scopes: [], legacy_ingestion_check: { scopes: [], coverage_complete: false, reason: null, discovered_count: 0, persisted_count: 0, notice: "Unverified member completeness" } };
const fact = { status: "unavailable", value: null, precision: null, reason: "unverified", source_url: null, retrieved_at: null };
const profile = { schema_version: "legislator-profile-v1", scope: { congress: 119, chamber: null }, identity: { id: 1, bioguide_id: "S000033", name: "Member", is_current: true, latest_affiliation: { chamber: "senate", state: "VT", party: "Independent", district: null }, last_seen_at: null, source_url: null }, service: { status: "unavailable", precision: "year", observations: [], notice: "Service unavailable" }, elections: [{ chamber: null, first_elected: fact, most_recent_election_won: fact, term_start: fact }], donors: { status: "unavailable", reason: "not_connected", cycle: null, reporting_period: null, currency: null, source_url: null, methodology: null, donors: [] }, coverage };

it("allows only public source hosts/paths and never forwards credentials or pagination URLs", async () => {
  for (const unsafe of ["javascript:alert(1)", "http://en.wikipedia.org/wiki/Member", "https://en.wikipedia.org.evil.test/wiki/Member", "https://user:password@en.wikipedia.org/wiki/Member", "https://api.congress.gov/v3/bill/119/hr/1?api_key=secret", "https://clerk.house.gov/Votes/20251?tracking=secret", "https://www.senate.gov:8443/legislative/votes_new.htm"]) assert.equal(safeSourceUrl(unsafe), null);
  assert.equal(safeSourceUrl("https://clerk.house.gov/Votes/20251"), "https://clerk.house.gov/Votes/20251");
  const controller = new AbortController();
  const requests: {url:string;options?:RequestInit}[] = [];
  globalThis.fetch = async (url, options) => { requests.push({url:String(url), options}); return Response.json({ count: 0, next: "https://evil.test/steal", previous: null, results: [] }); };
  await getIntroducedBills(scope, 1, controller.signal);
  await getIntroducedBills(scope, 2, controller.signal);
  assert.match(requests[1].url, /\/api\/representatives\/1\/sponsored-bills\/\?congress=119&page=2$/);
  assert.equal(requests[0].options?.signal, controller.signal);
  assert.notEqual(requests[0].options?.credentials, "include");
  assert.equal(requests[0].options?.headers, undefined);
});

it("rejects wrong legislator/scope and malformed DTOs without turning gaps into zero facts", async () => {
  globalThis.fetch = async () => Response.json(profile);
  assert.equal((await getLegislatorProfile(scope)).elections[0].first_elected.value, null);
  globalThis.fetch = async () => Response.json({ ...profile, identity: { ...profile.identity, id: 2 } });
  await assert.rejects(getLegislatorProfile(scope), /Invalid legislator/);
  globalThis.fetch = async () => Response.json({ ...profile, scope: { congress: 118, chamber: null } });
  await assert.rejects(getLegislatorProfile(scope), /Invalid legislator/);
  globalThis.fetch = async () => Response.json({ status: "available", text: "Unverified generated text" });
  await assert.rejects(getLegislatorBiography(scope), /Invalid biography/);
  globalThis.fetch = async () => Response.json({ count: 0, next: null, previous: null, results: [], pagination_mode: "complete_history", coverage, page_read_at: "bad date" });
  await assert.rejects(getRecordedVotes(scope, 1), /Invalid voting-record/);
});

it("validates scope and page before network access", async () => {
  globalThis.fetch = async () => { throw new Error("Unexpected fetch"); };
  assert.equal(profileHref({ ...scope, chamber: "house" }), "/representatives/1?congress=119&chamber=house");
  assert.throws(() => profileHref({ ...scope, congress: 0 }), /Invalid legislator scope/);
  await assert.rejects(getIntroducedBills(scope, 0), /Invalid page/);
  await assert.rejects(getRecordedVotes(scope, 1.5), /Invalid page/);
});
