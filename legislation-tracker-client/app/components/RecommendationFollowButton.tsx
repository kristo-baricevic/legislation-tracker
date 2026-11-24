"use client";

import { useRef, useState } from "react";
import styles from "./recommendations.module.css";

export default function RecommendationFollowButton({ label, followed, children, onToggle }: {
  label: string; followed: boolean; children: string; onToggle: () => Promise<void>;
}) {
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  async function toggle() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setFailed(false);
    try {
      await onToggle();
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setFailed(true);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }
  return <>
    <button className={styles.action} aria-label={label} aria-pressed={followed} aria-disabled={pending} onClick={() => void toggle()}>{children}</button>
    {failed && <span role="alert">Your follow was not saved. Try again.</span>}
  </>;
}
