"use client";
import React from "react";
import Link from "next/link";
import { getApiBase, type TrackedLegislatorItem } from "@/lib/api";
import LegislatorName from "./LegislatorName";
import styles from "./tracked-legislators.module.css";

function Card({ item, congress }: { item: TrackedLegislatorItem; congress: number | null }) {
  const rep = item.representative, facts = item.card;
  const [failedPhoto, setFailedPhoto] = React.useState("");
  const plainName = rep.name.replace(/^(Rep\.|Sen\.|Del\.|Resident Commissioner)\s*/i, "").replace(/\s*\[[^\]]*\]\s*$/, "");
  const name = rep.first_name && rep.last_name ? `${rep.first_name} ${rep.last_name}` : plainName.includes(",") ? plainName.split(",").slice(1).join(",").trim() + " " + plainName.split(",")[0].trim() : plainName;
  const party = /^(R|Republican)$/i.test(rep.party) ? "republican" : /^(D|Democrat|Democratic)$/i.test(rep.party) ? "democrat" : "other";
  const partyLabel = party === "republican" ? "Republican" : party === "democrat" ? "Democrat" : rep.party || "Party unavailable";
  const rawPhoto = facts?.portrait?.url || rep.image_url || (/^[A-Z]\d{6}$/i.test(rep.bioguide_id) ? `https://www.congress.gov/img/member/${rep.bioguide_id.toLowerCase()}_200.jpg` : "");
  const photo = rawPhoto.startsWith(`/api/representatives/${rep.id}/portraits/`) ? getApiBase() + rawPhoto : /^https:\/\//.test(rawPhoto) ? rawPhoto : "";
  const bill = facts?.latest_bill;
  return <article className={styles.card} data-party={party}>
    <header>
      <span className={styles.avatar}>{photo && photo !== failedPhoto ? <img src={photo} alt={name} onError={() => setFailedPhoto(photo)} /> : <span aria-hidden="true">{name.split(/\s+/).filter(Boolean).map(part => part[0]).filter((_, index, parts) => index === 0 || index === parts.length - 1).join("")}</span>}</span>
      <div><h3>{congress ? <LegislatorName id={rep.id} name={name} congress={congress} /> : <Link href={`/representatives/${rep.id}`}>{name}</Link>}</h3>
        <p>{partyLabel} · {rep.state}{rep.district ? ` · District ${rep.district}` : ""}</p>
        <p>{rep.chamber === "senate" ? "Senate" : rep.chamber === "house" ? "House" : rep.chamber}</p>
      </div>
    </header>
    {facts?.biography?.text && <p className={styles.bio}>{facts.biography.text}</p>}
    <div className={styles.latest}><span>Latest sponsored bill</span>{bill ? <><Link href={`/bills/${bill.id}`}>{bill.bill_number} · {bill.title}</Link><small>{bill.introduced_at} · Congress {bill.session}</small></> : <p>No dated bills on record.</p>}</div>
    {(facts?.biography || facts?.portrait) && <details className={styles.sources}><summary>Sources</summary>{[facts.biography?.source, facts.portrait?.source].filter(Boolean).map((source, index) => <p key={index}>{source && /^https:\/\//.test(source.url) ? <a href={source.url} target="_blank" rel="noreferrer">{source.attribution || "Source"}</a> : source?.attribution}{source?.license && ` · ${source.license}`}</p>)}</details>}
  </article>;
}

export default function TrackedLegislators({ items, congress }: { items: TrackedLegislatorItem[]; congress: number | null }) {
  return <section className={styles.section}><div className={styles.heading}><h2>Tracked legislators <small>{items.length}</small></h2><Link href="/representatives">Find representatives</Link></div>
    {items.length ? <div className={styles.row} role="region" aria-label="Tracked legislators" tabIndex={0}>{items.map(item => <Card key={item.representative.id} item={item} congress={congress} />)}</div> : <p>Track a representative to see them here.</p>}
  </section>;
}
