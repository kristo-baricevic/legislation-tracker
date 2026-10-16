"use client";

import type { ReactNode } from "react";
import type { BillListItem } from "@/lib/api";
import LegislatorName from "./LegislatorName";
import styles from "./bill-deck.module.css";

const colors = ["#233f68", "#923e47", "#2f6b50", "#426c86", "#705786", "#357b78"];
export function topicColor(id: number) { return colors[Math.abs(id) % colors.length]; }
export function readable(value: string) { return value.replaceAll("_", " "); }
export function dateLabel(value: string | null) { if (!value) return "Not recorded"; const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value); return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); }

export default function BillCard({ bill, onOpen, footer, accentTopicId, sponsorState }: {
  bill: BillListItem;
  onOpen: () => void;
  footer: ReactNode;
  accentTopicId?: number;
  sponsorState?: string;
}) {
  return <article className={styles.card}>
    <div className={styles.bar} style={{ background: topicColor(accentTopicId ?? bill.topics[0]?.topic_id ?? 0) }} />
    <div className={styles.cardBody}>
      <div className={styles.cardMeta}><span>{bill.bill_number} / {bill.session}</span><span>{readable(bill.status || "Status unavailable")}</span></div>
      <h3><button onClick={onOpen}>{bill.title || "Untitled bill"}</button></h3>
      {bill.highlights?.[0] && <p className={styles.cardTopics}>{bill.highlights[0].segments.map((segment, index) => segment.matched ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>)}</p>}
      <p className={styles.cardTopics}>{bill.topics.map(item => item.name).join(", ") || "Topic not recorded"}</p>
      <p className={styles.sponsor}><LegislatorName id={bill.sponsor_id ?? null} name={bill.sponsor_name || "Sponsor not recorded"} congress={bill.session} />{sponsorState ? ` (${sponsorState}, latest stored state)` : ""}</p>
      <div className={styles.cardFooter}><span>Last action<br /><time>{dateLabel(bill.last_action_at)}</time></span>{footer}</div>
    </div>
  </article>;
}
