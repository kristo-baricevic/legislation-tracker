"use client";

import { useState } from "react";
import { authPost, capturePersonalizedScope, sessionMutation, type PersonalizedScope } from "@/lib/api";
import styles from "./recommendations.module.css";

export default function DismissRecommendation({ kind, id, name, scope, onDismiss }: {
  kind: "bill" | "representative"; id: number; name: string; scope: PersonalizedScope | null; onDismiss: (scope: PersonalizedScope, id: number) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  async function dismiss() {
    if (!scope || saving) return;
    setSaving(true);
    setFailed(false);
    try {
      const endpoint = kind === "bill" ? "recommendations" : "representative-recommendations";
      await sessionMutation(options => authPost(`/api/tracking/${endpoint}/${id}/dismiss/`, undefined, options), { scope });
      const current = capturePersonalizedScope();
      if (current.sessionGeneration === scope.sessionGeneration) onDismiss(current, id);
    } catch {
      if (capturePersonalizedScope().sessionGeneration === scope.sessionGeneration) setFailed(true);
    } finally {
      setSaving(false);
    }
  }
  return <>
    <button type="button" className={styles.dismiss} title="Dismiss recommendation" disabled={saving} aria-label={`Dismiss ${name} from recommendations`} onClick={dismiss}><span aria-hidden="true">×</span></button>
    {failed && <span role="alert">Could not dismiss this recommendation. Try again.</span>}
  </>;
}
