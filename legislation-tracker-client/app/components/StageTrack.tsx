import type { CSSProperties } from "react";
import { STAGES, type BillStage } from "@/lib/bill-stage";
import styles from "./stage-track.module.css";

/**
 * Five stops from "introduced" to "became law". Stops already reached are filled
 * in the bill's topic colour; the current stop is larger and ringed. The visible
 * label below says the same thing in words, so colour is never the only signal.
 */
export default function StageTrack({ stage, color }: { stage: BillStage; color: string }) {
  return <div className={styles.wrap} style={{ "--topic": color } as CSSProperties}>
    <div className={styles.track} role="img" aria-label={`Step ${stage.index + 1} of ${STAGES.length}: ${stage.label}`}>
      {STAGES.map((item, index) => <span key={item.key} className={styles.stop} data-state={index < stage.index ? "done" : index === stage.index ? "current" : "todo"} />)}
    </div>
    <p className={styles.label}>{stage.label}</p>
  </div>;
}
