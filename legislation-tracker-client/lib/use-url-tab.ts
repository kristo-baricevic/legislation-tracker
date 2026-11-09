"use client";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

/** Change tabs without scrolling, refetching the page, or dropping its filters. */
export function useUrlTab<T extends string>(tabs: Record<T, string>, fallback: T) {
  const params = useSearchParams();
  const requested = params.get("tab");
  const resolve = (value: string | null): T => value && Object.prototype.hasOwnProperty.call(tabs, value) ? value as T : fallback;
  const [active, setActive] = useState<T>(() => resolve(requested));
  useEffect(() => { setActive(resolve(requested)); }, [requested]);
  useEffect(() => {
    const restore = () => setActive(resolve(new URLSearchParams(window.location.search).get("tab")));
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, [tabs, fallback]);
  const select = useCallback((tab: T) => {
    const url = new URL(window.location.href);
    if (url.searchParams.get("tab") !== tab) {
      url.searchParams.set("tab", tab);
      window.history.pushState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
    setActive(tab);
  }, []);
  return [active, select] as const;
}

export const representativeTabs = { bills: "Bills", votes: "Votes", funding: "Campaign funding", committees: "Committees" };
export function representativeTabKey(label: string) {
  return (Object.keys(representativeTabs) as (keyof typeof representativeTabs)[]).find(key => representativeTabs[key] === label) ?? "bills";
}
