"""Reader stages for latest-action text, matching the client's bill-stage helper.

Unrecognized actions remain 'other'; we do not guess a legislative stage.
"""
import re


def stage_for(status):
    text = (status or "").replace("_", " ").lower().strip()
    if not text:
        return "other"
    if re.search(r"became (public|private) law|signed by president|^enacted\b|^law$", text):
        return "law"
    if re.search(r"^(?:motion|not passed)\b|\b(?:failed|rejected)\b", text):
        return "other"
    if re.search(r"^vetoed\b|^(?:presented|sent) to (?:the )?president|^enrolled\b", text):
        return "both_chambers"
    if re.search(r"received in the (house|senate)", text):
        return "first_chamber"
    if re.search(r"(?:passed|agreed to)(?: house| senate)?(?:/agreed to)? in (?:the )?(house|senate)|passed (?:the )?(house|senate)|engrossed", text):
        return "first_chamber"
    if re.search(r"reported|ordered to be reported|placed on .*calendar|committee|markup|hearing|discharge|referred to", text):
        return "committee"
    if re.search(r"^introduced|introduced in|sponsor introductory", text):
        return "introduced"
    return "other"
