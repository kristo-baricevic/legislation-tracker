"use client";
import React from "react";
import type { BillListItem } from "@/lib/api";
import { RECOMMENDATIONS_FLAG_KEY, persistRecommendationsFlag, readRecommendationsFlag } from "@/lib/recommendations-flag";
import BillRecommendations from "./BillRecommendations";
import RepresentativeRecommendations, { type RepresentativeRecommendationsProps } from "./RepresentativeRecommendations";
import styles from "./recommendations.module.css";

export default function RecommendationsPreview({ onOpenBill, onDismissBill, renderName }: { onOpenBill: (bill: BillListItem) => boolean | void; onDismissBill?: () => void } & RepresentativeRecommendationsProps) {
  const [enabled, setEnabled] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  React.useEffect(() => {
    const sync = () => setEnabled(readRecommendationsFlag());
    sync();
    const onStorage = (event: StorageEvent) => { if (event.key === RECOMMENDATIONS_FLAG_KEY || event.key === null) sync(); };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  return <div className={styles.section}>
    <label><input data-recommendations-toggle type="checkbox" checked={enabled} onChange={event => {
      setEnabled(event.target.checked);
      if (!event.target.checked) onDismissBill?.();
      setNotice(persistRecommendationsFlag(event.target.checked) ? "" : "Browser storage is unavailable. This preview will reset on reload.");
    }} /> Show recommendations on this browser</label>
    {notice && <p role="status">{notice}</p>}
    {enabled && <><BillRecommendations onOpenBill={onOpenBill} onDismissBill={onDismissBill} /><RepresentativeRecommendations renderName={renderName} /></>}
  </div>;
}
