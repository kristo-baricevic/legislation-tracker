import type { BillEnhancement, ReaderExplanationItem } from "./api";

export interface ReaderIdentity {
  contractId: number | null;
  contractHash: string | null;
  documentId: number | null;
}

export function compatibleReader(enhancement: BillEnhancement | null, identity: ReaderIdentity | null) {
  if (!identity || !enhancement || enhancement.status !== "succeeded" ||
      !(enhancement.source_compatible ?? !enhancement.stale) ||
      enhancement.result?.schema_version !== "1.4") return null;
  const result = enhancement.result;
  const saved = result.identity;
  // Document-only reviews have no NLP contract to bind to. Only the server
  // can verify their content hash; require its affirmative compatibility check.
  if (identity.contractId === null && (identity.contractHash !== null ||
      identity.documentId === null || enhancement.source_compatible !== true || !result.source_review)) return null;
  if (saved.contract_id !== identity.contractId || saved.contract_hash !== identity.contractHash ||
      saved.document_id !== identity.documentId) return null;
  return result;
}

export function resolveReaderExplanation(
  enhancement: BillEnhancement | null, identity: ReaderIdentity | null,
  kind: ReaderExplanationItem["kind"], itemId: string, original: string,
) {
  const result = compatibleReader(enhancement, identity);
  if (!result) return null;
  const item = result.explanations.find(t => t.kind === kind && t.item_id === itemId);
  if (!item || item.status !== "explained" || !item.text?.trim() ||
      !item.cited_sources.length || item.original_text !== original ||
      item.contract_id !== result.identity.contract_id ||
      item.contract_hash !== result.identity.contract_hash ||
      item.document_id !== result.identity.document_id ||
      item.document_content_hash !== result.identity.document_content_hash) return null;
  return item;
}
