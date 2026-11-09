"use client";

import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import type { BillListItem } from "@/lib/api";
import RepresentativeAvatarBadge from "./RepresentativeAvatarBadge";
import StageTrack from "./StageTrack";
import { dateLabel, ordinal, readable, topicColor } from "@/lib/bill-format";
import { stageFor } from "@/lib/bill-stage";
import styles from "./bill-deck.module.css";

export { dateLabel, readable, topicColor };

export default function BillCard({ bill, onOpen, footer, accentTopicId, sponsorState }: {
  bill: BillListItem;
  onOpen?: () => void;
  footer: ReactNode;
  accentTopicId?: number;
  sponsorState?: string;
}) {
  const primary = bill.topics.find(topic => topic.topic_id === accentTopicId) ?? bill.topics[0];
  const color = topicColor(primary?.topic_id ?? 0);
  const stage = stageFor(bill.status);
  return <article className={styles.card} style={{ "--topic": color } as CSSProperties}>
    <div className={styles.bar} aria-hidden="true" />
    <div className={styles.cardBody}>
      <div className={styles.cardMeta}>
        <span className={styles.topicName} title={bill.topics.map(topic => topic.name).join(", ") || undefined}>{primary?.name ?? "Topic not recorded"}{bill.topics.length > 1 && <span className={styles.moreTopics}> +{bill.topics.length - 1}</span>}</span>
        <span className={styles.number}>{bill.bill_number}<small>{bill.jurisdiction === "federal" ? `${ordinal(bill.session)} Congress` : `Session ${bill.session}`}</small></span>
      </div>
      <h3>{onOpen ? <button onClick={onOpen}><span className={styles.titleText}>{bill.title || "Untitled bill"}</span></button> : <Link href={`/bills/${bill.id}`}><span className={styles.titleText}>{bill.title || "Untitled bill"}</span></Link>}</h3>
      {bill.highlights?.[0] && <p className={styles.cardTopics}>{bill.highlights[0].segments.map((segment, index) => segment.matched ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>)}</p>}
      <div className={styles.sponsor}>{bill.sponsor_id ? <RepresentativeAvatarBadge id={bill.sponsor_id} name={bill.sponsor_name || "Sponsor"} congress={bill.session} representative={bill.sponsor_bioguide_id ? { bioguide_id: bill.sponsor_bioguide_id } : undefined} notes={["Introduced this bill", ...(sponsorState ? [`State: ${sponsorState}`] : [])]} /> : <span>Sponsor not recorded</span>}</div>
      {stage ? <StageTrack stage={stage} color={color} /> : <p className={styles.actionText}>{readable(bill.status || "Status unavailable")}</p>}
      <div className={styles.cardFooter}><span>Last action<br /><time>{dateLabel(bill.last_action_at)}</time></span>{footer}</div>
    </div>
  </article>;
}
