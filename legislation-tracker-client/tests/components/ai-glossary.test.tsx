import { useEffect } from "react";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AiGlossaryProvider, useAiGlossary } from "../../app/bills/[id]/ai-glossary-context";
import { GlossaryEntryView } from "../../app/bills/[id]/bill-brief";
import { buildGlossary } from "../../lib/glossary";
import definitions from "../fixtures/hr7583-definitions.json";
import type { LegalNlpDefinitionItem } from "../../lib/contracts";
import type { BillEnhancement } from "../../lib/api";
import { beginSessionTransition, endSessionTransition } from "../../lib/personalized-scope";

const entry = buildGlossary(definitions as LegalNlpDefinitionItem[])[0];
function Publish({ stale = false, contractId = 10 }: { stale?: boolean; contractId?: number }) {
  const { setEnhancement } = useAiGlossary();
  useEffect(() => {
    setEnhancement({
      status: "succeeded", stale, result: {
        schema_version: "1.3",
        glossary: [{
          definition_id: entry.sources[0].id, contract_id: contractId,
          term: entry.sources[0].term, definition: entry.sources[0].definition,
          text: "A private, source-linked explanation.",
          cited_sources: [{ source_ref: "src_1" }], source_quotes: [],
        }],
      },
    } as unknown as BillEnhancement);
  }, [stale, contractId, setEnhancement]);
  return <GlossaryEntryView entry={entry} contractId={10} document={null} />;
}

describe("private AI glossary", () => {
  it("uses matching definitions without replacing the original legal definition", () => {
    render(<AiGlossaryProvider><Publish /></AiGlossaryProvider>);
    expect(screen.getByText("A private, source-linked explanation.")).toBeInTheDocument();
    expect(screen.getByText("View legal definition")).toBeInTheDocument();
  });
  it.each([{ stale: true }, { contractId: 11 }])("rejects stale or mismatched analysis %j", props => {
    render(<AiGlossaryProvider><Publish {...props} /></AiGlossaryProvider>);
    expect(screen.queryByText("A private, source-linked explanation.")).not.toBeInTheDocument();
    expect(screen.getByText(entry.explanation)).toBeInTheDocument();
  });
  it("clears private explanations when the session changes", () => {
    render(<AiGlossaryProvider><Publish /></AiGlossaryProvider>);
    expect(screen.getByText("A private, source-linked explanation.")).toBeInTheDocument();
    act(() => {
      const scope = beginSessionTransition();
      endSessionTransition(null, scope);
    });
    expect(screen.queryByText("A private, source-linked explanation.")).not.toBeInTheDocument();
  });
});
