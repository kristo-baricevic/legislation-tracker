import type { BillContractItem } from "@/lib/api";
import {
  getContractSummary,
  groupEvidenceByFieldPath,
  isLegalNlpV2Contract,
  type EvidenceSpanItem,
  type LegalNlpV2ContractJson,
} from "@/lib/contracts";

function LegacyContractSection({ contract }: { contract: BillContractItem }) {
  const j = contract.contract_json;
  const plain = getContractSummary(j);
  const sourceExcerpt = "source_excerpt" in j ? j.source_excerpt : null;
  const excerpt =
    typeof sourceExcerpt === "string" ? sourceExcerpt : null;
  const versionLabel =
    typeof j.version_label === "string"
      ? j.version_label
      : contract.document_version_label;

  return (
    <section className="mb-6 rounded-lg border border-slate-400/80 bg-white/80 p-4 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-green-400">
        Plain-language summary{" "}
        <span className="text-sm font-normal text-slate-600 dark:text-green-600">(beta)</span>
      </h2>
      <p className="mb-3 text-xs text-slate-600 dark:text-green-600">
        Schema {contract.schema_version}
        {versionLabel ? ` · Version: ${versionLabel}` : ""}
        {contract.computed_at
          ? ` · Generated ${new Date(contract.computed_at).toLocaleString()}`
          : ""}
      </p>
      {plain ? (
        <p className="w-full break-words whitespace-pre-wrap leading-relaxed text-slate-800 [overflow-wrap:anywhere] dark:text-green-100">
          {plain}
        </p>
      ) : (
        <p className="text-sm text-slate-600 dark:text-green-500">No summary text in contract yet.</p>
      )}
      {excerpt && excerpt !== plain && (
        <div className="mt-4">
          <h3 className="mb-1 text-sm text-slate-600 dark:text-green-500">Source excerpt</h3>
          <p className="w-full break-words whitespace-pre-wrap text-sm text-slate-700 [overflow-wrap:anywhere] dark:text-green-300/90">
            {excerpt}
          </p>
        </div>
      )}
      {contract.evidence_spans.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-slate-600 dark:text-green-500">
            Evidence spans ({contract.evidence_spans.length})
          </summary>
          <ul className="mt-2 space-y-2 text-sm text-slate-800 dark:text-green-400/90">
            {contract.evidence_spans.map((evidence, index) => (
              <li
                key={`${evidence.field_path}-${index}`}
                className="border-l-2 border-slate-400 pl-3 dark:border-green-800"
              >
                <div className="font-mono text-xs text-slate-600 dark:text-green-500">
                  {evidence.field_path}
                </div>
                <div className="mt-1 line-clamp-4 break-words text-slate-700 [overflow-wrap:anywhere] dark:text-green-300/80">
                  {evidence.quoted_text}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function EvidenceDisclosure({
  title,
  index,
  spans,
}: {
  title: string;
  index: number;
  spans: readonly EvidenceSpanItem[];
}) {
  if (spans.length === 0) return null;
  return (
    <details className="group mt-3 border-t border-slate-200 pt-2 dark:border-green-950">
      <summary
        aria-label={`Source evidence for ${title} item ${index + 1}`}
        className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 marker:hidden hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-600 dark:text-green-700 dark:hover:text-green-400"
      >
        <span aria-hidden="true" className="mr-2 inline-block transition-transform group-open:rotate-90">›</span>
        Source evidence · {spans.length}
      </summary>
      <ul className="mt-3 space-y-3">
        {spans.map((span, evidenceIndex) => (
          <li
            key={`${span.start_char}-${span.end_char}-${evidenceIndex}`}
            className="border-l-2 border-emerald-600/60 pl-3 text-sm text-slate-700 dark:border-green-500/50 dark:text-green-200/80"
          >
            <p className="break-words [overflow-wrap:anywhere]">{span.quoted_text}</p>
            <p className="mt-1 font-mono text-[11px] text-slate-500 dark:text-green-700">
              Characters {span.start_char}–{span.end_char}
              {span.page_number ? ` · Page ${span.page_number}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}

interface DisplayItem {
  section_label: string | null;
  display_text: string;
}

function ClaimGroup({
  title,
  items,
  fieldPrefix,
  evidenceField = "display_text",
  evidence,
}: {
  title: string;
  items: readonly DisplayItem[];
  fieldPrefix: string;
  evidenceField?: string;
  evidence: ReadonlyMap<string, readonly EvidenceSpanItem[]>;
}) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={`contract-${fieldPrefix}`}>
      <h3
        id={`contract-${fieldPrefix}`}
        className="mb-2 text-sm font-bold uppercase tracking-[0.16em] text-slate-700 dark:text-green-500"
      >
        {title}
      </h3>
      <ol className="space-y-3">
        {items.map((item, index) => (
          <li
            key={`${fieldPrefix}-${index}`}
            className="rounded-r-md border-l-4 border-slate-300 bg-slate-50/80 px-4 py-3 dark:border-green-900 dark:bg-black/20"
          >
            {item.section_label && (
              <p className="mb-1 font-mono text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-green-700">
                {item.section_label}
              </p>
            )}
            <p className="break-words leading-relaxed text-slate-800 [overflow-wrap:anywhere] dark:text-green-100">
              {item.display_text}
            </p>
            <EvidenceDisclosure
              title={title}
              index={index}
              spans={evidence.get(`${fieldPrefix}[${index}].${evidenceField}`) ?? []}
            />
          </li>
        ))}
      </ol>
    </section>
  );
}

function ExtractionWarnings({ warnings }: { warnings: readonly string[] }) {
  const warningCopy: Record<string, string> = {
    "item_limit_reached:requirements":
      "Only the first 100 extracted requirements are shown.",
    "item_limit_reached:funding_items":
      "Only the first 100 extracted funding items are shown.",
  };
  const messages = warnings.flatMap((warning) =>
    warningCopy[warning] ? [warningCopy[warning]] : [],
  );
  if (warnings.some((warning) => !warningCopy[warning])) {
    messages.push("Some provisions could not be represented in this automated summary.");
  }
  if (messages.length === 0) return null;
  return (
    <ul className="mt-3 space-y-1 border-l-2 border-amber-500 pl-3 text-sm text-amber-900 dark:text-amber-200">
      {messages.map((message) => <li key={message}>{message}</li>)}
    </ul>
  );
}

function V2ContractSection({
  contract,
  value,
}: {
  contract: BillContractItem;
  value: LegalNlpV2ContractJson;
}) {
  const evidence = groupEvidenceByFieldPath(contract.evidence_spans);
  const keyProvisions = value.key_provisions.map((item) => ({
    section_label: item.section_label,
    display_text: item.text,
  }));
  return (
    <section className="mb-6 overflow-hidden rounded-lg border border-slate-400/80 bg-white/85 shadow-sm dark:border-green-800/80 dark:bg-green-950/20 dark:shadow-none">
      <header className="border-b border-slate-300 bg-slate-100/80 px-4 py-3 dark:border-green-900 dark:bg-black/20">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-green-700">
          Structured legislative analysis · beta
        </p>
        <h2 className="mt-1 text-lg font-semibold text-slate-950 dark:text-green-400">
          Legislative contract
        </h2>
        <p className="mt-1 text-xs text-slate-600 dark:text-green-600">
          Schema {contract.schema_version} · Version: {value.version_label}
          {contract.computed_at
            ? ` · Generated ${new Date(contract.computed_at).toLocaleString()}`
            : ""}
        </p>
        <ExtractionWarnings warnings={value.extraction.warnings} />
      </header>

      <div className="space-y-7 p-4">
        <section aria-labelledby="contract-overview">
          <h3
            id="contract-overview"
            className="mb-2 text-sm font-bold uppercase tracking-[0.16em] text-slate-700 dark:text-green-500"
          >
            Overview
          </h3>
          <p className="max-w-4xl break-words text-base leading-relaxed text-slate-800 [overflow-wrap:anywhere] dark:text-green-100">
            {value.plain_summary}
          </p>
        </section>

        <ClaimGroup title="Key provisions" items={keyProvisions} fieldPrefix="key_provisions" evidenceField="text" evidence={evidence} />
        <ClaimGroup title="Requirements" items={value.requirements} fieldPrefix="requirements" evidence={evidence} />
        <ClaimGroup title="Funding" items={value.funding_items} fieldPrefix="funding_items" evidence={evidence} />
        <ClaimGroup title="Timelines" items={value.timeline_items} fieldPrefix="timeline_items" evidence={evidence} />
        <ClaimGroup title="Definitions" items={value.definitions} fieldPrefix="definitions" evidence={evidence} />
        <ClaimGroup title="Applicability" items={value.applicability} fieldPrefix="applicability" evidence={evidence} />
        <ClaimGroup title="Amendments" items={value.amendment_operations} fieldPrefix="amendment_operations" evidence={evidence} />

        {value.limitations.length > 0 && (
          <section aria-labelledby="contract-limitations">
            <h3
              id="contract-limitations"
              className="mb-2 text-sm font-bold uppercase tracking-[0.16em] text-slate-700 dark:text-green-500"
            >
              Limitations
            </h3>
            <ul className="space-y-1 text-sm text-slate-600 dark:text-green-600">
              {value.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
            </ul>
          </section>
        )}
      </div>
    </section>
  );
}

export function ContractSection({ contract }: { contract: BillContractItem }) {
  if (isLegalNlpV2Contract(contract.schema_version, contract.contract_json)) {
    return <V2ContractSection contract={contract} value={contract.contract_json} />;
  }
  return <LegacyContractSection contract={contract} />;
}
