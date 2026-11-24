"use client";
import React from "react";
import { dashboardValue, useDashboardRepVersion } from "@/lib/dashboard-cache";
import Link from "next/link";
import { getApiBase, getRepresentativeCard, type TrackedLegislatorItem } from "@/lib/api";
import { getRepresentativeTopicActivity, type RepresentativeTopicActivity } from "@/lib/recommendations";
import { topRepresentativeTopics } from "@/lib/representative-card";
import LegislatorName from "./LegislatorName";
import RepresentativeCardResearch from "./RepresentativeCardResearch";
import { useDashboardLoading } from "./DashboardLoading";
import CardTooltip from "./CardTooltip";
import styles from "./tracked-legislators.module.css";
import { representativeInitials } from "@/lib/representative-name";

export function LegislatorCard({ representative: rep, facts, congress = null, renderName, children, activity, actions, headerAction }: {
  representative: Pick<TrackedLegislatorItem["representative"], "id" | "name" | "bioguide_id" | "chamber" | "state"> & Partial<TrackedLegislatorItem["representative"]>;
  facts?: TrackedLegislatorItem["card"];
  congress?: number | null;
  renderName?: (representative: { id: number; name: string; chamber: string }) => React.ReactNode;
  children?: React.ReactNode;
  activity?: RepresentativeTopicActivity;
  actions?: React.ReactNode;
  headerAction?: React.ReactNode;
}) {
  const [failedPhoto, setFailedPhoto] = React.useState("");
  const [loadedFacts, setLoadedFacts] = React.useState<TrackedLegislatorItem["card"]>();
  const [loadedActivity, setLoadedActivity] = React.useState<RepresentativeTopicActivity | null>(null);
  const [loadError, setLoadError] = React.useState(false);
  const [retry, setRetry] = React.useState(0);
  const version = useDashboardRepVersion();
  React.useEffect(() => {
    const controller = new AbortController();
    setLoadError(false);
    if (!facts) void dashboardValue(`rep:${rep.id}:card`, () => getRepresentativeCard(rep.id)).then(value => { if (!controller.signal.aborted) setLoadedFacts(value); }).catch(() => { if (!controller.signal.aborted) setLoadError(true); });
    if (!activity && !facts?.top_topics) void dashboardValue(`rep:${rep.id}:activity`, () => getRepresentativeTopicActivity(rep.id)).then(value => { if (!controller.signal.aborted) setLoadedActivity(value); }).catch(() => { if (!controller.signal.aborted) setLoadError(true); });
    return () => controller.abort();
  }, [rep.id, facts, activity, retry, version]);
  React.useEffect(() => { setLoadedFacts(undefined); }, [rep.id, facts]);
  const cardFacts = loadedFacts ?? facts;
  const rowId = React.useId();
  useDashboardLoading(rowId, !loadError && (!cardFacts || (!activity && !facts?.top_topics && !loadedActivity)));
  const topics = cardFacts?.top_topics ?? topRepresentativeTopics(activity ?? loadedActivity);
  const plainName = rep.name.replace(/^(Rep\.|Sen\.|Del\.|Resident Commissioner)\s*/i, "").replace(/\s*\[[^\]]*\]\s*$/, "");
  const name = rep.first_name && rep.last_name ? `${rep.first_name} ${rep.last_name}` : plainName.includes(",") ? plainName.split(",").slice(1).join(",").trim() + " " + plainName.split(",")[0].trim() : plainName;
  const partyCode = rep.party || rep.name.match(/\[([A-Z]+)-[A-Z]{2}(?:-\d+)?\]/)?.[1] || "";
  const party = /^(R|Republican)$/i.test(partyCode) ? "republican" : /^(D|Democrat|Democratic)$/i.test(partyCode) ? "democrat" : "other";
  const partyLabel = party === "republican" ? "Republican" : party === "democrat" ? "Democrat" : partyCode;
  const rawPhoto = cardFacts?.portrait?.url || rep.image_url || (/^[A-Z]\d{6}$/i.test(rep.bioguide_id) ? `https://www.congress.gov/img/member/${rep.bioguide_id.toLowerCase()}_200.jpg` : "");
  const photo = rawPhoto.startsWith(`/api/representatives/${rep.id}/portraits/`) ? getApiBase() + rawPhoto : /^https:\/\//.test(rawPhoto) ? rawPhoto : "";
  const bill = cardFacts?.latest_bill;
  return <article className={styles.card} data-party={party}>
    <header>
      <span className={styles.avatar}>{photo && photo !== failedPhoto ? <img src={photo} alt={name} onError={() => setFailedPhoto(photo)} /> : <span aria-hidden="true">{representativeInitials(rep.first_name && rep.last_name ? `${rep.first_name} ${rep.last_name}` : rep.name)}</span>}</span>
      <div><h3>{renderName ? renderName({ id: rep.id, name, chamber: rep.chamber }) : congress ? <LegislatorName id={rep.id} name={name} congress={congress} /> : <Link href={`/representatives/${rep.id}`}>{name}</Link>}</h3>
        <p>{[partyLabel, rep.state, rep.district ? `District ${rep.district}` : ""].filter(Boolean).join(" · ")}</p>
        <p>{rep.chamber === "senate" ? "Senate" : rep.chamber === "house" ? "House" : rep.chamber}</p>
      </div>
      {headerAction}
    </header>
    {cardFacts?.biography?.text && <p className={styles.bio}>{cardFacts.biography.text}</p>}
    <div className={styles.cardBottom}>
    {topics.length > 0 && <div className={styles.topics} aria-label="Top topics">{topics.map(topic => <CardTooltip key={topic.id} text="Recorded sponsorship and cosponsorship activity"><Link className={styles.pill} href={`/bills?topic_id=${topic.id}`}>{topic.name}</Link></CardTooltip>)}</div>}
    {(bill || children) && <div className={styles.contextRow}>
      {bill && <CardTooltip text={`Latest bill introduced: ${bill.title}`}><Link className={`${styles.pill} ${styles.latestBill}`} href={`/bills/${bill.id}`} aria-description={`Latest sponsored bill: ${bill.title}`}>{bill.bill_number}</Link></CardTooltip>}
      {children}
    </div>}
    {loadError && <button className={styles.retry} onClick={() => setRetry(value => value + 1)}>Retry card details</button>}
    <footer className={styles.cardFooter}>
      {actions && <div className={styles.cardActions}>{actions}</div>}
      <RepresentativeCardResearch id={rep.id} name={name} card={cardFacts} onCard={setLoadedFacts} />
    </footer>
    </div>
  </article>;
}

export default function TrackedLegislators({ items, congress }: { items: TrackedLegislatorItem[]; congress: number | null }) {
  return <section className={styles.section}><div className={styles.heading}><h2>Tracked legislators <small>{items.length}</small></h2><Link href="/representatives">Find representatives</Link></div>
    {items.length ? <div className={styles.row} role="region" aria-label="Tracked legislators" tabIndex={0}>{items.map(item => <LegislatorCard key={item.representative.id} representative={item.representative} facts={item.card} congress={congress} />)}</div> : <p>Track a representative to see them here.</p>}
  </section>;
}
