"use client";

import { useState } from "react";
import { authPost, isPersonalizedScopeCurrent, type PersonalizedScope } from "@/lib/api";
import { forgetDashboardValue } from "@/lib/dashboard-cache";
import styles from "./recommendations.module.css";

export default function DismissRecommendation({ kind, id, name, scope }: {
  kind: "bill" | "representative"; id: number; name: string; scope: PersonalizedScope | null;
}) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  async function dismiss() {
    if (!scope || saving) return;
    setSaving(true);
    setFailed(false);
    try {
      const endpoint = kind === "bill" ? "recommendations" : "representative-recommendations";
      await authPost(`/api/tracking/${endpoint}/${id}/dismiss/`, undefined, { scope });
      if (!isPersonalizedScopeCurrent(scope)) return;
      const key = kind === "bill" ? "bill-recommendations" : "rep-recommendations";
      forgetDashboardValue(key);
      window.dispatchEvent(new Event(`dismissed-${key}`));
    } catch {
      if (isPersonalizedScopeCurrent(scope)) setFailed(true);
    } finally {
      setSaving(false);
    }
  }
  return <>
    <button type="button" className={styles.dismiss} title="Dismiss recommendation" disabled={saving} aria-label={`Dismiss ${name} from recommendations`} onClick={dismiss}><span aria-hidden="true">×</span></button>
    {failed && <span role="alert">Could not dismiss this recommendation. Try again.</span>}
  </>;
}
