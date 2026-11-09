"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";

import {
  getApiBase,
  getContractEvidence,
  type ContractEvidenceParams,
} from "@/lib/api";
import type { LegalNlpEvidenceItem } from "@/lib/contracts";
import { SourcePopover } from "./source-popover";

interface SourceEvidenceProps {
  annotations?: ReactNode;
  contractId: number;
  lineItemId?: string;
  financialItemId?: string;
  definitionItemId?: string;
  textUrl?: string | null;
  downloadUrl?: string | null;
  label?: string;
  number?: number;
}

function documentUrl(path: string): string {
  return /^https?:\/\//.test(path) ? path : `${getApiBase()}${path}`;
}

function evidenceIdentity(props: SourceEvidenceProps): string {
  return [
    props.contractId,
    props.lineItemId ?? "",
    props.financialItemId ?? "",
    props.definitionItemId ?? "",
  ].join(":");
}

export function SourceEvidence(props: SourceEvidenceProps) {
  const [chunks, setChunks] = useState<LegalNlpEvidenceItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const identity = evidenceIdentity(props);

  useEffect(() => {
    requestId.current += 1;
    setChunks([]);
    setPage(1);
    setHasMore(false);
    setLoading(false);
    setError(null);
  }, [identity]);

  async function load(targetPage: number) {
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    const params: ContractEvidenceParams = {
      page: targetPage,
      pageSize: 25,
      ...(props.lineItemId ? { lineItemId: props.lineItemId } : {}),
      ...(props.financialItemId ? { financialItemId: props.financialItemId } : {}),
      ...(props.definitionItemId ? { definitionItemId: props.definitionItemId } : {}),
    };
    try {
      const response = await getContractEvidence(props.contractId, params);
      if (activeRequest !== requestId.current) return;
      setChunks((current) => {
        const incoming = targetPage === 1 ? response.results : [...current, ...response.results];
        const seen = new Set<string>();
        return incoming.filter((chunk) => {
          const key = `${chunk.start_char}:${chunk.end_char}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      });
      setPage(targetPage);
      setHasMore(Boolean(response.next));
    } catch {
      if (activeRequest === requestId.current) {
        setError("Could not load bill text. Try again.");
      }
    } finally {
      if (activeRequest === requestId.current) setLoading(false);
    }
  }

  return (
    <SourcePopover key={identity} number={props.number} label={props.label ?? "Read bill text"} onOpen={() => { if (!chunks.length && !loading) void load(1); }}>
        {props.annotations}
        <div>
          {loading && chunks.length === 0 && (
            <p aria-live="polite" className="text-sm text-slate-600 dark:text-green-600">
              Loading source text…
            </p>
          )}
          {error && (
            <div role="alert" className="text-sm text-red-700 dark:text-red-300">
              <p>{error}</p>
              <button
                type="button"
                onClick={() => void load(chunks.length === 0 ? 1 : page + 1)}
                className="mt-2 cursor-pointer border border-current px-2 py-1 font-semibold focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                Retry source text
              </button>
            </div>
          )}
          {chunks.length > 0 && (
            <blockquote
              data-testid="source-evidence-text"
              className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-800 [overflow-wrap:anywhere] dark:text-green-200"
            >
              {chunks.map((chunk) => chunk.quoted_text).join("")}
            </blockquote>
          )}
          {!loading && !error && chunks.length === 0 && <p>No source passage is available. Read the full document below.</p>}
          {hasMore && !error && (
            <button
              type="button"
              disabled={loading}
              onClick={() => void load(page + 1)}
              className="mt-3 cursor-pointer border border-slate-600 px-3 py-1.5 text-sm font-semibold text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-green-700 dark:text-green-300"
            >
              {loading ? "Loading source text…" : "Load more source text"}
            </button>
          )}
          {(props.textUrl || props.downloadUrl) && (
            <div className="mt-3 flex flex-wrap gap-4 text-sm">
              {props.textUrl && /\/documents\/([1-9]\d*)\/text\/?$/.test(props.textUrl) && (
                <Link href={`/documents/${props.textUrl.match(/\/documents\/([1-9]\d*)\/text\/?$/)![1]}`} className="text-blue-900 underline dark:text-green-400">
                  Read full text
                </Link>
              )}
              {props.downloadUrl && (
                <a href={documentUrl(props.downloadUrl)} target="_blank" rel="noopener noreferrer" className="text-blue-900 underline dark:text-green-400">
                  Download document
                </a>
              )}
            </div>
          )}
        </div>
    </SourcePopover>
  );
}
