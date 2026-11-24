"use client";
import React from "react";
import { dashboardValue, useDashboardRepVersion } from "@/lib/dashboard-cache";
import Link from "next/link";
import CardTooltip from "./CardTooltip";
import { useProfileDialogs } from "./ProfileProvider";
import { getRepresentative, getApiBase } from "@/lib/api";
import styles from "./recommendations.module.css";
import { representativeInitials } from "@/lib/representative-name";

export default function RepresentativeAvatarBadge({ id, name, notes, representative, congress, party, linkToPage = false }: { id: number; name: string; notes: string[]; representative?: { image_url?: string | null; bioguide_id: string; party?: string }; congress?: number; party?: string | null; linkToPage?: boolean }) {
  const [loadedParty, setLoadedParty] = React.useState({id, party: ""});
  const rawParty = (party ?? representative?.party ?? (loadedParty.id === id ? loadedParty.party : "")).trim().toLowerCase();
  const partyGroup = ["d", "democrat", "democratic"].includes(rawParty) ? "democrat" : ["r", "republican"].includes(rawParty) ? "republican" : ["i", "id", "ind", "independent"].includes(rawParty) ? "independent" : undefined;
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
      setLoadedParty({id, party: rep.party || ""});
      const raw = rep.image_url || (/^[A-Z]\d{6}$/i.test(rep.bioguide_id) ? `https://www.congress.gov/img/member/${rep.bioguide_id.toLowerCase()}_200.jpg` : "");
      setPortrait({ id, url: raw.startsWith(`/api/representatives/${id}/portraits/`) ? getApiBase() + raw : /^https:\/\//.test(raw) ? raw : "" });
    }).catch(() => {});
    return () => { active = false; };
  }, [id, representative?.image_url, representative?.bioguide_id, version]);
  return <CardTooltip text={[name, ...(partyGroup ? [partyGroup === "democrat" ? "Democrat" : partyGroup === "republican" ? "Republican" : "Independent"] : []), ...notes].join("\n")}><Link data-party={partyGroup} className={styles.representativeAvatar} href={`/representatives/${id}${congress ? `?congress=${congress}` : ""}`} aria-label={name} aria-description={notes.join(". ")} onClick={event => { if (!linkToPage && congress && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && profiles?.open({ representativeId: id, congress })) event.preventDefault(); }}>
    {photo && photo !== failed ? <img src={photo} alt={name} loading="lazy" onError={() => setFailed(photo)} /> : <span aria-hidden="true">{representativeInitials(name)}</span>}
  </Link></CardTooltip>;
}
