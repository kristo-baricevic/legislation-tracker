"""Rebuildable reader wording; source contracts and citation identities stay immutable.

These rules change expression, not legal scope. Unknown constructions are retained,
never truncated or replaced with a guessed legal effect.
"""
import re
import hashlib
import copy

VERSION = "brief-5"
PHRASES = (
    ("prior to", "before"), ("subsequent to", "after"),
    ("in order to", "to"), ("in the event that", "if"),
    ("for the purpose of", "for"), ("notwithstanding", "despite"),
    ("such sums as may be necessary", "whatever funding is needed"),
    ("on an annual basis", "each year"),
    ("on a quarterly basis", "every three months"),
    ("award, on a competitive basis, grants", "award competitive grants"),
    ("not less than", "at least"), ("not more than", "at most"),
    ("with respect to", "for"), ("pursuant to", "under"),
    ("in accordance with", "following"), ("utilize", "use"),
    ("utilization", "use"), ("commence", "begin"),
    ("on the date of enactment", "on the day the bill becomes law"),
)


def explain_line(line):
    text = line.get("display_text") or ""
    # Amendment quotes are instructions to change exact words, not prose to edit.
    if line.get("kind") == "amendment":
        return text
    actor, action = line.get("actor"), line.get("action")
    verbs = {"requirement": ("Requires", "must"), "permission": ("Allows", "may")}
    if actor and action and line.get("kind") in verbs:
        prefix, modal = verbs[line["kind"]]
        original = f"{prefix} {actor} to {action}"
        suffix = text[len(original):]
        if text.startswith(original) and (not suffix or suffix[0] in " .,;:\n"):
            text = f"{actor[0].upper()}{actor[1:]} {modal} {action}{suffix}"
    # Do not alter quoted terms/definitions inside otherwise ordinary provisions.
    parts = re.split(r'(“[^”]*”|"[^"]*")', text)
    for index in range(0, len(parts), 2):
        for source, replacement in PHRASES:
            parts[index] = re.sub(r"\b" + re.escape(source) + r"\b", replacement, parts[index], flags=re.I)
    text = "".join(parts)
    return text[:1].upper() + text[1:]


def build_reader_copy(payload, contract_hash, source_purpose=""):
    return {"version": VERSION, "contract_hash": contract_hash,
            "lines": {line["id"]: explain_line(line) for line in payload.get("line_items", [])},
            "groups": change_groups(payload), "brief": bill_brief(payload, source_purpose)}


def projection(contract):
    saved = contract.reader_copy or {}
    if (saved.get("version") == VERSION and saved.get("contract_hash") == contract.contract_hash
            and all(len(g.get("reader_text", "")) <= 8000 for g in saved.get("groups", []))):
        return saved
    document = getattr(contract, "document", None)
    return build_reader_copy(contract.contract_json, contract.contract_hash, document.source_purpose if document else "")


def _plain(text):
    text = explain_line({"display_text": text})
    replacements = {
        "postsecondary": "college", "participation, retention, and completion rates": "college enrollment, retention, and graduation rates",
        "participation, retention, and completion": "starting, staying in, and finishing college",
        "high-need students": "students facing barriers to education",
        "evidence-based": "research-backed", "fiscal years": "budget years",
        "attainment and completion rates or graduation rates": "completion and graduation rates",
        "eligible entities": "qualifying organizations", "eligible entity": "qualifying organization",
        "on a competitive basis": "through a competition", "shall": "must",
    }
    parts = re.split(r'(“[^”]*”|"[^"]*")', text)
    for index in range(0, len(parts), 2):
        for old, new in replacements.items():
            parts[index] = re.sub(r"\b" + re.escape(old) + r"\b", new, parts[index], flags=re.I)
        parts[index] = re.sub(r"\b([Aa])n qualifying\b", r"\1 qualifying", parts[index])
    return "".join(parts).strip()


def concise_rule(line):
    """Reader projection only: keep the complete legal statement and evidence unchanged."""
    original = explain_line(line)
    if line.get("kind") == "amendment" or re.search(r'["“”]', original):
        return original
    original = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "-", original)
    text = _plain(" ".join(original.split()))
    text = re.sub(r"^(Source text \(not simplified\): )?(?:[\w ,’-]+\.)--(?=\w)", r"\1", text)
    substitutions = (
        (r"From the total amount appropriated to carry out this Act for a fiscal year and not reserved under ([^,]+), the Secretary must reserve", r"From annual funding left after \1, the Secretary must set aside"),
        (r"to award grants to qualifying organizations with applications that propose to include", "for applicants proposing"),
        (r"an evidence tier (\d+) reform or practice", r"a tier \1 approach"),
        (r"evidence tier (\d+) reforms or practices", r"tier \1 approaches"),
        (r"make grants to or enter into contracts with 1 or more organizations to", "give grants or contracts to one or more organizations to"),
        (r"disseminate information on the impact of", "share the effects of"),
        (r"for the purpose of improving the effectiveness of|for improving the effectiveness of", "to improve"),
        (r"research-backed reforms and practices", "research-backed approaches"),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text, flags=re.I)
    # Extract examples only from an explicitly optional enumeration. Never
    # reduce eligibility lists, exclusions, limits, or required combinations.
    if text.startswith("Source text (not simplified):"):
        content = text.split(": ", 1)[1]
        head, sep, examples = content.partition(" that may include the following:")
        if sep and " must " in head and not re.search(r"\b(except|unless|only|subject to|prohibited|shall|must|required|may not|provided that|if)\b", examples, re.I):
            groups = re.split(r"(?:^|\s)\(\d+\)\s+", examples.strip())[1:]
            if groups:
                names = [re.split(r", which may include|, including a combination of|[.;]\s*\(", g, maxsplit=1, flags=re.I)[0].strip(" .;") for g in groups]
                if all(0 < len(n.split()) <= 12 for n in names):
                    head = re.sub(r" that receives a grant under this Act must use the grant funds to carry out the plans submitted under subsection (\([a-z]\)) and for", r" receiving a grant must follow its plan under subsection \1 and fund", head)
                    head = head.replace("research-backed approaches for improving", "research-backed ways to improve")
                    names = [re.sub(r"^Efforts to ", "", n, flags=re.I) for n in names]
                    return f"{head}. Examples: " + "; ".join(n[:1].lower()+n[1:] for n in names) + "."
    return text[:1].upper() + text[1:]


def _heading(line):
    path = line.get("section_path", [])
    # Group an application's nested checklists before pagination, not six
    # independent clauses per screen. Keep different programs/sections apart.
    application = next((i for i, p in enumerate(path) if re.search(r"content(?:s)? of application|application requirements", p.get("heading") or "", re.I)), None)
    if application is not None:
        return path[:application + 1], "Application information"
    meaningful = [(i, p) for i, p in enumerate(path) if p.get("heading") and not re.fullmatch(r"in general|general rule", p["heading"], re.I)]
    if meaningful:
        i, p = meaningful[-1]
        return path[:i + 1], p["heading"].capitalize()
    return path, "What changes"


def _application_overview(lines):
    # Factor only a repeated, identical obligation. Keyword summaries cannot
    # establish modality or preserve the conditions attached to each clause.
    prefix = "An application submitted under this section must include "
    if len(lines) < 2:
        return None
    tails = []
    for line in lines:
        text = line.get("display_text", "")
        if line.get("kind") != "requirement" or not text.startswith(prefix):
            return None
        tail = text[len(prefix):]
        # Keep qualified clauses as separate complete statements, so a final
        # exception cannot accidentally appear to qualify the entire list.
        if not re.fullmatch(r"[^.;:!?]+\.", tail) or re.search(r"\b(if|unless|except|only|provided|subject|not|without)\b", tail, re.I):
            return None
        tails.append(tail[:-1])
    return prefix + "; ".join(dict.fromkeys(tails)) + "."


def change_groups(payload):
    grouped = {}
    for line in payload.get("line_items", []):
        if line.get("kind") == "purpose" or any(re.fullmatch("short title", p.get("heading") or "", re.I) for p in line.get("section_path", [])):
            continue
        path, heading = _heading(line)
        key = tuple((p.get("id"), p.get("label"), p.get("heading")) for p in path) or (line.get("section_id") or line["id"],)
        grouped.setdefault(key, {"path": path, "heading": heading, "lines": []})["lines"].append(line)
    result = []
    for group in grouped.values():
        lines = group["lines"]
        item = copy.deepcopy(lines[0])
        item["id"] = "brief-" + hashlib.sha256("|".join(l["id"] for l in lines).encode()).hexdigest()[:20]
        item["member_ids"] = [l["id"] for l in lines]
        # Compact immutable matching identity; complete text remains in the
        # source evidence and member facts rather than in the API preview.
        item["member_texts"] = [l.get("display_text", "") for l in lines]
        item["display_text"] = "Grouped source " + hashlib.sha256("\n".join(item["member_texts"]).encode()).hexdigest()
        item["section_path"] = copy.deepcopy(group["path"])
        if item["section_path"]:
            item["section_path"][-1]["heading"] = group["heading"]
        for field in ("evidence_paths", "exact_financial_refs", "timeline_refs", "definition_refs"):
            item[field] = list(dict.fromkeys(ref for l in lines for ref in l.get(field, [])))
        item["actor"] = item["action"] = item["effect"] = None
        text = _application_overview(lines) if group["heading"] == "Application information" else None
        if not text:
            statements = list(dict.fromkeys(
                concise_rule(l)
                for l in lines
            ))
            text = _group_overview(statements, group["heading"])
        if len(text) > 8000 and len(lines) > 1:
            # An unknown construction must not turn a whole page into a 400
            # response. Keep its individual source-bound provisions intact;
            # never cut a sentence or discard members to satisfy the API limit.
            for line in lines:
                result.extend(change_groups({"line_items": [line]}))
            continue
        item["reader_text"] = text
        result.append(item)
    return result


def _group_overview(statements, heading):
    # Joined list children can repeat a single reservation as both a duty and
    # a ledger row. Factor the matching chapeau, never add the shares.
    if len(statements) in (2, 3):
        first = re.fullmatch(r"(.+ must set aside at least (\d+(?:\.\d+)?) percent for applicants proposing .+?) at least (\d+) of which is (.+)\.", statements[0])
        if first and statements[1].startswith(first[1] + " the rest of which are "):
            rest = statements[1][len(first[1] + " the rest of which are "):]
            text = f"{first[1]}. At least {first[3]} must be {first[4]}; the rest must be {rest}"
            # Keep a separately extracted ledger statement unless its wording
            # also identifies the same basis, recipients and purpose.
            if len(statements) == 3:
                text += " " + statements[2]
            return text
    # Retain full clauses: a familiar keyword does not establish that the rest
    # of a long provision is optional context rather than a legal condition.
    return " ".join(statements)


def bill_brief(payload, source_purpose=""):
    orientation = payload.get("orientation") or {}
    from ..source_summary import purpose_summary
    purpose = _plain(orientation.get("purpose_clause") or purpose_summary(source_purpose) or "")
    purpose = re.sub(r"^This bill aims to support (?:research-backed )?(.+?) activities designed to ensure the college success of students facing barriers to education\.$",
                     "This bill would fund programs that help students facing barriers start college, stay in school, and graduate.", purpose)
    # Only complete sentences; never invent a total from the financial ledger.
    actions = {f.get("financial_action") for f in payload.get("financial_items", [])}
    phrases = [label for action, label in (
        ("appropriation", "provides funding"), ("authorization", "allows funding"),
        ("set_aside", "sets aside funding for specific uses"), ("allocation", "directs how funding is divided"),
        ("transfer", "moves funding between accounts"), ("rescission", "cancels previously approved funding"),
        ("fee", "sets fees"), ("penalty", "sets financial penalties"),
        ("limitation", "limits how funding can be used"), ("account_rule", "sets rules for using funds"),
    ) if action in actions]
    money = "It " + ", ".join(phrases) + "." if phrases else ""
    rows = payload.get("financial_items") or []
    if rows and all(
        r.get("financial_action") in {"set_aside", "limitation"}
        and r.get("amount_type") in {"percentage", "ceiling"} and not r.get("currency")
        and "appropriat" in (r.get("source_account") or "").lower()
        for r in rows
    ):
        money = "The funding rules set shares, not a dollar total."
        grants = [line for line in payload.get("line_items", [])
                  if line.get("kind") == "requirement" and
                  re.match(r"^award(?:, on a competitive basis,| competitive)? grants to ", line.get("action") or "", re.I)]
        source_id = orientation.get("purpose_line_item_id")
        if len(grants) == 1 and "grant" not in purpose.lower():
            # Keep the purpose intact; identify recipients from the operative
            # award, never from topics, the title, or the name of the bill.
            match = re.fullmatch(r"award(?:, on a competitive basis,| competitive)? grants to ([\w -]+?) to (?:provide|support|carry out) .+", grants[0]["action"], re.I)
            if match:
                recipient = _plain(match[1]).lower()
                if match[1].lower() == "eligible entities":
                    definition = next((d.get("definition") for d in payload.get("definitions", [])
                                       if d.get("term", "").lower() == "eligible entity" and d.get("definition_type") == "means"), None)
                    from .glossary import PARAPHRASES, normalized
                    if definition and ("eligible entity", normalized(definition)) in PARAPHRASES:
                        recipient = "eligible colleges and education partnerships"
                goal = re.fullmatch(r"This bill would fund programs that help (.+)\.", purpose)
                if goal and "competitive" in grants[0]["action"].lower():
                    purpose = f"{recipient.capitalize()} could compete for grants to help {goal[1]}."
                    source_id = grants[0]["id"]
                    money = "The bill sets rules for dividing the grant money, not a dollar total."
        return {"summary": purpose, "money": money, "source_id": source_id}
    return {"summary": purpose, "money": money,
            "source_id": orientation.get("purpose_line_item_id")}


def reader_text(contract, line):
    saved = contract.reader_copy or {}
    if saved.get("version") == VERSION and saved.get("contract_hash") == contract.contract_hash:
        value = saved.get("lines", {}).get(line["id"])
        if isinstance(value, str) and value:
            return value
    return explain_line(line)
