"use client";

import React from "react";
import { profileHref, type ProfileScope } from "@/lib/legislator-profile";
import { useProfileDialogs } from "./ProfileProvider";

export default function LegislatorName({ id, name, congress, chamber, children, className, ariaLabel }: { id: number | null; name: string; congress: number; chamber?: ProfileScope["chamber"]; children?: React.ReactNode; className?: string; ariaLabel?: string }) {
  const context = useProfileDialogs();
  if (id == null || !Number.isSafeInteger(id) || id <= 0 || !Number.isSafeInteger(congress) || congress < 1 || congress > 1000) return <>{children ?? name}</>;
  const scope = { representativeId: id, congress, chamber };
  return <a href={profileHref(scope)} className={className} aria-label={ariaLabel} onClick={event => {
    if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && context?.open(scope)) event.preventDefault();
  }}>{children ?? name}</a>;
}
