"use client";

import Link from "next/link";
import type { AnalysisCondition, SourceFirstResult } from "@/lib/api";

type Claim = SourceFirstResult["provisions"][number]["claims"][number];
function claimLabel(claim: Claim) {
  const label = { required: "Required", prohibited: "Prohibited", permitted: "Permitted", unspecified: "Rule" }[claim.modality];
  return `${label}: ${[claim.actor, claim.action].filter(Boolean).join(" — ")}`;
}

function Condition({ node }: { node: AnalysisCondition }) {
  if (node.operator === "leaf") return <p>{node.text}</p>;
  return <div className="space-y-2"><p className="font-semibold">{node.operator === "all" ? "All of these must apply:" : "At least one must apply:"}</p><ul className="list-disc space-y-2 pl-5">{node.children.map((child, i) => <li key={i}><Condition node={child} /></li>)}</ul></div>;
}

export default function SourceFirstAnalysis({ result }: { result: SourceFirstResult }) {
  const explained = result.provisions.filter(p => p.status === "explained").length;
  const moneyCount = result.provisions.reduce((n, p) => n + p.claims.reduce((sum, c) => sum + c.money.length, 0), 0);
  const financialItems = result.provisions.flatMap(p => p.claims.flatMap(c => c.money));
  const onlyHarmThresholds = financialItems.length > 0 && financialItems.every(item => item.measure?.trim().toLowerCase() === "financial harm threshold");
  return <div className="mt-5 max-w-3xl space-y-6 leading-relaxed">
    {result.coverage.unresolved_unit_ids.length > 0 && <p className="border-l-2 border-amber-400 pl-3 text-sm">Partial AI analysis: {explained} of {result.provisions.length} provisions explained. Unresolved provisions remain available below.</p>}
    {!!result.coverage.context_limited_unit_ids?.length && <p className="border-l-2 border-amber-400 pl-3 text-sm">This analysis explains the supplied bill text. It does not explain the referenced outside law or establish its full legal effect.</p>}
    {result.synopsis.status !== "unavailable" && <section><h3 className="font-semibold">What this bill does</h3><p className="mt-2">{result.synopsis.text}</p></section>}
    {result.synopsis.status === "unavailable" && <p className="text-sm">An AI overview could not be verified. The bill’s non-AI brief remains available above.</p>}
    <p className="text-sm">{moneyCount} financial items shown below. Amounts are not added together because they may overlap or serve different purposes.</p>
    {onlyHarmThresholds && <p className="text-sm">These financial items are harm thresholds, not funding allocations. They are not an estimate of the bill’s cost.</p>}
    {result.provisions.map(provision => <section key={provision.id} className="space-y-3 border-t border-slate-300 pt-4 dark:border-green-900/70">
      {provision.status === "explained" ? <>
        <p className="font-semibold">{provision.summary}</p>
        {provision.details.length > 0 && <ul className="list-disc space-y-2 pl-5">{provision.details.map((detail, i) => <li key={i}>{detail}</li>)}</ul>}
        {!!provision.claims.length && <details><summary className="cursor-pointer font-semibold">All rules and requirements ({provision.claims.length})</summary><ul className="mt-3 list-disc space-y-2 pl-5">{provision.claims.map((claim, i) => <li key={i}>{claimLabel(claim)}{claim.conditions && <Condition node={claim.conditions} />}{claim.exceptions.map((node, n) => <div key={n}><p>Exception:</p><Condition node={node} /></div>)}</li>)}</ul></details>}
        {provision.claims.flatMap(claim => claim.money.map(money => ({ claim, money }))).map(({ claim, money }, i) => <div key={i} className="border-l-2 border-amber-400 pl-3 text-sm">
          <p className="font-semibold">{claimLabel(claim)}</p>
          <p className="font-semibold">{money.amount === null ? "Amount not specified" : `${money.comparator ?? ""} ${money.currency ?? ""} ${money.amount}`.trim()}</p>
          <p>{money.purpose ?? "Purpose needs source review"}</p>
          {money.measure && <p>{money.measure}</p>}{money.period && <p>{money.period}</p>}{money.base && <p>Based on: {money.base}</p>}
        </div>)}
      </> : <div><p className="font-semibold">This provision needs review.</p><p className="text-sm">A reliable explanation is not available. Read the complete source below.</p></div>}
      {!!provision.source_limitations?.length && <details className="text-sm"><summary className="cursor-pointer">Referenced law not included</summary><ul className="mt-2 list-disc pl-5">{provision.source_limitations.map((reference, i) => <li key={i}>{reference}</li>)}</ul></details>}
      <details className="text-sm"><summary className="cursor-pointer underline underline-offset-2">Source text</summary><div className="mt-3 space-y-4">{provision.evidence.map(source => <div key={source.id}><p className="font-semibold">{source.section_label}</p><blockquote className="my-2 whitespace-pre-wrap border-l-2 border-slate-300 pl-3">{source.text}</blockquote><Link className="underline" href={source.url}>Read source</Link></div>)}</div></details>
    </section>)}
  </div>;
}
