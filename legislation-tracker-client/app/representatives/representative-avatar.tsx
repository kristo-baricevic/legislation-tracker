"use client";

import { useState } from "react";
import Link from "next/link";
import { getApiBase, type RepresentativeItem } from "@/lib/api";
import { representativeInitials } from "@/lib/representative-name";

export default function RepresentativeAvatar({ rep, congress, children }: {
  rep: RepresentativeItem; congress: number | null; children?: React.ReactNode;
}) {
  const [failedPhoto, setFailedPhoto] = useState("");
  const plainName = rep.name.replace(/^(Rep\.|Sen\.|Del\.|Resident Commissioner)\s*/i, "").replace(/\s*\[[^\]]*\]\s*$/, "");
  const name = rep.first_name && rep.last_name ? `${rep.first_name} ${rep.last_name}` : plainName.includes(",") ? `${plainName.split(",").slice(1).join(",").trim()} ${plainName.split(",")[0].trim()}` : plainName;
  const party = /^(D|Democrat|Democratic)$/i.test(rep.party) ? "Democrat" : /^(R|Republican)$/i.test(rep.party) ? "Republican" : /^(I|ID|Independent)$/i.test(rep.party) ? "Independent" : rep.party || "Party unknown";
  const partyStyle = party === "Democrat"
    ? "border-[#9bafc5] bg-[#edf2f7] text-[#405b78] dark:border-[#627b95] dark:bg-[#253341] dark:text-[#c0d1e2]"
    : party === "Republican"
      ? "border-[#c7a39e] bg-[#f7efed] text-[#80534c] dark:border-[#956e68] dark:bg-[#3e2c2a] dark:text-[#e3c4be]"
      : party === "Independent"
        ? "border-[#b4a5c9] bg-[#f2eef7] text-[#68547e] dark:border-[#857298] dark:bg-[#332b40] dark:text-[#d6c7e5]"
        : "border-slate-300 bg-slate-100 text-slate-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300";
  const raw = rep.image_url || (/^[A-Z]\d{6}$/i.test(rep.bioguide_id) ? `https://www.congress.gov/img/member/${rep.bioguide_id.toLowerCase()}_200.jpg` : "");
  const photo = raw.startsWith(`/api/representatives/${rep.id}/portraits/`) ? getApiBase() + raw : /^https:\/\//.test(raw) ? raw : "";
  const initials = representativeInitials(rep.first_name && rep.last_name ? `${rep.first_name} ${rep.last_name}` : rep.name);
  const portrait = <span className={`flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-full border p-1.5 shadow-sm ${partyStyle}`}>
      {photo && photo !== failedPhoto ? <img src={photo} alt={name} loading="lazy" onError={() => setFailedPhoto(photo)} className="h-full w-full rounded-full object-cover object-top" /> : <span aria-hidden="true" className="text-3xl font-semibold">{initials}</span>}
    </span>;
  const portraitClass = "rounded-full cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-current";
  const href = `/representatives/${rep.id}${congress ? `?congress=${congress}` : ""}`;
  return <li className="flex min-w-0 flex-col items-center gap-3 rounded-xl px-3 py-5 text-center hover:bg-wash">
    <Link href={href} aria-label={`View ${name} profile`} className={portraitClass}>{portrait}</Link>
    <h2 className="text-base font-semibold leading-snug text-ink [&_a]:rounded [&_a]:hover:underline [&_a]:focus-visible:outline-2">
      <Link href={href}>{name}</Link>
    </h2>
    <div className="flex flex-wrap justify-center gap-1.5 text-xs text-ink">
      {[rep.state, rep.chamber === "house" ? "House" : rep.chamber === "senate" ? "Senate" : rep.chamber, rep.district ? `District ${rep.district}` : ""].filter(Boolean).map(label => <span key={label} className="rounded-full border border-line bg-wash px-2 py-1">{label}</span>)}
      <span className={`rounded-full border px-2 py-1 ${partyStyle}`}>{party}</span>
    </div>
    {children}
  </li>;
}
