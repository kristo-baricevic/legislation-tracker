"""Rebuildable reader wording; source contracts and citation identities stay immutable.

These rules change expression, not legal scope. Unknown constructions are retained,
never truncated or replaced with a guessed legal effect.
"""
import re
import hashlib
import copy

VERSION = "brief-1"
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
    text = re.sub(r"\s*\(\d+ U\.S\.C\.[^)]*\)", "", text)
    replacements = {
        "postsecondary": "college", "participation, retention, and completion rates": "college enrollment, retention, and graduation rates",
        "participation, retention, and completion": "starting, staying in, and finishing college",
        "high-need students": "students facing barriers to education",
        "evidence-based": "research-backed", "fiscal years": "budget years",
        "attainment and completion rates or graduation rates": "completion and graduation rates",
        "eligible entities": "qualifying organizations", "eligible entity": "qualifying organization",
        "on a competitive basis": "through a competition", "shall": "must",
    }
    for old, new in replacements.items():
        text = re.sub(r"\b" + re.escape(old) + r"\b", new, text, flags=re.I)
    text = re.sub(r"\b([Aa])n qualifying\b", r"\1 qualifying", text)
    return " ".join(text.split()).strip()


def _heading(line):
    path = line.get("section_path", [])
    # Group an application's nested checklists before pagination, not six
    # independent clauses per screen. Keep different programs/sections apart.
    application = next((i for i, p in enumerate(path) if re.search(r"content(?:s)? of application|application requirements", p.get("heading") or "", re.I)), None)
    if application is not None:
        return path[:application + 1], "What applicants must explain"
    meaningful = [(i, p) for i, p in enumerate(path) if p.get("heading") and not re.fullmatch(r"in general|general rule", p["heading"], re.I)]
    if meaningful:
        i, p = meaningful[-1]
        return path[:i + 1], p["heading"].capitalize()
    return path, "What changes"


def _application_overview(lines):
    raw = " ".join(l.get("display_text", "") for l in lines)
    subjects = []
    for pattern, label in (
        (r"plan to increase|implement|use the grant|use grant|grant funds", "what they will do"),
        (r"demographic|high.need|students enrolled|enrolled students", "which students they will help"),
        (r"evaluat|benchmark|outcome", "how they will measure results"),
        (r"Pell Grant", "how many students receive Pell Grants"),
        (r"sustain|after.*grant|continue", "how the work will continue after funding ends"),
    ):
        if re.search(pattern, raw, re.I):
            subjects.append(label)
    if not subjects:
        return None
    # A high-level list of required application information, not a statement
    # that an applicant qualifies or that these are the only requirements.
    return "Applicants must explain " + ", ".join(subjects[:-1]) + (", and " if len(subjects) > 1 else "") + subjects[-1] + "."


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
        text = _application_overview(lines) if group["heading"] == "What applicants must explain" else None
        if not text:
            statements = list(dict.fromkeys(_plain(explain_line(l)) for l in lines))
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
    raw = " ".join(statements)
    if len(raw.split()) <= 45:
        return raw
    # These describe the governing action, not the exhaustive eligibility test.
    # The original clauses and all monetary records remain independently stored.
    if re.search(r"must use the grant funds to carry out the plans", raw, re.I):
        examples = [label for pattern, label in (("tutor", "tutoring"), ("emergency financial", "emergency aid"), ("career", "career support"), ("counsel", "advising")) if re.search(pattern, raw, re.I)]
        return "Grant recipients must carry out their approved plans." + (" Allowed support includes " + ", ".join(examples) + "." if examples else "")
    if re.search(r"must submit an application", raw, re.I):
        return "Qualifying applicants must apply and follow the required timing, format, and information rules."
    if re.search(r"evaluations? .*must measure|must.*evaluate.*effectiveness", raw, re.I):
        return "The program must be evaluated to check whether it works." + (" Evaluators must compare participants’ results with those of similar people who did not participate." if "comparing" in raw else "")
    if re.search(r"must (?:reserve|set aside)|Sets aside", raw):
        return "Funding must be set aside for " + _plain(heading).removeprefix("Reservation of funds for ").lower() + ". The Money tab shows the amounts and funding rules."
    if re.search(r"may (?:reserve|set aside)", raw):
        purposes = list(dict.fromkeys(re.findall(r"percent for ([^.]+)", raw)))
        if purposes and len(" ".join(purposes).split()) <= 30:
            return "Some funding may be used for " + "; or ".join(purposes) + "."
    grant = re.search(r"For each of budget years (\d{4} through \d{4}), (.+?) must award competitive grants to (.+?) to (.+)\.$", raw)
    if grant:
        return f"From {grant[1]}, {grant[2]} must offer competitive grants to {grant[3]}. The grants would {_plain(grant[4])}."
    # Never drop an exception to produce a seemingly unconditional benefit.
    # Unknown long constructions stay faithful until a source-bound AI overview
    # is available; this is intentionally not word-count truncation.
    return raw


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
    return {"summary": purpose, "money": money,
            "source_id": orientation.get("purpose_line_item_id")}


def reader_text(contract, line):
    saved = contract.reader_copy or {}
    if saved.get("version") == VERSION and saved.get("contract_hash") == contract.contract_hash:
        value = saved.get("lines", {}).get(line["id"])
        if isinstance(value, str) and value:
            return value
    return explain_line(line)
