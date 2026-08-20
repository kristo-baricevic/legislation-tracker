export interface EvidenceSpanItem {
  field_path: string;
  start_char: number;
  end_char: number;
  quoted_text: string;
  page_number: number | null;
}

export interface LegacyContractJson {
  [key: string]: unknown;
  schema_version?: string;
  plain_summary?: string;
  source_excerpt?: string;
}

export interface LegalNlpExtractionMetadata {
  method: "federal-rules";
  parser_version: "2.0.0";
  sections_seen: number;
  sections_with_claims: number;
  warnings: string[];
}

export interface LegalNlpKeyProvision {
  kind:
    | "requirement"
    | "funding"
    | "timeline"
    | "definition"
    | "applicability"
    | "amendment";
  section_label: string | null;
  heading: string | null;
  text: string;
}

export interface LegalNlpRequirement {
  section_label: string | null;
  display_text: string;
  modality: "required" | "prohibited" | "permitted";
  actor: string | null;
  action: string;
  object: string | null;
  conditions: string[];
}

export interface LegalNlpFundingItem {
  section_label: string | null;
  display_text: string;
  amount: string | null;
  amount_type: "specified" | "such_sums";
  currency: "USD" | null;
  fiscal_years: number[];
  purpose: string | null;
}

export interface LegalNlpTimelineItem {
  section_label: string | null;
  display_text: string;
  timeline_type: "absolute" | "relative" | "effective";
  date: string | null;
  relative_value: number | null;
  relative_unit: "days" | "months" | "years" | null;
  trigger: string | null;
}

export interface LegalNlpDefinition {
  section_label: string | null;
  display_text: string;
  term: string;
  definition: string;
  definition_type: "means" | "includes" | "excludes";
}

export interface LegalNlpApplicabilityItem {
  section_label: string | null;
  display_text: string;
  subject: string;
  scope: string;
  applicability_type: "applies" | "does_not_apply" | "eligible" | "excluded";
}

export interface LegalNlpAmendmentOperation {
  section_label: string | null;
  display_text: string;
  target: string | null;
  operation:
    | "add"
    | "insert"
    | "strike"
    | "strike_and_insert"
    | "replace"
    | "redesignate"
    | "repeal"
    | "amend";
  removed_text: string | null;
  inserted_text: string | null;
}

export interface LegalNlpV2ContractJson {
  schema_version: "2.0-legal-nlp";
  title: string;
  version_label: string;
  extraction: LegalNlpExtractionMetadata;
  plain_summary: string;
  key_provisions: LegalNlpKeyProvision[];
  requirements: LegalNlpRequirement[];
  funding_items: LegalNlpFundingItem[];
  timeline_items: LegalNlpTimelineItem[];
  definitions: LegalNlpDefinition[];
  applicability: LegalNlpApplicabilityItem[];
  amendment_operations: LegalNlpAmendmentOperation[];
  limitations: string[];
}

export type ContractJson = LegacyContractJson | LegalNlpV2ContractJson;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isRecordArray(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every(isRecord);
}

function hasDisplayItemShape(value: Record<string, unknown>): boolean {
  return isStringOrNull(value.section_label) && typeof value.display_text === "string";
}

function hasExtractionShape(value: unknown): value is LegalNlpExtractionMetadata {
  return (
    isRecord(value) &&
    value.method === "federal-rules" &&
    value.parser_version === "2.0.0" &&
    Number.isInteger(value.sections_seen) &&
    Number.isInteger(value.sections_with_claims) &&
    isStringArray(value.warnings)
  );
}

export function isLegalNlpV2Contract(
  schemaVersion: string,
  value: unknown,
): value is LegalNlpV2ContractJson {
  if (schemaVersion !== "2.0-legal-nlp" || !isRecord(value)) return false;
  if (
    value.schema_version !== "2.0-legal-nlp" ||
    typeof value.title !== "string" ||
    typeof value.version_label !== "string" ||
    typeof value.plain_summary !== "string" ||
    !hasExtractionShape(value.extraction) ||
    !isStringArray(value.limitations)
  ) {
    return false;
  }

  const keyProvisions = value.key_provisions;
  const requirements = value.requirements;
  const fundingItems = value.funding_items;
  const timelineItems = value.timeline_items;
  const definitions = value.definitions;
  const applicability = value.applicability;
  const amendmentOperations = value.amendment_operations;
  if (
    !isRecordArray(keyProvisions) ||
    !isRecordArray(requirements) ||
    !isRecordArray(fundingItems) ||
    !isRecordArray(timelineItems) ||
    !isRecordArray(definitions) ||
    !isRecordArray(applicability) ||
    !isRecordArray(amendmentOperations)
  ) {
    return false;
  }

  if (
    !keyProvisions.every(
      (item) =>
        typeof item.kind === "string" &&
        isStringOrNull(item.section_label) &&
        isStringOrNull(item.heading) &&
        typeof item.text === "string",
    )
  ) {
    return false;
  }
  if (
    ![
      ...requirements,
      ...fundingItems,
      ...timelineItems,
      ...definitions,
      ...applicability,
      ...amendmentOperations,
    ].every(hasDisplayItemShape)
  ) {
    return false;
  }

  return true;
}

export function getContractSummary(value: unknown): string | null {
  if (!isRecord(value)) return null;
  return typeof value.plain_summary === "string" ? value.plain_summary : null;
}

export function groupEvidenceByFieldPath(
  spans: readonly EvidenceSpanItem[],
): ReadonlyMap<string, readonly EvidenceSpanItem[]> {
  const grouped = new Map<string, EvidenceSpanItem[]>();
  for (const span of spans) {
    const existing = grouped.get(span.field_path) ?? [];
    existing.push(span);
    grouped.set(span.field_path, existing);
  }
  for (const values of grouped.values()) {
    values.sort((left, right) =>
      left.start_char === right.start_char
        ? left.end_char - right.end_char
        : left.start_char - right.start_char,
    );
  }
  return grouped;
}
