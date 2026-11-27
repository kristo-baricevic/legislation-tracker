"""Public funding copy is rendered from pinned evidence, including on historical reads."""

import re
from dataclasses import dataclass

_SIGNAL = re.compile(
    r"[$€£]|\b(?:USD|dollars?|appropriat\w*|fund(?:s|ed|ing)?|grants?|"
    r"spend(?:s|ing)?|spent|allocat\w*|disburs\w*|outlays?|payments?|"
    r"budget|subsid\w*|obligat(?:e|ed|es)|financ(?:e|es|ing))\b",
    re.I,
)
# Only rewrite a whole, affirmative decision. Capture the entire quantity and
# qualifier tail verbatim: ranges, fiscal periods and exceptions stay attached.
_DECISION = re.compile(
    r"(?:(?P<actor>The [A-Za-z -]+?) (?P<modal>shall|may|must) "
    r"(?P<verb>pay|spend|allocate|provide|obligate|disburse)|"
    r"There (?:is|are) (?P<authority>authorized to be appropriated|appropriated)) "
    r"(?P<quantity>(?:(?:a total of|at least|at most|not more than|not less than|"
    r"between|exactly|up to) )?\$\d[\d,]*(?:\.\d+)?(?: (?:thousand|million|billion|trillion))?"
    r"(?: and \$\d[\d,]*(?:\.\d+)?(?: (?:thousand|million|billion|trillion))?)?)"
    r"(?P<qualifiers>(?: [^.!?;]+)?)[.]?",
    re.I,
)
UNRESOLVED = "The funding terms could not be verified from the cited bill text."


def funding_context(texts):
    return any(_SIGNAL.search(text) for text in texts if isinstance(text, str))


@dataclass(frozen=True)
class PublicFundingDecision:
    actor: str
    predicate: str
    quantity: str
    qualifications: str

    @classmethod
    def from_passage(cls, passage):
        match = _DECISION.fullmatch(passage)
        if not match:
            return None
        # Keep purpose, period and prerequisite together as source text. Unknown
        # syntax or missing purpose is quoted; never infer that a restriction ends.
        tail = match["qualifiers"]
        if not re.search(r"\bfor\s+[\w-]+", tail, re.I):
            return None
        authority = match["authority"]
        if authority:
            verb = (
                "authorizes appropriations of"
                if authority.lower().startswith("authorized")
                else "appropriates"
            )
            return cls("The bill", verb, match["quantity"], tail)
        modal = match["modal"].lower()
        predicate = f"{'must' if modal == 'shall' else modal} {match['verb']}"
        return cls(match["actor"], predicate, match["quantity"], tail)

    def render(self):
        return f"{self.actor} {self.predicate} {self.quantity}{self.qualifications}."


def public_funding_text(proposed, passages):
    """Return source-owned wording. The proposal can select an exact quote only."""
    passages = list(dict.fromkeys(p.strip() for p in passages if p and p.strip()))
    if not passages:
        return UNRESOLVED
    source = "\n\n".join(passages)
    if proposed == source:
        return source
    decision = PublicFundingDecision.from_passage(source)
    return decision.render() if decision else source


def project_staged_item(item, category, sources):
    # A selected substring can omit a trailing prerequisite. Use the complete
    # pinned passages containing the citations when rendering financial copy.
    citations = item.get("cited_sources", [])
    excerpts = [s["quoted_text"] for s in citations]
    fields = (
        "text",
        "title",
        "label",
        "amount_display",
        "actor",
        "action",
        "conditions",
        "why_it_matters",
        "unresolved_reason",
        "explanation",
    )
    if not (
        category == "financial_items"
        or item.get("kind") in {"funding", "financial_item"}
        or funding_context([*excerpts, *(item.get(k) for k in fields)])
    ):
        return
    if item.get("status") == "unresolved":
        item["unresolved_reason"] = UNRESOLVED
        return
    cited_refs = {s["source_ref"] for s in citations}
    passages = [
        sources[ref]["quoted_text"]
        for ref in sorted(
            cited_refs, key=lambda ref: (sources[ref].get("start_char") or 0, ref)
        )
    ]
    copy = public_funding_text(item.get("text"), passages)
    if "text" in item:
        item["text"] = copy
    if category == "obligations":
        item.update(
            funding_text=copy,
            actor="",
            modality="unspecified",
            action=copy,
            conditions=None,
        )
    if "explanation" in item:
        item["explanation"] = copy
    if "title" in item:
        item["title"] = "Funding provision"
    if "amount_display" in item:
        decision = PublicFundingDecision.from_passage(" ".join(passages))
        label = {
            "appropriates": "Appropriation",
            "authorizes appropriations of": "Authorization",
        }
        item.update(
            label=(
                label.get(decision.predicate, "Financial provision")
                if decision
                else "Financial provision"
            ),
            amount_display=decision.quantity if decision else "",
            fiscal_years=[
                year
                for year in item.get("fiscal_years", [])
                if any(re.search(rf"\bfiscal year {year}\b", p, re.I) for p in passages)
            ],
        )
    if "why_it_matters" in item:
        item["why_it_matters"] = "See the cited bill text."


def project_provisions(result):
    summaries = {}
    for row in result["provisions"]:
        if row["status"] != "explained":
            continue
        ordered = sorted(row["evidence"], key=lambda p: p.get("start", 0))
        evidence = [p["text"] for p in ordered]
        funding = any(c["money"] for c in row["claims"]) or funding_context(
            [
                row["summary"],
                *row["details"],
                *evidence,
                *(c["action"] for c in row["claims"]),
            ]
        )
        if funding:
            row["summary"] = public_funding_text(row["summary"], evidence)
            # Keep a single complete statement including all cited qualifications.
            row["details"] = []
            from .source_first_schema import _evidence_ids

            for claim in row["claims"]:
                refs = set(_evidence_ids(claim))
                passages = [p["text"] for p in ordered if p["id"] in refs]
                if claim["money"] or funding_context([claim["action"], *passages]):
                    wording = public_funding_text(None, passages)
                    claim.update(
                        funding_text=wording,
                        actor=None,
                        action=wording,
                        modality="unspecified",
                        conditions=None,
                        exceptions=[],
                        money=[],
                    )
        summaries[row["unit_id"]] = row["summary"]
    synopsis = result["synopsis"]
    if synopsis["status"] != "unavailable":
        synopsis["text"] = " ".join(
            summaries[uid] for uid in synopsis["explanation_ids"]
        )
    return result
