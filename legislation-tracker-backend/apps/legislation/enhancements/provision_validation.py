"""Conservative mechanical checks, not a semantic correctness certificate."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from jsonschema import ValidationError

from .citations import citation_spans
from .source_first_schema import _evidence_ids, validate_source_first_schema
from .source_graph import BARE_REFERENCE, REFERENCE, has_explainable_text


@dataclass(frozen=True)
class Finding:
    code: str
    unit_id: str
    path: str
    evidence_ids: tuple[str, ...]
    outcome: str
    message: str


def _amounts(text):
    multipliers = {
        "": 1,
        "thousand": 1000,
        "million": 1000000,
        "billion": 1000000000,
        "trillion": 1000000000000,
    }
    return {
        Decimal(amount.replace(",", "")) * multipliers[magnitude.lower()]
        for amount, magnitude in re.findall(
            r"\$\s*([\d,]+(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion)\b)?",
            text,
            re.I,
        )
    }


def required_conditions(unit, graph):
    """Source-only scope checklist shared by generation and validation."""
    result = []
    own = "\n".join(graph.passages[pid].text for pid in unit.own_passage_ids)
    governing_sections = {}
    for prefix in re.finditer(r"\bsubject to\s+(?=section\s)", own, re.I):
        reference = REFERENCE.match(own, prefix.end())
        if reference:
            if " ".join(reference[2].split()).casefold() == "this act":
                governing_sections.setdefault(reference[1].casefold(), []).append(
                    tuple(re.findall(r"\([A-Za-z0-9]+\)", reference[0]))
                )
            continue
        reference = BARE_REFERENCE.match(own, prefix.end())
        if reference and reference[0] not in unit.unresolved_dependencies:
            governing_sections.setdefault(reference[1].casefold(), []).append(
                tuple(re.findall(r"\([A-Za-z0-9]+\)", reference[0]))
            )
    # Available background is not automatically a condition on this unit.
    # Preserve structural parent context and explicitly governing references;
    # definitions and other references remain available as evidence, not a
    # requirement to repeat every unrelated rule in their entire section.
    scoped_sources = [(pid, graph.passages[pid].text) for pid in unit.own_passage_ids]
    for pid in unit.context_passage_ids:
        passage = graph.passages[pid]
        label = re.search(
            r"(?:Sec\.|Section)\s+(\d+[A-Za-z]?)", passage.structural_path[0], re.I
        )
        if passage.role == "context":
            scoped_sources.append((pid, passage.text))
        elif label and label[1].casefold() in governing_sections:
            for suffix in governing_sections[label[1].casefold()]:
                if not suffix:
                    scoped_sources.append((pid, passage.text))
                    continue
                from apps.legislation.extraction.federal_structure import (
                    parse_federal_structure,
                )
                from apps.legislation.extraction.types import (
                    ExpectedExtractionRejection,
                )

                try:
                    nodes = parse_federal_structure(passage.text)
                except ExpectedExtractionRejection:
                    nodes = ()
                matches = [
                    node
                    for node in nodes
                    if tuple(
                        item.label for item in node.path if item.label.startswith("(")
                    )
                    == suffix
                ]
                if len(matches) != 1:
                    # Do not silently broaden an unresolved subsection reference
                    # into the entire section. Preserve its explicit qualification.
                    for own_pid in unit.own_passage_ids:
                        for match in re.finditer(
                            r"\bsubject to\s+section\s+"
                            + re.escape(label[1])
                            + "".join(re.escape(part) for part in suffix)
                            + r"(?![\w(])",
                            graph.passages[own_pid].text,
                            re.I,
                        ):
                            result.append(
                                {"text": match.group(), "evidence_ids": [own_pid]}
                            )
                    continue
                selected = matches[0]
                # A cross-referenced exception can contain multiple actions
                # with different conditions. Preserve the whole qualification;
                # disconnected if-tails lose which action each one governs.
                result.append(
                    {"text": selected.span.text.strip(), "evidence_ids": [pid]}
                )
                # Keep each ancestor's introduction, not sibling provisions.
                for ancestor in nodes:
                    if (
                        len(ancestor.path) >= len(selected.path)
                        or selected.path[: len(ancestor.path)] != ancestor.path
                    ):
                        continue
                    children = [
                        node
                        for node in nodes
                        if len(node.path) == len(ancestor.path) + 1
                        and node.path[: len(ancestor.path)] == ancestor.path
                    ]
                    end = min(
                        (node.span.start_char for node in children),
                        default=ancestor.span.end_char,
                    )
                    scoped_sources.append(
                        (pid, passage.text[ancestor.span.start_char : end])
                    )
                    # Plain-text parsing can assign a parent's concluding rule
                    # to its last child. Explicit ancestor-wide scope must not
                    # disappear merely because that child is not selected.
                    tail = passage.text[end : ancestor.span.end_char]
                    scope = (
                        "section"
                        if len(ancestor.path) == 1
                        else "subsection"
                        if len(ancestor.path) == 2
                        else "paragraph"
                    )
                    for match in re.finditer(
                        r"\b(?:for purposes of|under|in|notwithstanding any other provision of)\s+this\s+"
                        + scope
                        + r"\b[^.]*[.]?",
                        tail,
                        re.I,
                    ):
                        scoped_sources.append((pid, match.group()))
    for pid, text in dict.fromkeys(scoped_sources):
        from .source_checklist import MARKER

        boundaries = sorted({0, len(text), *(m.start() for m in MARKER.finditer(text))})
        for left, right in zip(boundaries, boundaries[1:], strict=False):
            block = text[left:right]
            if re.search(r"\bif\s*(?:--|—|:)\s*$", block, re.I):
                # The applicant class/actor before an enumerated if-list is
                # part of eligibility, not disposable introductory wording.
                result.append({"text": block.strip(), "evidence_ids": [pid]})
        for match in re.finditer(
            r"\b(?:only if|if|unless|provided that|only|except)\b(?:[^.]|(?<=\b[A-Z])\.|(?<=\d)\.(?=\d))*[.]?",
            text,
            re.I,
        ):
            result.append({"text": match.group(), "evidence_ids": [pid]})
    return result


def validate_combined(explanations):
    """Flag directly conflicting descriptions of the same cited rule.

    Do not compare unrelated provisions merely because both contain money, nor
    mistake different conditions or actors for a contradiction. Paraphrase-level
    contradictions still require semantic review.
    """
    claims = [
        (row["unit_id"], claim) for row in explanations for claim in row["claims"]
    ]
    findings = []

    def normalize(value):
        return " ".join((value or "").casefold().split())

    for index, (uid, claim) in enumerate(claims):
        for other_uid, other in claims[index + 1 :]:
            shared = set(claim["evidence_ids"]) & set(other["evidence_ids"])
            if uid == other_uid or not shared:
                continue
            if any(
                normalize(claim[k]) != normalize(other[k]) for k in ("actor", "action")
            ):
                continue
            if (
                claim["conditions"] != other["conditions"]
                or claim["exceptions"] != other["exceptions"]
            ):
                continue
            modalities = {claim["modality"], other["modality"]}
            conflict = "prohibited" in modalities and bool(
                modalities & {"required", "permitted"}
            )
            for money in claim["money"]:
                for other_money in other["money"]:
                    fields = (
                        "currency",
                        "measure",
                        "purpose",
                        "period",
                        "base",
                        "comparator",
                    )
                    if all(
                        normalize(money[k]) == normalize(other_money[k]) for k in fields
                    ):
                        conflict |= (
                            money["amount"] is not None
                            and other_money["amount"] is not None
                            and money["amount"] != other_money["amount"]
                        )
            if conflict:
                for affected in (uid, other_uid):
                    findings.append(
                        Finding(
                            "cross_unit_conflict",
                            affected,
                            "claims",
                            tuple(sorted(shared)),
                            "repairable",
                            "Conflicting claims about the same cited rule",
                        )
                    )
    return list({(f.unit_id, f.code): f for f in findings}.values())


def validate_provision(explanation, unit, graph, *, require_coverage=False):
    findings = []

    def add(code, outcome="repairable", path="summary", message=None):
        findings.append(
            Finding(
                code,
                unit.id,
                path,
                unit.own_passage_ids,
                outcome,
                message or code.replace("_", " "),
            )
        )

    try:
        ids = _evidence_ids(explanation)
        if any(pid not in graph.passages for pid in ids):
            add("source_identity", "fatal")
            return findings
        validate_source_first_schema({"provisions": [explanation]}, graph, [unit.id])
    except ValidationError:
        add("invalid_structure")
        return findings
    if explanation["status"] == "unresolved":
        add("provider_unresolved", "unresolved")
        return findings
    if require_coverage:
        from .source_checklist import check_accounting

        for code, path, message in check_accounting(explanation, unit, graph):
            add(code, "unresolved", path, message)
    source = "\n".join(graph.passages[p].text for p in unit.own_passage_ids)
    has_conditions = bool(required_conditions(unit, graph))
    prose = " ".join([explanation["summary"], *explanation["details"]])
    for index, sentence in enumerate([explanation["summary"], *explanation["details"]]):
        if re.search(r"\bassigned\s+(?:items|units|blocks|passages)\b|\btext\s+does\s+not\s+establish\s+the\s+contents\b", sentence, re.I):
            add("source_availability_claim", path=f"explanations/{index}", message="Source availability is supplied by the server, not inferred by generation. Explain the actual rule and preserve its referenced qualifications; do not claim assigned items or supplied text omit provisions that may be elsewhere in the bill.")
        if not re.search(r"[.!?][\"'’”)]*\s*$", sentence):
            add(
                "reader_prose_incomplete",
                path=f"explanations/{index}",
                message="Return complete sentences; split long prose into separate details instead of cutting it off.",
            )
        if re.search(r"\((?:[upsc]\d+)(?:\s*,\s*[upsc]\d+)*\)", sentence):
            add("internal_reference_in_prose", path=f"explanations/{index}")
    if not has_explainable_text(unit, graph):
        add("external_context_unresolved", "unresolved")
    if unit.unresolved_dependencies:
        qualifications = []
        for prefix in re.finditer(r"\bsubject to\s+(?=section\s)", source, re.I):
            ref = REFERENCE.match(source, prefix.end()) or BARE_REFERENCE.match(
                source, prefix.end()
            )
            if ref and ref[0] in unit.unresolved_dependencies:
                qualifications.append(BARE_REFERENCE.match(source, prefix.end())[0])
        visible = " ".join(prose.split()).casefold()
        if any(
            " ".join(ref.split()).casefold() not in visible for ref in qualifications
        ):
            add("external_qualification_omitted", "unresolved")
    # Compare only explicit currency amounts. Other numeric quantities need their
    # units and roles and cannot safely be classified by this lexical detector.
    if _amounts(prose) - _amounts(source):
        add("amount_conflict")
    if re.search(r"\bshall (?:be fined|impose a fine)\b", source, re.I) and re.search(
        r"\b(?:may|might|could) (?:be fined|impose a fine)\b", prose, re.I
    ):
        add("modality_conflict")
    if re.search(r"\bshall not\b", source, re.I) and re.search(
        r"\bmay (?:pay|provide|receive)\b", prose, re.I
    ):
        add("modality_conflict")
    if (
        "secretary of homeland security" in source.casefold()
        and "secretary of state" in prose.casefold()
        and "secretary of state" not in source.casefold()
    ):
        add("actor_conflict")

    def bounds(text):
        result = {}
        pattern = r"\b(not more than|no more than|at most|up to|not less than|no less than|at least|minimum of)\s+(\$\s*)?([\d,]+(?:\.\d+)?)"
        for match in re.finditer(pattern, text, re.I):
            direction = (
                "lower"
                if match[1].lower()
                in {"not less than", "no less than", "at least", "minimum of"}
                else "upper"
            )
            key = (bool(match[2]), Decimal(match[3].replace(",", "")))
            result.setdefault(key, set()).add(direction)
        return result

    original_bounds = bounds(source)
    if any(
        key in original_bounds and not directions <= original_bounds[key]
        for key, directions in bounds(prose).items()
    ):
        add("comparator_conflict")

    def fiscal(value):
        years = set()
        for match in re.finditer(
            r"fiscal years?\s+(\d{4})(?:\s*(?:through|to|[-–])\s*(\d{4}))?", value, re.I
        ):
            start = int(match[1])
            end = int(match[2] or match[1])
            years.update(range(start, end + 1))
        return years

    if fiscal(prose) - fiscal(source):
        add("date_conflict")
    claims = explanation["claims"]
    if re.search(r"\bshall (?:be fined|impose a fine)\b", source, re.I):
        for index, claim in enumerate(claims):
            describes_fine = re.search(
                r"\bfin(?:e|ed)\b", claim["action"], re.I
            ) or any(
                re.search(r"\bfine\b", m["measure"] or "", re.I) for m in claim["money"]
            )
            if describes_fine and claim["modality"] != "required":
                add(
                    "modality_conflict",
                    path=f"claims/{index}/modality",
                    message="The source requires a fine. Represent the mandatory consequence as its own required claim, not as permission or prohibited conduct; retain its maximum and qualifying violation.",
                )
    stated = set()
    for claim in claims:
        for money in claim["money"]:
            if money["amount"] is not None:
                try:
                    stated.add(Decimal(money["amount"].replace(",", "")))
                except InvalidOperation:
                    pass
    financial_action = re.search(
        r"\b(?:shall|may|must)\s+(?:[A-Za-z]+\s+){0,5}"
        r"(?:award|charge|collect|reserve|appropriate|authorize|reimburse|pay|impose|exempt)\w*\b",
        source,
        re.I,
    )
    if _amounts(source) - stated or (
        "financial" in unit.inventory_kinds
        and financial_action
        and not any(c["money"] for c in claims)
    ):
        add("financial_coverage_unverified", "unresolved", "claims.money")
    unspecified_authorizations = re.findall(
        r"authorized to be appropriated[^.]*such sums[^.]*", source, re.I
    )
    represented_authorizations = [
        m
        for c in claims
        for m in c["money"]
        if m["amount"] is None and "authoriz" in (m["measure"] or "").casefold()
    ]
    if len(represented_authorizations) < len(unspecified_authorizations):
        add("financial_coverage_unverified", "unresolved", "claims.money")
    financial_percentage = re.search(
        r"\bpercent(?:age)?\s+of\s+"
        r"(?:(?:the|a|an|total|annual|gross|net|adjusted|Federal|remaining|aggregate|monthly)\s+)*"
        r"(?:amounts?|sums?|appropriat\w*|funds?|grants?|loans?|fees?|income|earnings|salary|wages|pay|poverty|costs?|expenses?|revenue|assets?|debt|tax\w*|benefits?|budgets?)\b",
        source,
        re.I,
    )
    percentage_entries = [
        m
        for c in claims
        for m in c["money"]
        if re.search(r"percent|%", m["measure"] or "", re.I)
    ]
    if (
        financial_percentage and not any(m["base"] for c in claims for m in c["money"])
    ) or any(not m["base"] for m in percentage_entries):
        add("percentage_base_unverified", "unresolved", "claims.money.base")
    if has_conditions and not any(c["conditions"] for c in claims):
        add("conditions_unverified", "unresolved", "claims.conditions")
    # Exact source leaves are conservative evidence for preserved conditions;
    # paraphrased logic requires independent review, not keyword certification.
    condition_leaves = []
    for claim_index, claim in enumerate(claims):
        for node in [claim["conditions"], *claim["exceptions"]]:
            pending = [node] if node else []
            while pending:
                current = pending.pop()
                if current["operator"] == "leaf":
                    condition_leaves.append(current["text"])
                    supported = any(
                        citation_spans(graph.passages[p].text, current["text"])
                        for p in current["evidence_ids"]
                    )
                    if not supported:
                        add(
                            "condition_meaning_unverified",
                            "unresolved",
                            f"claims/{claim_index}/conditions",
                        )
                else:
                    pending.extend(current["children"])
        for money in claim["money"]:
            if money["currency"] is None and re.match(
                r"(?:calendar |business |consecutive |aggregate )?(?:days?|months?|years?|hours?|students?|persons?|people)\b",
                (money["measure"] or "").strip(),
                re.I,
            ):
                add(
                    "nonfinancial_quantity",
                    path=f"claims/{claim_index}/money",
                    message="Durations and counts are not financial provisions. Preserve the quantity in the action or conditions, not money.",
                )
            percentage_values = {
                Decimal(value.replace(",", ""))
                for value in re.findall(
                    r"([\d,]+(?:\.\d+)?)\s*(?:percent\b|%)", source, re.I
                )
            }
            try:
                is_percentage = (
                    money["currency"] is None
                    and bool(re.search(r"percent|%", money["measure"] or "", re.I))
                    and Decimal((money["amount"] or "").replace(",", ""))
                    in percentage_values
                )
            except InvalidOperation:
                is_percentage = False
            if (
                _amounts(source)
                and money["amount"] is not None
                and money["currency"] != "USD"
                and not is_percentage
            ):
                add("currency_conflict", path=f"claims/{claim_index}/money")
            if money["currency"] == "USD" and money["amount"] is not None:
                try:
                    amount = Decimal(money["amount"].replace(",", ""))
                except InvalidOperation:
                    add("invalid_amount", path="claims.money.amount")
                else:
                    if amount not in _amounts(source):
                        add("amount_conflict", path="claims.money.amount")
    if has_conditions and condition_leaves:
        # Require the full governing tail in one leaf. Splitting a conjunction
        # into fragments cannot establish its Boolean scope. Complex sources
        # that do not fit are explicitly unresolved, never silently shortened.
        def normalize(value):
            return " ".join(value.split()).casefold()

        tails = [item["text"] for item in required_conditions(unit, graph)]
        missing = [
            tail
            for tail in tails
            if not any(citation_spans(leaf, tail) for leaf in condition_leaves)
        ]
        if missing:
            add(
                "condition_scope_unverified",
                "unresolved",
                "claims.conditions",
                message="Missing complete source conditions: " + " | ".join(missing),
            )
    return list({(f.code, f.path): f for f in findings}.values())
