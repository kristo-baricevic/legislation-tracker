"""Official chamber passage without individual roll-call positions."""
import re
from datetime import date


def extract_passage_actions(actions, *, source_url):
    found = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        text = action.get("text")
        if not isinstance(text, str):
            continue
        try:
            day = date.fromisoformat(action.get("actionDate", "")).isoformat()
        except (ValueError, TypeError):
            continue
        wording = re.sub(r"^Passed/agreed to in (?:House|Senate):\s*", "", text, flags=re.I)
        chamber_match = re.match(r"Passed (Senate|House)\b", wording, re.I)
        chamber = chamber_match.group(1).title() if chamber_match else None
        if not chamber and re.match(r"On motion to (?:suspend the rules and )?pass (?:the bill|the measure)\b.*?Agreed to by voice vote\b", wording, re.I):
            chamber = "House"
        if not chamber:
            continue
        method = None
        if re.search(r"by unanimous consent\b", wording, re.I):
            method = "unanimous_consent"
        elif re.search(r"by (?:a )?voice vote\b", wording, re.I):
            method = "voice_vote"
        if method:
            found.setdefault((day, chamber, method), {
                "date": day, "chamber": chamber, "method": method,
                "source_text": text, "source_url": source_url,
            })
    return sorted(found.values(), key=lambda item: (item["date"], item["chamber"]), reverse=True)
