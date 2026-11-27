import type {Page} from "@playwright/test";
const fact = { status: "unavailable", value: null, precision: null, reason: "unverified", source_url: null, retrieved_at: null };
const coverage = { scope: { congress: 119, chamber: null }, stored_record_count: 1, unknown_session_record_count: 0, member_position_completeness: "unknown", provider_scopes: [], legacy_ingestion_check: { scopes: [], coverage_complete: false, reason: "No service history", discovered_count: 0, persisted_count: 0, notice: "Member completeness unknown" } };
export const bill = { id: 10, bill_number: "HR 5", session: 119, title: "Original bill", jurisdiction: "federal", status: "introduced", sponsor_id: 1, sponsor_bioguide_id: "S000033", sponsor_name: "Same Name", introduced_at: "2025-01-09", last_action_at: null, topics: [] };
const second = { ...bill, id: 11, title: "Another introduced bill" };
const profile = { schema_version: "legislator-profile-v1", scope: { congress: 119, chamber: null }, identity: { id: 1, bioguide_id: "S000033", name: "Same Name", is_current: true, latest_affiliation: { chamber: "senate", party: "Independent", state: "VT", district: null }, last_seen_at: null, source_url: null }, service: { status: "available", precision: "year", observations: [{ id: 1, chamber: "house", state: "VT", district: "1", start_year: 2023, end_year: 2027, source_url: null, retrieved_at: null }], notice: "Stored years; exact dates unverified." }, elections: [{ chamber: "house", first_elected: fact, most_recent_election_won: fact, term_start: fact }], donors: { status: "unavailable", reason: "source_not_connected", cycle: null, reporting_period: null, currency: null, source_url: null, methodology: null, donors: [] }, coverage };
const bio = { status: "available", text: "<script>unsafe()</script> A factual source excerpt.", reason: null, wikidata_id: "Q359442", page_id: 361176, observed_revision_id: 1378464460, observed_revision_at: "2026-10-04T16:55:30Z", page_url: "https://en.wikipedia.org/wiki/Bernie_Sanders", observed_revision_url: "https://en.wikipedia.org/w/index.php?oldid=1378464460", fetched_at: "2026-10-10T00:00:00Z", shortened: true, attribution: "Wikipedia contributors", license: "CC BY-SA 4.0", license_url: "https://creativecommons.org/licenses/by-sa/4.0/" };
const vote = { id: 1, representative_id: 1, vote_id: 1, congress: 119, chamber: "house", session_number: 1, roll_number: 1, vote_date: "2025-01-09T19:00:00Z", question: "On passage", position: "not_voting", raw_position: "Not Voting", bill: second, source_url: "https://clerk.house.gov/Votes/20251", source_link_kind: "roll_call", source_updated_at: null };

export async function fixtures(page: Page) {
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    let value: unknown = {};
    if (path === "/api/auth/session/current/") value = { authenticated: true,user:{email:"fixture@example.test"},current_congress:119 };
    else if (path.includes("recommendations/")) value = {results:[],next_cursor:null,count:0,empty_reason:"no_matches",unsupported_follow_types:[]};
    else if (path === "/api/tracking/") value = { bills: [{id:1,bill}], topics: [], legislators: [], is_staff: false };
    else if (path === "/api/representatives/") value = { count: 2, next: null, previous: null, results: [{ id: 1, bioguide_id: "S000033", name: "Same Name", state: "VT", chamber: "senate", party: "Independent", district: null }, { id: 2, bioguide_id: "I000002", name: "Same Name", state: "NY", chamber: "house", party: "Other", district: "1" }] };
    else if (path === "/api/bills/filter-options/") value = { jurisdictions: ["federal"], current_congress: 119 };
    else if (path === "/api/topics/") value = [];
    else if (path === "/api/bills/") value = { count: 1, next: null, previous: null, results: [bill] };
    else if (/\/api\/bills\/1[01]\/$/.test(path)) value = { ...(path.includes("/11/") ? second : bill), sponsor:1, summary_preview:"Stored official summary", summary_has_more:false, summary_source:"source_metadata", summary_version_code:null, summary_action_date:null, summary_last_updated_at:null, processing_status:"complete", source_api_id:null, congress_gov_url:null, created_at:"2026-01-01", updated_at:"2026-01-01", documents:[],latest_contract:null };
    else if (path.endsWith("/profile/")) value = path.includes("/2/") ? { ...profile, identity: { ...profile.identity, id: 2, bioguide_id: "I000002" } } : profile;
    else if (path.endsWith("/research/")) value = {status:"succeeded", period:2026, run:null, snapshot:null, portrait:null, biography:{text:bio.text,source:{url:bio.observed_revision_url,attribution:bio.attribution}}};
    else if (path.endsWith("/vote-summary/")) value = {scope:{congress:119,chamber:url.searchParams.get("chamber")},totals:{yes:1,no:0,present:0,not_voting:1,other:0},topics:[{id:1,name:"Health",yes:1,no:0}]};
    else if (path.endsWith("/biography/")) value = bio;
    else if (path.endsWith("/sponsored-bills/")) value = { count: 2, previous: url.searchParams.get("page") === "2" ? "?page=1" : null, next: url.searchParams.get("page") === "2" ? null : "https://untrusted.invalid/?page=2", results: [url.searchParams.get("page") === "2" ? bill : second] };
    else if (path.endsWith("/voting-record/")) value = { count: 1, next: null, previous: null, results: [vote], coverage, pagination_mode: "live_pages", page_read_at: "2026-10-10T00:00:00Z" };
    if (path.endsWith("/topic-activity/")) { await route.fulfill({status: 503, json: {detail: "fixture activity unavailable"}}); return; }
    await route.fulfill({ json: value });
  });
}

