"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { getApiBase, publicGet } from "@/lib/api";

interface DocumentInfo {
  id: number;
  bill: number;
  bill_title: string;
  bill_number: string;
  version_label: string;
  download_url: string | null;
}
const control = "rounded border border-slate-400 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40 dark:border-green-700";

export function DocumentReader({ documentId }: { documentId: string }) {
  const [data, setData] = useState<{ info: DocumentInfo; text: string } | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const article = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(false);
    if (!/^[1-9]\d*$/.test(documentId)) { setError(true); return; }
    Promise.all([
      publicGet<DocumentInfo>(`/api/documents/${documentId}/`, { signal: controller.signal }),
      publicGet<{ text: string }>(`/api/documents/${documentId}/text/`, { signal: controller.signal }),
    ]).then(([info, result]) => {
      if (!controller.signal.aborted) setData({ info, text: result.text });
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [documentId, retry]);

  const blocks = useMemo(() => {
    let offset = 0;
    const result = [];
    for (const text of (data?.text ?? "").split("\n")) {
      result.push({ text, start: offset });
      offset += text.length + 1;
    }
    return result;
  }, [data]);
  const matches = useMemo(() => {
    if (!query.trim() || !data) return [];
    const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    const found: number[] = [];
    let match;
    while (found.length < 500 && (match = pattern.exec(data.text)) !== null) {
      found.push(match.index);
    }
    return found;
  }, [data, query]);
  useEffect(() => {
    article.current?.querySelector('[data-current="true"]')?.scrollIntoView?.({ block: "center" });
  }, [selected, matches]);

  function highlighted(text: string, start: number) {
    const pieces = [];
    let cursor = 0;
    for (let index = 0; index < matches.length; index++) {
      const from = Math.max(matches[index] - start, 0);
      const to = Math.min(matches[index] + query.length - start, text.length);
      if (from >= to) continue;
      pieces.push(<Fragment key={index}>{text.slice(cursor, from)}<mark data-current={index === selected} className={index === selected ? "bg-amber-400 text-black outline outline-2 outline-amber-700" : "bg-yellow-200 text-black"}>{text.slice(from, to)}</mark></Fragment>);
      cursor = to;
    }
    pieces.push(text.slice(cursor));
    return pieces;
  }

  if (error) return <div className="mx-auto max-w-3xl p-6"><div role="alert">Could not load this bill text. It may not be available yet.</div><button className={control + " mt-4"} onClick={() => setRetry(retry + 1)}>Retry</button><Link className="ml-4 underline" href="/bills">Browse bills</Link></div>;
  if (!data) return <p role="status" className="mx-auto max-w-3xl p-6">Loading bill text…</p>;
  const { info, text } = data;
  return <main className="mx-auto max-w-4xl px-4 py-6 text-slate-900 dark:text-green-200 sm:px-8">
    <Link href={`/bills/${info.bill}`} className="text-sm font-semibold text-blue-900 underline dark:text-green-400">Back to bill summary</Link>
    <header className="my-6">
      <p className="text-sm text-slate-600 dark:text-green-400">{info.bill_number}</p>
      <h1 className="mt-2 text-3xl font-semibold leading-tight">{info.bill_title}</h1>
      <p className="mt-3">{info.version_label}</p>
      <p className="mt-2 text-sm text-slate-600 dark:text-green-400">Full bill text, not a summary. Wording is preserved from the stored source.</p>
      {info.download_url && <a className="mt-3 inline-block text-sm font-semibold underline" href={/^https?:\/\//.test(info.download_url) ? info.download_url : getApiBase() + info.download_url}>Download original</a>}
    </header>
    {text.trim() ? <>
      <div className="sticky top-0 z-10 mb-6 flex flex-wrap items-end gap-3 border-y border-slate-300 bg-white p-3 dark:border-green-800 dark:bg-black">
        <label className="min-w-0 flex-1 text-sm">Find in bill text<input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(0); }} className={control + " mt-1 block w-full bg-white dark:bg-black"} /></label>
        <button className={control} disabled={!matches.length} onClick={() => setSelected((selected + matches.length - 1) % matches.length)}>Previous match</button>
        <button className={control} disabled={!matches.length} onClick={() => setSelected((selected + 1) % matches.length)}>Next match</button>
        <p role="status" className="w-full text-sm">{query.trim() ? matches.length ? `${selected + 1} of ${matches.length} matches${matches.length === 500 ? " (first 500 shown; refine your search)" : ""}` : "No matches" : "Search for a word or phrase."}</p>
      </div>
      <article ref={article} aria-label="Full bill text" className="mx-auto max-w-[75ch] break-words text-base leading-8 [overflow-wrap:anywhere]">
        {blocks.map((block) => /^(?:SEC\.|SECTION\s|TITLE\s|DIVISION\s)/i.test(block.text.trim())
          ? <h2 key={block.start} className="mb-3 mt-8 whitespace-pre-wrap text-xl font-semibold">{highlighted(block.text, block.start)}</h2>
          : <p key={block.start} className="mb-3 whitespace-pre-wrap">{highlighted(block.text, block.start)}</p>)}
      </article>
    </> : <p>Text is not available for this version yet.</p>}
  </main>;
}
