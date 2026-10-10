"use client";

import React from "react";
import { profileHref, type ProfileScope } from "@/lib/legislator-profile";
import { useProfileDialogs } from "./ProfileProvider";

export default function LegislatorName({ id, name, congress, chamber }: { id: number | null; name: string; congress: number; chamber?: ProfileScope["chamber"] }) {
  const context = useProfileDialogs();
  if (id == null || !Number.isSafeInteger(id) || id <= 0 || !Number.isSafeInteger(congress) || congress < 1 || congress > 1000) return <>{name}</>;
  const scope = { representativeId: id, congress, chamber };
  return <a href={profileHref(scope)} onClick={event => {
    if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && context?.open(scope)) event.preventDefault();
  }}>{name}</a>;
}
