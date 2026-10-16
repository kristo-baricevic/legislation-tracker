"use client";
import React from "react";
import type { BillListItem } from "@/lib/api";
import BillRecommendations from "./BillRecommendations";
import RepresentativeRecommendations, { type RepresentativeRecommendationsProps } from "./RepresentativeRecommendations";
import styles from "./recommendations.module.css";

export default function RecommendationsPreview({ onOpenBill, onDismissBill, renderName }: { onOpenBill: (bill: BillListItem) => boolean | void; onDismissBill?: () => void } & RepresentativeRecommendationsProps) {
  return <div className={styles.section}>
    <BillRecommendations onOpenBill={onOpenBill} onDismissBill={onDismissBill} /><RepresentativeRecommendations renderName={renderName} />
  </div>;
}
