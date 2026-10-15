import Link from "next/link";
import type { RecommendationEmptyReason } from "@/lib/recommendations";
import styles from "./recommendations.module.css";

export function RecommendationState({ loading, error, signedIn, empty, retry, kind = "bills" }: { loading: boolean; error: string; signedIn: boolean; empty?: RecommendationEmptyReason | null; retry: () => void; kind?: "bills" | "representatives" }) {
  if (loading) return <p role="status" className={styles.empty}>Loading recommendations…</p>;
  if (error) return <div role="alert" className={styles.empty}>{error} <button className={styles.action} onClick={retry}>Retry recommendations</button></div>;
  if (!signedIn) return <p className={styles.empty}><Link href="/login">Log in</Link> to discover legislation from your followed interests.</p>;
  const message = empty === "no_follows" ? "Follow a topic or representative to start discovering related legislation."
    : empty === "unsupported_follows_only" ? "Your current follows do not provide supported topics for these recommendations."
    : empty === "insufficient_metadata" ? "There is not enough recorded topic or sponsor information for your followed interests yet."
    : kind === "representatives" ? "No current representatives have enough matching recorded activity for these interests yet." : "No other ingested legislation matches your followed interests yet.";
  return <p role="status" className={styles.empty}>{message} <Link href="/topics">Browse topics</Link></p>;
}
