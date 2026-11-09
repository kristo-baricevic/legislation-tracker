"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { getDonationSizes, type DonationSizes } from "@/lib/representative-research";
import CardTooltip from "./CardTooltip";
import styles from "./representative-research.module.css";

const colors = ["#b6c8b0", "#638675", "#3f697d", "#a77850"];
const dollars = (value: string) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(Number(value));

export default function DonationPie({ representativeId, period, snapshot, refreshToken, initialData }: { initialData?: DonationSizes; representativeId: number; period: number; snapshot: string; refreshToken: string }) {
  const [data, setData] = useState<DonationSizes | null>(initialData ?? null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getDonationSizes(representativeId, period, snapshot, controller.signal).then(result => {
      if (!controller.signal.aborted) { setData(result); setError(false); }
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [representativeId, period, snapshot, refreshToken, retry]);
  const total = Number(data?.total ?? 0);
  let offset = 0;
  const slices = data?.results.map((row, i) => {
    const share = total > 0 ? Number(row.amount) / total * 100 : 0;
    const start = offset;
    offset += share;
    return { ...row, share, color: colors[i % colors.length], gradient: `${colors[i % colors.length]} ${start}% ${offset}%` };
  }) ?? [];
  return <section className={styles.donationPie} aria-label="Donations by size">
    <div className={styles.pieHeading}><h3>Donations by size</h3><CardTooltip text="Slices show dollars, not donor counts, grouped by each donation’s amount. Includes collected itemized contributions only; excludes refunds and outside spending. Collection may be incomplete."><span tabIndex={0} aria-label="About donation sizes">ⓘ</span></CardTooltip><Link href={`/representatives/${representativeId}`}>View records</Link></div>
    {error && <p role="alert">Could not load donations. <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {!data && !error && <p role="status">Loading donations…</p>}
    {data && total > 0 && <div className={styles.pieLayout}>
      <div role="img" aria-label="Donation dollars by donation size" className={styles.pieDisc} style={{ background: `conic-gradient(${slices.map(slice => slice.gradient).join(",")})` }} />
      <ul className={styles.pieLegend}>{slices.map(slice => <li key={slice.label}><span className={styles.pieSwatch} style={{ background: slice.color }} aria-hidden="true" /><span>{slice.label}</span><strong>{dollars(slice.amount)}</strong><span>{slice.share > 0 && slice.share < 1 ? "<1" : Math.round(slice.share)}%</span></li>)}</ul>
    </div>}
    {data && total === 0 && <p>No donations recorded yet.</p>}
  </section>;
}
