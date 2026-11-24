"use client";
import LoadingSpinner from "@/app/components/LoadingSpinner";
import Link from "next/link";
import React from "react";
import { getBill, getBillEnhancement, type BillEnhancement, type BillListItem, type BillDetail } from "@/lib/api";
import { dateLabel, ordinal, readable, topicColor } from "@/lib/bill-format";
import { stageFor } from "@/lib/bill-stage";
import { getContractSummary } from "@/lib/contracts";
import styles from "./bill-deck.module.css";
import StackDialog from "./ModalStack";
import CardTooltip from "./CardTooltip";
import RepresentativeAvatarBadge from "./RepresentativeAvatarBadge";
import StageTrack from "./StageTrack";
import DashboardBillReader from "./DashboardBillReader";
import BillModalDetails from "./BillModalDetails";

function generatedSynopsis(value: unknown, structuredOnly = false): string {
  if (value && typeof value === "object" && "orientation" in value) {
    const orientation = value.orientation;
    if (orientation && typeof orientation === "object" && "purpose_clause" in orientation && typeof orientation.purpose_clause === "string") return orientation.purpose_clause.trim();
  }
  return structuredOnly ? "" : getContractSummary(value)?.trim() ?? "";
}
type BillModalProps = { bill: BillListItem; onClose: () => void; fallbackFocus?: () => void };

export default function BillDeckModal(props: BillModalProps) {
  return <DashboardBillReader key={props.bill.id} bill={props.bill}>
    {(_, enhance, feedback, bill) => <BillModal {...props} bill={bill} enhance={enhance} feedback={feedback} />}
  </DashboardBillReader>;
}
function BillModal({ bill, onClose, fallbackFocus, enhance, feedback }: BillModalProps & { enhance: React.ReactNode; feedback: React.ReactNode }) {
  const titleId = React.useId();
  const pagerId = React.useId();
  const [detail, setDetail] = React.useState<BillDetail | null>(null);
  const [enhancement, setEnhancement] = React.useState<BillEnhancement | null>(null);
  const expectsEnhancement = Boolean(bill.enhancement_id && bill.enhancement_status === "succeeded");
  const [enhancementLoading, setEnhancementLoading] = React.useState(expectsEnhancement);
  const [enhancementError, setEnhancementError] = React.useState(false);
  const [enhancementRetry, setEnhancementRetry] = React.useState(0);
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    const controller = new AbortController();
    void getBill(bill.id, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) { setDetail(value); setError(""); }
    }).catch(() => { if (!controller.signal.aborted) setError("Bill details could not be loaded. Please retry."); });
    return () => controller.abort();
  }, [bill.id, attempt]);
  React.useEffect(() => {
    if (!bill.enhancement_id || bill.enhancement_status !== "succeeded") return;
    let live = true;
    setEnhancementLoading(true); setEnhancementError(false);
    void getBillEnhancement(bill.id, bill.enhancement_id).then(value => {
      if (live) setEnhancement(value.active_reader !== undefined ? value.active_reader : value);
    }).catch(() => { if (live) setEnhancementError(true); }).finally(() => { if (live) setEnhancementLoading(false); });
    return () => { live = false; };
  }, [bill.id, bill.enhancement_id, bill.enhancement_status, enhancementRetry]);
  const contract = detail?.latest_contract;
  const contractDocument = detail?.documents.find(document => document.id === contract?.document);
  const source = detail?.documents.find(document => document.is_active_version) ?? contractDocument;
  const sameDocument = contractDocument?.id === source?.id;
  const synopsis = (sameDocument ? generatedSynopsis(contract?.contract_json, true) : "") || source?.reader_summary || (sameDocument ? generatedSynopsis(contract?.contract_json) : "") || "";
  const summary = detail?.summary?.replace(/<[^>]*>/g, " ").trim() ?? "";
  const status = detail?.status ?? bill.status;
  const stage = stageFor(status);
  return <StackDialog identity={`bill:${bill.id}`} titleId={titleId} className={`${styles.deck} ${styles.dialog}`} onClose={onClose} fallbackFocus={fallbackFocus}>
    <div className={styles.modalHeader}><p>{bill.bill_number}, {ordinal(bill.session)} Congress</p><div className={styles.modalHeaderActions}>{enhance}<button autoFocus onClick={onClose} aria-label="Close bill details">Close ✕</button></div></div>
    <div className={styles.modalBody}>
    {feedback}
    <h2 id={titleId} className={styles.modalTitle}><CardTooltip text="Click the title to open the full bill page."><Link href={`/bills/${bill.id}`}>{bill.title || "Untitled bill"} <span aria-hidden="true">↗</span></Link></CardTooltip></h2>
    {stage && <StageTrack stage={stage} color={topicColor(bill.topics[0]?.topic_id ?? 0)} />}
    <LoadingSpinner active={!error && !detail} label="Loading bill details…" />
    {error ? <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>Retry</button></p> : !detail ? null : <>
      <dl className={styles.metadata}>
        <div><dt>Sponsor</dt><dd>{detail.sponsor ? <RepresentativeAvatarBadge id={detail.sponsor} name={detail.sponsor_name || "Sponsor"} congress={detail.session} representative={detail.sponsor_bioguide_id ? { bioguide_id: detail.sponsor_bioguide_id } : undefined} notes={["Introduced this bill"]} /> : "Not recorded"}</dd></div>
        <div><dt>Introduced</dt><dd>{dateLabel(detail.introduced_at)}</dd></div>
        <div className={styles.modalAction}><dt>Latest action</dt><dd><CardTooltip text={readable(status) || "Not recorded"}><button type="button" className={styles.actionInfo} aria-label="Latest action details">{dateLabel(detail.last_action_at)} <span aria-hidden="true">ⓘ</span></button></CardTooltip></dd></div>
      </dl>
      <section className={styles.summary}><h3>Summary</h3><p>{bill.card_summary || summary || synopsis || "No bill summary is available yet."}</p>
        {!bill.card_summary && (summary ? <p className={styles.note}>Source: {detail.summary_source || "Stored bill summary"}.{detail.summary_version_code ? ` Summary version: ${detail.summary_version_code}.` : ""}</p> : synopsis && source && <p className={styles.note}>Source: <Link href={`/documents/${source.id}`}>{source.version_label || "Bill text"}</Link>.</p>)}
      </section>
      <LoadingSpinner active={enhancementLoading} label="Loading explanations…" />
      {enhancementLoading ? null : enhancementError ? <p role="alert" className="text-sm text-red-700">Couldn’t load explanations. <button onClick={() => setEnhancementRetry(value => value + 1)}>Retry explanations</button></p> : <BillModalDetails key={`${bill.id}:${contract?.id}`} billId={bill.id} contractId={sameDocument ? contract?.id : undefined} contractHash={contract?.contract_hash} enhancement={enhancement} document={source} paginationTarget={pagerId} />}
    </>}
    </div><div id={pagerId} className={styles.modalPagerSlot} />
  </StackDialog>;
}
