"use client";
import React, { useEffect, useRef, useState } from "react";
import { getConnections, type Connections } from "@/lib/representative-research";
import styles from "./representative-research.module.css";

const money = (amount: string) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(Number(amount));
function Evidence({ url }: { url: string }) {
  return /^https:\/\//.test(url) ? <a href={url} target="_blank" rel="noreferrer">FEC records ↗</a> : null;
}

export default function ContributorExplorer({ representativeId, period, refreshToken }: { representativeId: number; period: number; refreshToken?: string }) {
  const [data, setData] = useState<Connections | null>(null);
  const [donor, setDonor] = useState<{ id: number; name: string }>();
  const [member, setMember] = useState<{ id: number; name: string; snapshot?: string }>();
  const [donorPage, setDonorPage] = useState(0), [memberPage, setMemberPage] = useState(0);
  const [retry, setRetry] = useState(0), [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const loadedScope = useRef("");
  useEffect(() => {
    const controller = new AbortController();
    const scope = JSON.stringify([representativeId, period, donor?.id, donorPage, memberPage]);
    setLoading(loadedScope.current !== scope); setError("");
    getConnections(representativeId, period, 0, controller.signal, donor?.id, donorPage, memberPage)
      .then(result => { if (!controller.signal.aborted) { loadedScope.current = scope; setData(result); } })
      .catch(() => { if (!controller.signal.aborted) setError("Could not load campaign connections."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [representativeId, period, donor?.id, donorPage, memberPage, retry, refreshToken]);
  return <section className={styles.explorer} aria-label="Campaign connections">
    <h3>Follow the contributions</h3>
    <p className={styles.note}>Choose a contributor to see which researched campaigns received money. Contributions do not establish support for a bill or topic.</p>
    {error && <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry connections</button></p>}
    {loading && <p role="status">Loading connections…</p>}
    {data?.finance_status === "collecting" && <p className={styles.note}>Partial connections — donor records are still being collected. Amounts and rankings may change.</p>}
    {!loading && data && !data.donors.length && <p>{data.finance_status === "not_researched" ? "No campaign contribution data has been saved yet." : "No verified committee contributors are available for this reporting period."}</p>}
    {data && data.donors.length > 0 && <>
      <div className={styles.explorerHeader}><h4>Committee contributors</h4><small>{period - 1}–{period} · {data.donor_count} contributors · {data.finance_status} coverage</small></div>
      <ul className={styles.explorerRows}>{data.donors.map(item => <li key={item.id}>
        <button disabled={loading} aria-pressed={donor?.id === item.id} onClick={() => { setDonor({ id: item.id, name: item.name }); setMember(undefined); setMemberPage(0); }}>{item.name}</button>
        <strong>{money(item.amount)}</strong><Evidence url={item.source_url} />
      </li>)}</ul>
      <nav className={styles.controls} aria-label="Contributor connections pages"><span>{data.donor_count ? `${donorPage + 1}–${Math.min(donorPage + data.donors.length, data.donor_count)} of ${data.donor_count} committee contributors` : "0 committee contributors"}</span>{(donorPage > 0 || data.next_donor_cursor != null) && <><button disabled={loading || !donorPage} onClick={() => { setDonorPage(Math.max(0, donorPage - 20)); setDonor(undefined); setMember(undefined); }}>Prev</button><button disabled={loading || data.next_donor_cursor == null} onClick={() => { setDonorPage(data.next_donor_cursor!); setDonor(undefined); setMember(undefined); }}>Next</button></>}</nav>
    </>}
    {donor && !loading && data && <section className={styles.selection} aria-label="Selected contributor">
      <div className={styles.explorerHeader}><h4>{donor.name}</h4><button onClick={() => { setDonor(undefined); setMember(undefined); }}>Clear selection</button></div>
      <p>Campaigns receiving reported contributions</p>
      <ul className={styles.explorerRows}>{data.related_representatives.map(item => <li key={item.id}>
        <button aria-pressed={member?.id === item.id} onClick={() => setMember(item)}>{item.name}</button><strong>{money(item.amount)}</strong><Evidence url={item.source_url} />
      </li>)}</ul>
      {!data.related_representatives.length && <p>No other saved campaign connections in this scope.</p>}
      <nav className={styles.controls} aria-label="Connected representatives pages">{(memberPage > 0 || data.next_related_cursor != null) && <><button disabled={!memberPage} onClick={() => { setMemberPage(Math.max(0, memberPage - 20)); setMember(undefined); }}>Prev</button><button disabled={data.next_related_cursor == null} onClick={() => { setMemberPage(data.next_related_cursor!); setMember(undefined); }}>Next</button></>}</nav>
      <small>Only researched campaigns are included. Missing research is not evidence of no contributions.</small>
    </section>}
    {member && donor && <MemberActivity key={`${member.id}:${donor.id}`} member={member} period={period} close={() => setMember(undefined)} />}
  </section>;
}

function MemberActivity({ member, period, close }: { member: { id: number; name: string; snapshot?: string }; period: number; close: () => void }) {
  const [data, setData] = useState<Connections | null>(null), [error, setError] = useState("");
  const [cursor, setCursor] = useState(0), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError("");
    getConnections(member.id, period, cursor, controller.signal, undefined, 0, 0, { snapshot: member.snapshot })
      .then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(() => { if (!controller.signal.aborted) setError("Could not load legislative activity."); });
    return () => controller.abort();
  }, [member.id, member.snapshot, period, cursor, retry]);
  return <section className={styles.selection} aria-label="Selected representative activity">
    <div className={styles.explorerHeader}><h4>{member.name}: legislative activity</h4><button onClick={close}>Close activity</button></div>
    <p className={styles.note}>Recorded activity during {period - 1}–{period}. This does not show the contributor’s position on these bills.</p>
    {error ? <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry activity</button></p> : !data && <p role="status">Loading activity…</p>}
    {data && <><ul className={styles.activityRows}>{data.bills.map(bill => <li key={bill.id}>
      <small>{bill.relations.filter(label => !label.startsWith("Recorded vote")).join(" · ")}</small>
      <a href={`/bills/${bill.id}`}>{bill.number}: {bill.title}</a>
      {bill.votes.map(vote => <p key={vote.vote_id}>{vote.question || "Recorded roll-call vote"}: {vote.position.replaceAll("_", " ")} <a href={`/votes/${vote.vote_id}`}>View vote</a></p>)}
      <div>{bill.topics.map(topic => <a key={topic.id} className={styles.pill} href={`/bills?topic_id=${topic.id}`}>{topic.name}</a>)}</div>
    </li>)}</ul>{!data.bills.length && <p>No recorded activity in this period.</p>}
    <nav className={styles.controls} aria-label="Legislative activity pages"><button disabled={!cursor} onClick={() => setCursor(Math.max(0, cursor - 10))}>Prev</button><span>{data.count} bills</span><button disabled={data.next_cursor == null} onClick={() => setCursor(data.next_cursor!)}>Next</button></nav></>}
  </section>;
}
