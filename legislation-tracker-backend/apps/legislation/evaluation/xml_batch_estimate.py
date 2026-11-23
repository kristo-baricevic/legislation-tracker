"""Offline sizing scenario. Never dispatches, loads credentials, or saves output."""
from ..enhancements.providers.base import ProviderResult, ProviderUsage
from ..enhancements.reader_citations import citation_passages
from ..enhancements.reader_summary import summarize_review


def summary_scenario(plan):
    findings = []
    for source in plan.source_snapshot:
        if not source.get("discovery_source"):
            continue
        for passage in citation_passages(source):
            if passage["quote_id"]:
                # One 160-character finding per selectable passage. Cite the
                # real passage so the production reducer packs actual evidence.
                findings.append({"text": "x"*160, "source_quotes": [
                    {"source_ref": source["source_ref"], "quote": passage["text"]}]})
    sizes = []

    class LocalCounter:
        def enhance_bill(self, *, request, **unused):
            sizes.append(len(request.request_bytes))
            wire = request.request_envelope["source_packet"]["sources"][0]
            citation = {"source_ref": wire["source_ref"],
                        "quote_id": next(q["quote_id"] for q in wire["citation_passages"] if q["quote_id"])}
            return ProviderResult({"schema_version":"1.4", "explanations": [],
                "summary":[{"text":"Offline sizing placeholder.", "source_quotes":[citation]}]},
                ProviderUsage(0,0,0), "", "")

    summarize_review(plan, {"policy_changes": findings}, LocalCounter(), None, lambda: None,
                     plan.source_manifest["budget"]["maximum_calls"]-len(plan.reader_batches))
    return {"summary_calls":len(sizes), "summary_request_bytes":sum(sizes)}
