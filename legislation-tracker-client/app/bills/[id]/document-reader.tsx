"use client";

import type { ReactNode } from "react";
import { compatibleReader } from "@/lib/reader-enhancements";
import { useAiGlossary } from "./ai-glossary-context";
import { ReaderIdentityProvider, ReaderSummary, LegacyReaderChanges } from "./reader-explanation";
import { ReaderTabBar, ReaderTabPanel } from "./reader-tabs";
import { ReviewedMoney } from "./reviewed-money";

/** Full XML reviews can succeed before an NLP contract exists. */
export function DocumentReader({ documentId, enabled, children }: { documentId: number | null; enabled: boolean; children: ReactNode }) {
  const { enhancement } = useAiGlossary();
  const identity = { contractId: null, contractHash: null, documentId };
  const reader = enabled ? compatibleReader(enhancement, identity) : null;
  if (!reader) return <>{children}</>;
  return <ReaderIdentityProvider value={identity}>
    <section className="mb-6"><h2 className="text-xl font-semibold">Summary</h2>
      <ReaderSummary><p>A summary is not available for this version.</p></ReaderSummary>
    </section>
    <ReaderTabBar />
    <ReaderTabPanel tab="changes"><h3 className="mb-5 text-xl font-semibold">What this bill does</h3>
      <LegacyReaderChanges><p>No detailed changes are available for this version.</p></LegacyReaderChanges>
    </ReaderTabPanel>
    <ReaderTabPanel tab="money"><ReviewedMoney key={`${documentId}-${enhancement?.id}`} result={reader} /></ReaderTabPanel>
    <ReaderTabPanel tab="terms"><p>A separate glossary is not available for this version.</p></ReaderTabPanel>
  </ReaderIdentityProvider>;
}
