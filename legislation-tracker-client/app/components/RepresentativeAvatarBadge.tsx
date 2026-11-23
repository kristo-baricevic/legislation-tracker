"use client";
import React from "react";
import { dashboardValue, useDashboardRepVersion } from "@/lib/dashboard-cache";
import Link from "next/link";
import CardTooltip from "./CardTooltip";
import { useProfileDialogs } from "./ProfileProvider";
import { getRepresentative, getApiBase } from "@/lib/api";
import styles from "./recommendations.module.css";
import { representativeInitials } from "@/lib/representative-name";

export default function RepresentativeAvatarBadge({ id, name, notes, representative, congress }: { id: number; name: string; notes: string[]; representative?: { image_url?: string | null; bioguide_id: string }; congress?: number }) {
  const [portrait, setPortrait] = React.useState({ id, url: "" });
  const photo = portrait.id === id ? portrait.url : "";
  const version = useDashboardRepVersion();
  const profiles = useProfileDialogs();
  const [failed, setFailed] = React.useState("");
  React.useEffect(() => {
    let active = true;
    const request = representative ? Promise.resolve(representative) : dashboardValue(`rep:${id}:avatar`, () => getRepresentative(id));
    void request.then(rep => {
      if (!active) return;
      const raw = rep.image_url || (/^[A-Z]\d{6}$/i.test(rep.bioguide_id) ? `https://www.congress.gov/img/member/${rep.bioguide_id.toLowerCase()}_200.jpg` : "");
      setPortrait({ id, url: raw.startsWith(`/api/representatives/${id}/portraits/`) ? getApiBase() + raw : /^https:\/\//.test(raw) ? raw : "" });
    }).catch(() => {});
    return () => { active = false; };
  }, [id, representative?.image_url, representative?.bioguide_id, version]);
  return <CardTooltip text={[name, ...notes].join("\n")}><Link className={styles.representativeAvatar} href={`/representatives/${id}${congress ? `?congress=${congress}` : ""}`} aria-label={name} aria-description={notes.join(". ")} onClick={event => { if (congress && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && profiles?.open({ representativeId: id, congress })) event.preventDefault(); }}>
    {photo && photo !== failed ? <img src={photo} alt={name} loading="lazy" onError={() => setFailed(photo)} /> : <span aria-hidden="true">{representativeInitials(name)}</span>}
  </Link></CardTooltip>;
}
