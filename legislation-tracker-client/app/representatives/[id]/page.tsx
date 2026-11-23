"use client";

import Link from "next/link";
import BillCard from "../../components/BillCard";
import BillDeckModal from "../../components/BillDeckModal";
import CardTooltip from "../../components/CardTooltip";
import { VotingRecord as VoteSummary } from "../../components/LegislatorProfileModal";
import { getRecordedVotes, safeSourceUrl, type ProfileScope, type VotesPage, type VoteFilters } from "@/lib/legislator-profile";
import { getRepresentativeTopicActivity, type RepresentativeTopicActivity } from "@/lib/recommendations";
import { topRepresentativeTopics } from "@/lib/representative-card";
import type { Research } from "@/lib/representative-research";
import deck from "../../components/bill-deck.module.css";
import styles from "./representative-page.module.css";
import RepresentativeResearch from "../../components/RepresentativeResearch";
import TrackRepresentativeButton from "../../components/TrackRepresentativeButton";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useUrlTab, representativeTabs, representativeTabKey } from "@/lib/use-url-tab";

import {
  getRepresentative,
  getTopics,
  type TopicItem,
  getBillFilterOptions,
  getRepresentativeCommittees,
  getRepresentativeCosponsoredBills,
  getRepresentativeSponsoredBills,
  type BillCosponsorItem,
  type BillListItem,
  type CommitteeMembershipItem,
  type RepresentativeItem,
} from "@/lib/api";

function BillRows({ bills }: { bills: BillListItem[] }) {
  const [selected, setSelected] = useState<BillListItem | null>(null);
  if (!bills.length) return <p className={styles.note}>No bills available.</p>;
  return <><div className={deck.followedRow} role="region" aria-label="Bill cards" tabIndex={0}>{bills.map(bill => <BillCard key={bill.id} bill={bill} onOpen={() => setSelected(bill)} footer={null} />)}</div>{selected && <BillDeckModal bill={selected} onClose={() => setSelected(null)} />}</>;
}

function FullVotes({ scope }: { scope: ProfileScope }) {
  const resultsViewport = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<NonNullable<VoteFilters["position"]> | "">("");
  const [topic, setTopic] = useState("");
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [topicsError, setTopicsError] = useState(false);
  const [topicsRetry, setTopicsRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setTopicsError(false);
    void getTopics().then(items => { if (active) setTopics(items); }).catch(() => { if (active) setTopicsError(true); });
    return () => { active = false; };
  }, [topicsRetry]);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<VotesPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(false);
    void getRecordedVotes(scope, page, controller.signal, { position: position || undefined, topicId: topic ? Number(topic) : undefined }).then(value => { if (!controller.signal.aborted) { setData(value); if (resultsViewport.current) resultsViewport.current.scrollTop = 0; } }).catch(() => { if (!controller.signal.aborted) setError(true); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [scope, page, retry, position, topic]);
  return <section className={styles.records}><h2>Voting record</h2>
    <div className={styles.voteFilters}>
      <label>Vote<select value={position} onChange={event => { setPosition(event.target.value as typeof position); setPage(1); setLoading(true); }}><option value="">All votes</option><option value="yes">Yes</option><option value="no">No</option><option value="no_vote">No vote</option></select></label>
      <label>Topic<select value={topic} onChange={event => { setTopic(event.target.value); setPage(1); setLoading(true); }}><option value="">All topics</option>{topics.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {topicsError && <button onClick={() => setTopicsRetry(value => value + 1)}>Retry topics</button>}
    </div>
    <div className={styles.voteStatus}>
      {loading && <span role="status" className={data ? "sr-only" : undefined}>Loading votes…</span>}
      {error && <span role="alert">Could not load votes. <button onClick={() => setRetry(value => value + 1)}>Retry votes</button></span>}
    </div>
    <div ref={resultsViewport} className={styles.voteViewport} role="region" aria-label="Voting results" tabIndex={0}>
    <ul aria-label="Vote results" aria-busy={loading} className={loading || error ? styles.pendingVotes : undefined}>{data?.results.map(record => <li key={record.id}>
      <span className={styles.position} data-position={record.position}>{({yes:"Yes",no:"No",present:"Present",not_voting:"Not voting",other:record.raw_position || "Other"})[record.position]}</span>
      <div>{record.bill ? <Link href={`/bills/${record.bill.id}`}>{record.bill.bill_number} · {record.bill.title}</Link> : <strong>{record.question || "Roll call"}</strong>}{record.bill && record.question && <p>{record.question}</p>}<small>{new Date(record.vote_date).toLocaleDateString("en-US", { timeZone: "UTC" })} · {record.chamber === "senate" ? "Senate" : "House"}</small></div>
      {safeSourceUrl(record.source_url) && <CardTooltip text={record.source_link_kind === "session_list" ? "Official session vote list" : "Official roll-call record"}><a href={record.source_url!} target="_blank" rel="noreferrer" aria-label="Vote source">↗</a></CardTooltip>}
    </li>)}</ul>
    {data && !data.results.length && !loading && <p className={styles.note}>No voting records available.</p>}
    </div>
    <nav className={styles.pagination} aria-label="Vote pages"><button disabled={loading || error || page === 1} onClick={() => setPage(value => value - 1)}>Prev</button><span>Page {page}</span><button disabled={loading || error || !data?.next} onClick={() => setPage(value => value + 1)}>Next</button></nav>
  </section>;
}

function RepresentativeDetailContent() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const representativeId = Number(params.id);
  const congressParam = searchParams.get("congress");
  const parsedCongress = congressParam === null ? null : Number(congressParam);
  const [defaultCongress, setDefaultCongress] = useState<number | null>(null);
  const congress = parsedCongress ?? defaultCongress;
  const valid = Number.isSafeInteger(representativeId) && representativeId > 0 && congress !== null && Number.isSafeInteger(congress) && congress > 0;
  const [research, setResearch] = useState<Research | null>(null);
  const [activity, setActivity] = useState<RepresentativeTopicActivity | null>(null);
  const [failedPortrait, setFailedPortrait] = useState("");
  const [tabKey, setTabKey] = useUrlTab<keyof typeof representativeTabs>(representativeTabs, "bills");
  const tab = representativeTabs[tabKey];
  const [opened, setOpened] = useState(["Bills"]);
  const tabs = ["Bills", "Votes", "Campaign funding", "Committees"];
  const chooseTab = (name: string) => { setTabKey(representativeTabKey(name)); };
  useEffect(() => { setOpened(previous => previous.includes(tab) ? previous : [...previous, tab]); }, [tab]);
  const scope = useMemo<ProfileScope>(() => ({ representativeId, congress: congress ?? 0 }), [representativeId, congress]);
  useEffect(() => {
    const controller = new AbortController();
    setResearch(null); setActivity(null);
    void getRepresentativeTopicActivity(representativeId, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setActivity(value); }).catch(() => {});
    return () => controller.abort();
  }, [representativeId]);
  const [representative, setRepresentative] = useState<RepresentativeItem | null>(null);
  const [sponsored, setSponsored] = useState<BillListItem[]>([]);
  const [cosponsored, setCosponsored] = useState<BillCosponsorItem[]>([]);
  const [committees, setCommittees] = useState<CommitteeMembershipItem[]>([]);
  const [historyPages, setHistoryPages] = useState({ sponsored: 1, cosponsored: 1, committees: 1 });
  const [historyHasMore, setHistoryHasMore] = useState({ sponsored: false, cosponsored: false, committees: false });
  const [historyLoading, setHistoryLoading] = useState({ sponsored: false, cosponsored: false, committees: false });
  const historyInFlight = useRef({ sponsored: false, cosponsored: false, committees: false });
  const historyGeneration = useRef({ sponsored: 0, cosponsored: 0, committees: 0 });
  const [billTopics, setBillTopics] = useState<TopicItem[]>([]);
  const [billTopicError, setBillTopicError] = useState(false);
  const [billTopicRetry, setBillTopicRetry] = useState(0);
  const [selectedTopics, setSelectedTopics] = useState({ sponsored: "", cosponsored: "" });
  const [billErrors, setBillErrors] = useState({ sponsored: false, cosponsored: false });
  useEffect(() => {
    let active = true;
    void getTopics().then(items => { if (active) { setBillTopics(items); setBillTopicError(false); } }).catch(() => { if (active) setBillTopicError(true); });
    return () => { active = false; };
  }, [billTopicRetry]);
  useEffect(() => () => {
    historyGeneration.current.sponsored++;
    historyGeneration.current.cosponsored++;
    historyGeneration.current.committees++;
  }, []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (congressParam !== null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getBillFilterOptions()
      .then((options) => {
        if (!cancelled) setDefaultCongress(options.current_congress);
      })
      .catch(() => {
        if (!cancelled) {
          setLoading(false);
          setError("Could not load the current Congress.");
        }
      });
    return () => { cancelled = true; };
  }, [congressParam, retry]);

  useEffect(() => {
    if (congress === null) return;
    if (!valid) {
      setLoading(false);
      setError("Invalid representative or Congress ID.");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getRepresentative(representativeId),
      getRepresentativeSponsoredBills(representativeId, congress, 1),
      getRepresentativeCosponsoredBills(representativeId, congress, 1),
      getRepresentativeCommittees(representativeId, congress, 1),
    ])
      .then(([person, sponsors, cosponsors, memberships]) => {
        if (cancelled) return;
        setRepresentative(person);
        historyGeneration.current.sponsored++;
        historyGeneration.current.cosponsored++;
        setSelectedTopics({ sponsored: "", cosponsored: "" });
        setBillErrors({ sponsored: false, cosponsored: false });
        setSponsored(sponsors.results);
        setCosponsored(cosponsors.results);
        setCommittees(memberships.results);
        setHistoryPages({ sponsored: 1, cosponsored: 1, committees: 1 });
        setHistoryHasMore({
          sponsored: Boolean(sponsors.next),
          cosponsored: Boolean(cosponsors.next),
          committees: Boolean(memberships.next),
        });
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load representative details.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [congress, representativeId, retry, valid]);

  async function loadMoreHistory(
    kind: "sponsored" | "cosponsored" | "committees",
  ) {
    if (congress === null || historyInFlight.current[kind]) return;
    historyInFlight.current[kind] = true;
    const generation = historyGeneration.current[kind];
    setHistoryLoading((current) => ({ ...current, [kind]: true }));
    const nextPage = historyPages[kind] + 1;
    try {
      if (kind === "sponsored") {
        const response = await getRepresentativeSponsoredBills(
          representativeId,
          congress,
          nextPage,
          Number(selectedTopics.sponsored) || undefined,
        );
        if (generation !== historyGeneration.current[kind]) return;
        setSponsored((current) => [...current, ...response.results]);
        setHistoryHasMore((current) => ({ ...current, sponsored: Boolean(response.next) }));
      } else if (kind === "cosponsored") {
        const response = await getRepresentativeCosponsoredBills(
          representativeId,
          congress,
          nextPage,
          Number(selectedTopics.cosponsored) || undefined,
        );
        if (generation !== historyGeneration.current[kind]) return;
        setCosponsored((current) => [...current, ...response.results]);
        setHistoryHasMore((current) => ({ ...current, cosponsored: Boolean(response.next) }));
      } else {
        const response = await getRepresentativeCommittees(
          representativeId,
          congress,
          nextPage,
        );
        if (generation !== historyGeneration.current[kind]) return;
        setCommittees((current) => [...current, ...response.results]);
        setHistoryHasMore((current) => ({ ...current, committees: Boolean(response.next) }));
      }
      setHistoryPages((current) => ({ ...current, [kind]: nextPage }));
    } catch (cause) {
      if (generation !== historyGeneration.current[kind]) return;
      setError(cause instanceof Error ? cause.message : "Could not load more history.");
    } finally {
      if (generation === historyGeneration.current[kind]) {
        historyInFlight.current[kind] = false;
        setHistoryLoading((current) => ({ ...current, [kind]: false }));
      }
    }
  }

  async function filterBills(kind: "sponsored" | "cosponsored", topic: string) {
    if (congress === null) return;
    const generation = ++historyGeneration.current[kind];
    setSelectedTopics(current => ({ ...current, [kind]: topic }));
    setBillErrors(current => ({ ...current, [kind]: false }));
    historyInFlight.current[kind] = true;
    setHistoryLoading(current => ({ ...current, [kind]: true }));
    try {
      let next: string | null;
      if (kind === "sponsored") {
        const response = await getRepresentativeSponsoredBills(representativeId, congress, 1, Number(topic) || undefined);
        if (generation !== historyGeneration.current[kind]) return;
        setSponsored(response.results); next = response.next;
      } else {
        const response = await getRepresentativeCosponsoredBills(representativeId, congress, 1, Number(topic) || undefined);
        if (generation !== historyGeneration.current[kind]) return;
        setCosponsored(response.results); next = response.next;
      }
      setHistoryPages(current => ({ ...current, [kind]: 1 }));
      setHistoryHasMore(current => ({ ...current, [kind]: Boolean(next) }));
    } catch {
      if (generation === historyGeneration.current[kind]) setBillErrors(current => ({ ...current, [kind]: true }));
    } finally {
      if (generation === historyGeneration.current[kind]) {
        historyInFlight.current[kind] = false;
        setHistoryLoading(current => ({ ...current, [kind]: false }));
      }
    }
  }

  const activeCosponsoredBills = useMemo(
    () => cosponsored.filter((item) => item.withdrawn_at === null),
    [cosponsored],
  );

  const name = (representative?.name ?? "").replace(/^(Rep\.|Sen\.)\s*/, "").replace(/\s*\[.*\]$/, "").replace(/^([^,]+),\s*(.+)$/, "$2 $1");
  const portrait = research?.portrait?.url || representative?.image_url;
  return <main className={styles.page}>
    {loading && <p role="status">Loading representative…</p>}
    {error && <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {!loading && representative && <>
      <header className={styles.header}>
        <div className={styles.avatar}>{portrait && portrait !== failedPortrait ? <img src={portrait} alt={name} onError={() => setFailedPortrait(portrait)} /> : <span>{name.split(" ").map(part => part[0]).slice(0, 2).join("")}</span>}</div>
        <div><h1>{name}</h1><div className={styles.badges}><span>{({D:"Democrat",R:"Republican",I:"Independent"} as Record<string,string>)[representative.party] || representative.party}</span><span>{representative.state}{representative.district ? ` · District ${representative.district}` : ""}</span><span>{representative.chamber === "senate" ? "Senate" : "House"}</span></div></div>
        <div className={styles.actions}>
          <TrackRepresentativeButton key={representative.id} representativeId={representative.id} />
          <RepresentativeResearch representativeId={representative.id} cardName={name} onResearch={setResearch} />
        </div>
      </header>
      {research?.biography && <p className={styles.bio}>{research.biography.text}</p>}
      <div className={styles.topics}>{topRepresentativeTopics(activity).map(topic => <Link key={topic.id} href={`/bills?topic_id=${topic.id}`}>{topic.name}</Link>)}</div>
      <div className={styles.tabBar}><div role="tablist" aria-label="Representative information">{tabs.map((name,index) => <button key={name} id={`representative-tab-${index}`} role="tab" aria-selected={tab === name} aria-controls={`representative-panel-${index}`} tabIndex={tab === name ? 0 : -1} onClick={() => chooseTab(name)} onKeyDown={event => {
        const next = event.key === "ArrowRight" ? (index+1)%tabs.length : event.key === "ArrowLeft" ? (index+tabs.length-1)%tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length-1 : null;
        if (next !== null) { event.preventDefault(); chooseTab(tabs[next]); document.getElementById(`representative-tab-${next}`)?.focus(); }
      }}>{name}</button>)}</div><span>Congress {congress}</span></div>
      {tabs.map((name,index) => (opened.includes(name) || tab === name) && <div key={name} id={`representative-panel-${index}`} role="tabpanel" aria-labelledby={`representative-tab-${index}`} hidden={tab !== name} className={styles.panel}>
        {name === "Bills" && <>
          {billTopicError && <button onClick={() => setBillTopicRetry(value => value + 1)}>Retry topics</button>}
          {(["sponsored", "cosponsored"] as const).map(kind => {
            const title = kind === "sponsored" ? "Bills introduced" : "Bills cosponsored";
            return <section key={kind}>
              <div className={styles.billHistoryToolbar}><h2>{title}</h2><select aria-label={`${title} topic`} value={selectedTopics[kind]} onChange={event => void filterBills(kind, event.target.value)}><option value="">All topics</option>{billTopics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select></div>
              <div className={styles.billHistoryResults} aria-busy={historyLoading[kind]} style={{ opacity: historyLoading[kind] || billErrors[kind] ? 0.55 : 1 }}><BillRows bills={kind === "sponsored" ? sponsored : activeCosponsoredBills.map(item => item.bill)} /></div>
              {billErrors[kind] && <p role="alert">Could not load bills. <button onClick={() => void filterBills(kind, selectedTopics[kind])}>Retry</button></p>}
              {historyHasMore[kind] && <div className={styles.pagination}><button disabled={historyLoading[kind] || billErrors[kind]} onClick={() => void loadMoreHistory(kind)}>Load more {kind} bills</button></div>}
            </section>;
          })}
        </>}
        {name === "Votes" && <><VoteSummary scope={scope} fullPage /><FullVotes scope={scope} /></>}
        {name === "Campaign funding" && <RepresentativeResearch key={searchParams.get("period") ?? "current"} representativeId={representative.id} initialPeriod={searchParams.get("period")} financeView />}
        {name === "Committees" && <section><h2>Committees</h2>{committees.length ? <ul className={styles.committees}>{committees.map(membership => <li key={`${membership.committee.id}-${membership.congress}`}><strong>{membership.committee.name}</strong><span>{membership.role.replaceAll("_", " ")}{!membership.is_current ? " · Former" : ""}</span></li>)}</ul> : <p className={styles.note}>No committee assignments available.</p>}{historyHasMore.committees && <div className={styles.pagination}><button disabled={historyLoading.committees} onClick={() => void loadMoreHistory("committees")}>Load more committees</button></div>}</section>}
      </div>)}
    </>}
  </main>;
}

function ScopedRepresentativeDetail() {
  const params = useParams<{ id: string }>();
  const query = useSearchParams();
  return <RepresentativeDetailContent key={`${params.id}:${query.get("congress") ?? ""}`} />;
}

export default function RepresentativeDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center font-sans text-slate-600 dark:text-green-500">
          Loading representative…
        </div>
      }
    >
      <ScopedRepresentativeDetail />
    </Suspense>
  );
}
