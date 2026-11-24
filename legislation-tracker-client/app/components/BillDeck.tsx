"use client";
import { Dropdown, SearchInput } from "@/app/components/FilterControls";
import DashboardLoading from "./DashboardLoading";

import Link from "next/link";
import React from "react";
import type { BillListItem } from "@/lib/api";
import BillDeckModal from "./BillDeckModal";
import IngestionTelemetryLive from "./IngestionTelemetryLive";
import RecommendationsPreview from "./RecommendationsPreview";
import { focusRecommendationFallback } from "@/lib/recommendation-focus";
import LegislatorName from "./LegislatorName";
import TrackedLegislators from "./TrackedLegislators";
import styles from "./bill-deck.module.css";

import DashboardBillCard, { useDashboardBillTracking } from "./DashboardBillCard";
import { readable } from "./BillCard";
import { STAGES, stageFor } from "@/lib/bill-stage";
export { topicColor, readable, dateLabel } from "./BillCard";

export default function BillDeck() {
  const [query, setQuery] = React.useState("");
  const [recommendationQuery, setRecommendationQuery] = React.useState("");
  React.useEffect(() => {
    const timer = setTimeout(() => setRecommendationQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);
  const [topic, setTopic] = React.useState("");
  const [sponsor, setSponsor] = React.useState("");
  const [state, setState] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [sort, setSort] = React.useState("recent");
  const [selected, setSelected] = React.useState<BillListItem | null>(null);
  const [selectedFromRecommendations, setSelectedFromRecommendations] = React.useState(false);
  const closeBill = React.useCallback(() => setSelected(null), []);
  const controls = useDashboardBillTracking(closeBill);
  const { tracking, signedIn, ready, error, followError, currentCongress, isSuperuser } = controls;
  const recommendationOwnsBill = React.useRef(false);
  const dismissRecommendedBill = React.useCallback(() => {
    if (recommendationOwnsBill.current) { recommendationOwnsBill.current = false; setSelected(null); }
  }, []);
  const source = tracking?.bills.map(item => item.bill) ?? [];
  const topics = new Map<number, string>();
  tracking?.topics.forEach(item => topics.set(item.topic.id, item.topic.name));
  source.forEach(bill => bill.topics.forEach(item => topics.set(item.topic_id, item.name)));
  const sponsorKey = (bill: BillListItem) => bill.sponsor_id ? `id:${bill.sponsor_id}` : `unidentified:${bill.sponsor_name ?? ""}`;
  const sponsors = [...new Map(source.filter(bill => bill.sponsor_name).map(bill => [sponsorKey(bill), bill.sponsor_name!])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const presentStages = new Set(source.map(bill => stageFor(bill.status)?.key));
  const stageOptions = STAGES.filter(item => presentStages.has(item.key));
  const statuses = [...new Set(source.map(bill => bill.status).filter(value => value && !stageFor(value)))].sort();
  const stateBySponsor = new Map(source.map(bill => [bill.sponsor_id ?? -1, bill.sponsor_state ?? undefined]));
  const states = [...new Set(source.map(bill => stateBySponsor.get(bill.sponsor_id ?? -1)).filter((value): value is string => Boolean(value)))].sort();
  const visible = source.filter(bill => (!query || `${bill.bill_number} ${bill.title}`.toLowerCase().includes(query.toLowerCase())) && (!topic || bill.topics.some(item => String(item.topic_id) === topic)) && (!sponsor || sponsorKey(bill) === sponsor) && (!state || stateBySponsor.get(bill.sponsor_id ?? -1) === state) && (!status || (stageFor(bill.status)?.key ?? `raw:${bill.status}`) === status));
  visible.sort((a, b) => {
    if (sort === "title") return a.title.localeCompare(b.title) || a.id - b.id;
    if (sort === "number") return a.bill_number.localeCompare(b.bill_number, undefined, { numeric: true }) || b.session - a.session || a.id - b.id;
    const dateA = Date.parse(a.last_action_at ?? ""), dateB = Date.parse(b.last_action_at ?? "");
    if (!Number.isFinite(dateA)) return Number.isFinite(dateB) ? 1 : a.id - b.id;
    if (!Number.isFinite(dateB)) return -1;
    return (sort === "oldest" ? dateA - dateB : dateB - dateA) || a.id - b.id;
  });
  return <div className={styles.deck}>
    <header className={styles.heading}>
      <h1 data-dashboard-heading tabIndex={-1}>Follow the bills that matter to you.</h1>
    </header>
    <div className={styles.filters}>
      <label>Search bills<SearchInput placeholder="Title or bill number" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label>Topic<Dropdown aria-label="Topic" value={topic} onChange={event => setTopic(event.target.value)}><option value="">All topics</option>{[...topics].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</Dropdown></label>
      <label>Representative (sponsor)<Dropdown aria-label="Representative (sponsor)" value={sponsor} onChange={event => setSponsor(event.target.value)}><option value="">All sponsors</option>{sponsors.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</Dropdown></label>
      <label>Sponsor state<Dropdown aria-label="Sponsor state" value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{states.map(value => <option key={value}>{value}</option>)}</Dropdown></label>
      <label>Status<Dropdown aria-label="Status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{stageOptions.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}{statuses.map(value => <option key={value} value={`raw:${value}`}>{readable(value)}</option>)}</Dropdown></label>
      <label>Sort bills<Dropdown value={sort} onChange={event => setSort(event.target.value)}><option value="recent">Latest action first</option><option value="oldest">Oldest action first</option><option value="title">Title A–Z</option><option value="number">Bill number</option></Dropdown></label>
    </div>
    <div className="min-h-6 text-sm text-red-700" aria-live="polite">{error && <span role="alert">{error} <button onClick={controls.retry}>Retry</button></span>}</div>
    {followError && <p role="alert">{followError}</p>}
    <DashboardLoading loading={!ready}>
    {ready && !signedIn && !error && <div className={styles.empty}><h2>Start your collection</h2><p><Link href="/login">Log in</Link> to follow bills, or browse the <Link href="/bills">Bills page</Link>.</p></div>}
    {ready && !error && signedIn && !visible.length && <div className={styles.empty}><h2>{source.length ? "No bills match these filters" : "Your collection starts with a bill"}</h2><p>{source.length ? "Clear a filter to see more legislation." : <>Browse the <Link href="/bills">Bills page</Link> and follow a bill to keep it here.</>}</p>{!tracking?.topics.length && <p>Follow topics to organize your collection around your interests.</p>}</div>}
    {visible.length > 0 && <section className={styles.topicSection}>
      <h2>Following<small>{visible.length}</small></h2>
      <div role="region" aria-label="Followed bills" tabIndex={0} className={styles.followedRow}>{visible.map(bill => <DashboardBillCard key={bill.id} bill={bill} controls={controls}
        accentTopicId={bill.topics.find(item => tracking?.topics.some(follow => follow.topic.id === item.topic_id))?.topic_id}
        sponsorState={stateBySponsor.get(bill.sponsor_id ?? -1)}
        onOpen={currentBill => { recommendationOwnsBill.current = false; setSelectedFromRecommendations(false); setSelected(currentBill); }}
      />)}</div>
    </section>}
    {tracking && <TrackedLegislators items={tracking.legislators} congress={currentCongress} />}
    <RecommendationsPreview filters={{q: recommendationQuery, topic_id: topic, sponsor, state, status, sort}} renderName={currentCongress === null ? undefined : ({ id, name, chamber }) => <LegislatorName id={id} name={name} congress={currentCongress} chamber={chamber === "house" || chamber === "senate" ? chamber : undefined} />} onOpenBill={bill => { recommendationOwnsBill.current = true; setSelectedFromRecommendations(true); setSelected(bill); return true; }} onDismissBill={dismissRecommendedBill} />
    {ready && signedIn && isSuperuser && <IngestionTelemetryLive />}
    </DashboardLoading>
    {selected && <BillDeckModal {...(selectedFromRecommendations ? { fallbackFocus: focusRecommendationFallback } : {})} bill={selected} onClose={() => { recommendationOwnsBill.current = false; setSelected(null); }} />}
  </div>;
}
