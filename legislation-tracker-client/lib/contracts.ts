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
    | "purpose"
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

export const LEGAL_NLP_SECTION_LEVELS = [
  "division",
  "title",
  "subtitle",
  "chapter",
  "subchapter",
  "part",
  "subpart",
  "account",
  "subaccount",
  "subsubaccount",
  "subsubsubaccount",
  "article",
  "subdivision",
  "section",
  "appropriations_paragraph",
  "subsection",
  "paragraph",
  "subparagraph",
  "clause",
  "subclause",
  "item",
  "subitem",
] as const;

export type LegalNlpSectionLevel = (typeof LEGAL_NLP_SECTION_LEVELS)[number];

export interface LegalNlpSectionPathItem {
  level: LegalNlpSectionLevel;
  label: string;
  heading: string | null;
}

export type FinancialAction =
  | "appropriation"
  | "authorization"
  | "allocation"
  | "transfer"
  | "rescission"
  | "reduction"
  | "cancellation"
  | "set_aside"
  | "limitation"
  | "other_explicit";

export type FinancialDirection =
  | "increase"
  | "decrease"
  | "neutral_transfer"
  | "limit";

export interface LegalNlpFinancialPreview {
  id: string;
  display_text: string;
  financial_action: FinancialAction;
  direction: FinancialDirection;
  amount: string | null;
  amount_type: "specified" | "such_sums" | "percentage" | "ceiling";
  currency: "USD" | null;
  fiscal_years: number[];
}

export interface LegalNlpTimelinePreview {
  id: string;
  display_text: string;
  timeline_type: "absolute" | "relative" | "effective";
  date: string | null;
  relative_value: number | null;
  relative_unit: "days" | "months" | "years" | null;
  trigger: string | null;
}

export interface LegalNlpLineItem {
  id: string;
  source_id: string;
  section_id: string;
  section_path: LegalNlpSectionPathItem[];
  kind:
    | "requirement"
    | "prohibition"
    | "permission"
    | "amendment"
    | "applicability"
    | "financial"
    | "timeline";
  display_text: string;
  actor: string | null;
  action: string | null;
  effect: string | null;
  exact_financial_count: number;
  exact_financial_preview: LegalNlpFinancialPreview[];
  timeline_count: number;
  timeline_preview: LegalNlpTimelinePreview[];
  definition_count: number;
}

export interface LegalNlpFinancialItem extends LegalNlpFinancialPreview {
  source_id: string;
  section_id: string;
  section_label: string | null;
  section_path: LegalNlpSectionPathItem[];
  purpose: string | null;
  source_account: string | null;
  destination_account: string | null;
}

export interface LegalNlpTimelinePublicItem extends LegalNlpTimelinePreview {
  source_id: string;
  section_id: string;
  section_label: string | null;
  section_path: LegalNlpSectionPathItem[];
}

export interface LegalNlpDefinitionItem {
  id: string;
  source_id: string;
  section_id: string;
  section_label: string | null;
  section_path: LegalNlpSectionPathItem[];
  display_text: string;
  term: string;
  definition: string;
  definition_type: "means" | "includes" | "excludes";
}

export interface LegalNlpSectionSupplement {
  section_id: string;
  section_path: LegalNlpSectionPathItem[];
  section_financial_count: number;
  section_timeline_count: number;
}

export interface LegalNlpReaderStats {
  line_item_count: number;
  financial_item_count: number;
  timeline_item_count: number;
  definition_item_count: number;
  section_group_count: number;
}

export interface LegalNlpReaderOrientation {
  purpose_clause: string | null;
  purpose_line_item_id: string | null;
}

interface ContractSummaryBase {
  id: number;
  schema_version: string;
  contract_hash: string;
  computed_at: string;
  document: number | null;
  document_version_label: string | null;
}

export interface LegalNlpV21ContractSummary extends ContractSummaryBase {
  schema_version: "2.1-legal-nlp";
  coverage_note: string;
  orientation: LegalNlpReaderOrientation;
  reader_stats: LegalNlpReaderStats;
}

export interface LegacyContractSummary extends ContractSummaryBase {
  coverage_note: null;
  orientation: null;
  reader_stats: null;
}

export type BillContractSummary = LegalNlpV21ContractSummary | LegacyContractSummary;

export interface PageResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface LegalNlpReaderItemsPage extends PageResponse<LegalNlpLineItem> {
  section_supplements: LegalNlpSectionSupplement[];
}

export type LegalNlpFinancialItemsPage = PageResponse<LegalNlpFinancialItem>;
export type LegalNlpTimelineItemsPage = PageResponse<LegalNlpTimelinePublicItem>;
export type LegalNlpDefinitionItemsPage = PageResponse<LegalNlpDefinitionItem>;

export interface LegalNlpEvidenceItem {
  start_char: number;
  end_char: number;
  quoted_text: string;
  page_number: number | null;
}

export type LegalNlpEvidencePage = PageResponse<LegalNlpEvidenceItem>;

export interface OfficialSummaryResponse {
  summary: string | null;
  summary_source: string | null;
  summary_action_date: string | null;
  summary_version_code: string | null;
  summary_last_updated_at: string | null;
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

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

function isIdentifier(value: unknown): value is string {
  return (
    isNonEmptyString(value) &&
    /^[a-z][a-z0-9_-]*-[0-9]+(?:-[0-9]+)?$/.test(value)
  );
}

function isNullableNonEmptyString(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function isSectionPathItem(value: unknown): value is LegalNlpSectionPathItem {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["level", "label", "heading"]) &&
    LEGAL_NLP_SECTION_LEVELS.includes(value.level as LegalNlpSectionLevel) &&
    isNonEmptyString(value.label) &&
    isNullableNonEmptyString(value.heading)
  );
}

function isSectionPath(value: unknown): value is LegalNlpSectionPathItem[] {
  return Array.isArray(value) && value.length > 0 && value.every(isSectionPathItem);
}

const FINANCIAL_ACTIONS: readonly FinancialAction[] = [
  "appropriation",
  "authorization",
  "allocation",
  "transfer",
  "rescission",
  "reduction",
  "cancellation",
  "set_aside",
  "limitation",
  "other_explicit",
];

const FINANCIAL_DIRECTIONS: readonly FinancialDirection[] = [
  "increase",
  "decrease",
  "neutral_transfer",
  "limit",
];

function isFinancialPreview(value: unknown): value is LegalNlpFinancialPreview {
  if (!isRecord(value)) return false;
  return (
    hasExactKeys(value, [
      "id",
      "display_text",
      "financial_action",
      "direction",
      "amount",
      "amount_type",
      "currency",
      "fiscal_years",
    ]) &&
    isIdentifier(value.id) &&
    isNonEmptyString(value.display_text) &&
    FINANCIAL_ACTIONS.includes(value.financial_action as FinancialAction) &&
    FINANCIAL_DIRECTIONS.includes(value.direction as FinancialDirection) &&
    (value.amount === null ||
      (typeof value.amount === "string" && /^[0-9]+(?:\.[0-9]{2})$/.test(value.amount))) &&
    ["specified", "such_sums", "percentage", "ceiling"].includes(
      value.amount_type as string,
    ) &&
    (value.currency === "USD" || value.currency === null) &&
    Array.isArray(value.fiscal_years) &&
    value.fiscal_years.every(
      (year) => Number.isInteger(year) && year >= 1000 && year <= 9999,
    )
  );
}

function isTimelinePreview(value: unknown): value is LegalNlpTimelinePreview {
  if (!isRecord(value)) return false;
  return (
    hasExactKeys(value, [
      "id",
      "display_text",
      "timeline_type",
      "date",
      "relative_value",
      "relative_unit",
      "trigger",
    ]) &&
    isIdentifier(value.id) &&
    isNonEmptyString(value.display_text) &&
    ["absolute", "relative", "effective"].includes(value.timeline_type as string) &&
    (value.date === null ||
      (typeof value.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value.date))) &&
    (value.relative_value === null || isNonNegativeInteger(value.relative_value)) &&
    (["days", "months", "years"].includes(value.relative_unit as string) ||
      value.relative_unit === null) &&
    isNullableNonEmptyString(value.trigger)
  );
}

function hasUniqueIds(values: readonly { id: string }[]): boolean {
  return new Set(values.map((item) => item.id)).size === values.length;
}

export function isLegalNlpLineItem(value: unknown): value is LegalNlpLineItem {
  if (!isRecord(value)) return false;
  if (
    !hasExactKeys(value, [
      "id",
      "source_id",
      "section_id",
      "section_path",
      "kind",
      "display_text",
      "actor",
      "action",
      "effect",
      "exact_financial_count",
      "exact_financial_preview",
      "timeline_count",
      "timeline_preview",
      "definition_count",
    ]) ||
    !isIdentifier(value.id) ||
    !isIdentifier(value.source_id) ||
    !isIdentifier(value.section_id) ||
    !isSectionPath(value.section_path) ||
    ![
      "purpose",
      "requirement",
      "prohibition",
      "permission",
      "amendment",
      "applicability",
      "financial",
      "timeline",
    ].includes(value.kind as string) ||
    !isNonEmptyString(value.display_text) ||
    !isNullableNonEmptyString(value.actor) ||
    !isNullableNonEmptyString(value.action) ||
    !isNullableNonEmptyString(value.effect) ||
    !isNonNegativeInteger(value.exact_financial_count) ||
    !Array.isArray(value.exact_financial_preview) ||
    value.exact_financial_preview.length > 3 ||
    !value.exact_financial_preview.every(isFinancialPreview) ||
    !hasUniqueIds(value.exact_financial_preview) ||
    value.exact_financial_preview.length > value.exact_financial_count ||
    !isNonNegativeInteger(value.timeline_count) ||
    !Array.isArray(value.timeline_preview) ||
    value.timeline_preview.length > 3 ||
    !value.timeline_preview.every(isTimelinePreview) ||
    !hasUniqueIds(value.timeline_preview) ||
    value.timeline_preview.length > value.timeline_count ||
    !isNonNegativeInteger(value.definition_count)
  ) {
    return false;
  }
  return true;
}

export function isLegalNlpFinancialItem(value: unknown): value is LegalNlpFinancialItem {
  if (!isRecord(value)) return false;
  const preview = {
    id: value.id,
    display_text: value.display_text,
    financial_action: value.financial_action,
    direction: value.direction,
    amount: value.amount,
    amount_type: value.amount_type,
    currency: value.currency,
    fiscal_years: value.fiscal_years,
  };
  return (
    hasExactKeys(value, [
      ...Object.keys(preview),
      "source_id",
      "section_id",
      "section_label",
      "section_path",
      "purpose",
      "source_account",
      "destination_account",
    ]) &&
    isFinancialPreview(preview) &&
    isIdentifier(value.source_id) &&
    isIdentifier(value.section_id) &&
    isStringOrNull(value.section_label) &&
    isSectionPath(value.section_path) &&
    isNullableNonEmptyString(value.purpose) &&
    isNullableNonEmptyString(value.source_account) &&
    isNullableNonEmptyString(value.destination_account)
  );
}

export function isLegalNlpTimelineItem(
  value: unknown,
): value is LegalNlpTimelinePublicItem {
  if (!isRecord(value)) return false;
  const preview = {
    id: value.id,
    display_text: value.display_text,
    timeline_type: value.timeline_type,
    date: value.date,
    relative_value: value.relative_value,
    relative_unit: value.relative_unit,
    trigger: value.trigger,
  };
  return (
    hasExactKeys(value, [
      ...Object.keys(preview),
      "source_id",
      "section_id",
      "section_label",
      "section_path",
    ]) &&
    isTimelinePreview(preview) &&
    isIdentifier(value.source_id) &&
    isIdentifier(value.section_id) &&
    isStringOrNull(value.section_label) &&
    isSectionPath(value.section_path)
  );
}

export function isLegalNlpDefinitionItem(
  value: unknown,
): value is LegalNlpDefinitionItem {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "id",
      "source_id",
      "section_id",
      "section_label",
      "section_path",
      "display_text",
      "term",
      "definition",
      "definition_type",
    ]) &&
    isIdentifier(value.id) &&
    isIdentifier(value.source_id) &&
    isIdentifier(value.section_id) &&
    isStringOrNull(value.section_label) &&
    isSectionPath(value.section_path) &&
    isNonEmptyString(value.display_text) &&
    isNonEmptyString(value.term) &&
    isNonEmptyString(value.definition) &&
    ["means", "includes", "excludes"].includes(value.definition_type as string)
  );
}

function isPageResponse<T>(
  value: unknown,
  itemGuard: (item: unknown) => item is T,
): value is PageResponse<T> {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["count", "next", "previous", "results"]) ||
    !isNonNegativeInteger(value.count) ||
    !(value.next === null || isNonEmptyString(value.next)) ||
    !(value.previous === null || isNonEmptyString(value.previous)) ||
    !Array.isArray(value.results) ||
    value.results.length > value.count ||
    !value.results.every(itemGuard)
  ) {
    return false;
  }
  const results = value.results as T[];
  const ids = results
    .map((item) => (isRecord(item) ? item.id : undefined))
    .filter((id): id is string | number =>
      typeof id === "string" || typeof id === "number",
    );
  return new Set(ids).size === ids.length;
}

export function isLegalNlpFinancialItemsPage(
  value: unknown,
): value is LegalNlpFinancialItemsPage {
  return isPageResponse(value, isLegalNlpFinancialItem);
}

export function isLegalNlpTimelineItemsPage(
  value: unknown,
): value is LegalNlpTimelineItemsPage {
  return isPageResponse(value, isLegalNlpTimelineItem);
}

export function isLegalNlpDefinitionItemsPage(
  value: unknown,
): value is LegalNlpDefinitionItemsPage {
  return isPageResponse(value, isLegalNlpDefinitionItem);
}

function isSectionSupplement(value: unknown): value is LegalNlpSectionSupplement {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "section_id",
      "section_path",
      "section_financial_count",
      "section_timeline_count",
    ]) &&
    isIdentifier(value.section_id) &&
    isSectionPath(value.section_path) &&
    isNonNegativeInteger(value.section_financial_count) &&
    isNonNegativeInteger(value.section_timeline_count)
  );
}

export function isLegalNlpReaderItemsPage(
  value: unknown,
): value is LegalNlpReaderItemsPage {
  if (!isRecord(value)) return false;
  const base = {
    count: value.count,
    next: value.next,
    previous: value.previous,
    results: value.results,
  };
  if (
    !hasExactKeys(value, [
      "count",
      "next",
      "previous",
      "results",
      "section_supplements",
    ]) ||
    !isPageResponse(base, isLegalNlpLineItem) ||
    !Array.isArray(value.section_supplements) ||
    !value.section_supplements.every(isSectionSupplement)
  ) {
    return false;
  }
  const results = value.results as LegalNlpLineItem[];
  const supplements = value.section_supplements as LegalNlpSectionSupplement[];
  const sectionIds = new Set(results.map((item) => item.section_id));
  const supplementIds = supplements.map((item) => item.section_id);
  return (
    new Set(supplementIds).size === supplementIds.length &&
    supplementIds.every((id) => sectionIds.has(id))
  );
}

function isEvidenceItem(value: unknown): value is LegalNlpEvidenceItem {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["start_char", "end_char", "quoted_text", "page_number"]) &&
    isNonNegativeInteger(value.start_char) &&
    isPositiveInteger(value.end_char) &&
    value.end_char > value.start_char &&
    isNonEmptyString(value.quoted_text) &&
    (value.page_number === null || isPositiveInteger(value.page_number))
  );
}

export function isLegalNlpEvidencePage(value: unknown): value is LegalNlpEvidencePage {
  return isPageResponse(value, isEvidenceItem);
}

function isReaderOrientation(value: unknown): value is LegalNlpReaderOrientation {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["purpose_clause", "purpose_line_item_id"])
  ) {
    return false;
  }
  const bothNull = value.purpose_clause === null && value.purpose_line_item_id === null;
  const bothPresent =
    isNonEmptyString(value.purpose_clause) && isIdentifier(value.purpose_line_item_id);
  return bothNull || bothPresent;
}

function isReaderStats(value: unknown): value is LegalNlpReaderStats {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "line_item_count",
      "financial_item_count",
      "timeline_item_count",
      "definition_item_count",
      "section_group_count",
    ]) &&
    Object.values(value).every(isNonNegativeInteger)
  );
}

const CONTRACT_SUMMARY_KEYS = [
  "id",
  "schema_version",
  "contract_hash",
  "computed_at",
  "document",
  "document_version_label",
  "coverage_note",
  "orientation",
  "reader_stats",
] as const;

function hasContractSummaryBase(value: Record<string, unknown>): boolean {
  return (
    hasExactKeys(value, CONTRACT_SUMMARY_KEYS) &&
    isPositiveInteger(value.id) &&
    isNonEmptyString(value.schema_version) &&
    isNonEmptyString(value.contract_hash) &&
    isNonEmptyString(value.computed_at) &&
    (value.document === null || isPositiveInteger(value.document)) &&
    isStringOrNull(value.document_version_label)
  );
}

export function isLegalNlpV21ContractSummary(
  value: unknown,
): value is LegalNlpV21ContractSummary {
  return (
    isRecord(value) &&
    hasContractSummaryBase(value) &&
    value.schema_version === "2.1-legal-nlp" &&
    isNonEmptyString(value.coverage_note) &&
    isReaderOrientation(value.orientation) &&
    isReaderStats(value.reader_stats)
  );
}

export function isBillContractSummary(value: unknown): value is BillContractSummary {
  if (isLegalNlpV21ContractSummary(value)) return true;
  return (
    isRecord(value) &&
    hasContractSummaryBase(value) &&
    value.schema_version !== "2.1-legal-nlp" &&
    value.coverage_note === null &&
    value.orientation === null &&
    value.reader_stats === null
  );
}

export function isBillContractSummariesPage(
  value: unknown,
): value is PageResponse<BillContractSummary> {
  return isPageResponse(value, isBillContractSummary);
}

export function isOfficialSummaryResponse(
  value: unknown,
): value is OfficialSummaryResponse {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "summary",
      "summary_source",
      "summary_action_date",
      "summary_version_code",
      "summary_last_updated_at",
    ]) &&
    isStringOrNull(value.summary) &&
    isStringOrNull(value.summary_source) &&
    isStringOrNull(value.summary_action_date) &&
    isStringOrNull(value.summary_version_code) &&
    isStringOrNull(value.summary_last_updated_at)
  );
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
