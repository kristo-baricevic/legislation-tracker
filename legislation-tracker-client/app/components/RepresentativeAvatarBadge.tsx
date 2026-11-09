"use client";
import React from "react";
import Link from "next/link";
import CardTooltip from "./CardTooltip";
import { useProfileDialogs } from "./ProfileProvider";
import { getRepresentative, getApiBase } from "@/lib/api";
import styles from "./recommendations.module.css";
import { representativeInitials } from "@/lib/representative-name";

export default function RepresentativeAvatarBadge({ id, name, notes, representative, congress }: { id: number; name: string; notes: string[]; representative?: { image_url?: string | null; bioguide_id: string }; congress?: number }) {
  const [photo, setPhoto] = React.useState("");
  const profiles = useProfileDialogs();
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setPhoto(""); setFailed(false);
    const request = representative ? Promise.resolve(representative) : getRepresentative(id, controller.signal);
    void request.then(rep => {
      if (!active) return;
      const raw = rep.image_url || (/^[A-Z]\d{6}$/i.test(rep.bioguide_id) ? `https://www.congress.gov/img/member/${rep.bioguide_id.toLowerCase()}_200.jpg` : "");
      setPhoto(raw.startsWith(`/api/representatives/${id}/portraits/`) ? getApiBase() + raw : /^https:\/\//.test(raw) ? raw : "");
    }).catch(() => {});
    return () => { active = false; controller.abort(); };
  }, [id, representative?.image_url, representative?.bioguide_id]);
  return <CardTooltip text={[name, ...notes].join("\n")}><Link className={styles.representativeAvatar} href={`/representatives/${id}${congress ? `?congress=${congress}` : ""}`} aria-label={name} aria-description={notes.join(". ")} onClick={event => { if (congress && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && profiles?.open({ representativeId: id, congress })) event.preventDefault(); }}>
    {photo && !failed ? <img src={photo} alt={name} loading="lazy" onError={() => setFailed(true)} /> : <span aria-hidden="true">{representativeInitials(name)}</span>}
  </Link></CardTooltip>;
}
