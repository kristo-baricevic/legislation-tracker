"""Lossless presentation grouping of accepted policy drafts."""

import copy
import re


def section_assignments(preflight, items):
    sources = {
        s["source_ref"]: s
        for s in preflight.source_snapshot
        if s.get("discovery_source")
    }
    text = "".join(
        s["quoted_text"]
        for s in sorted(sources.values(), key=lambda s: s["start_char"])
    )
    boundaries, depth = [0], 0
    for match in re.finditer(
        r"\[\[QUOTED_BLOCK_START\]\]|\[\[QUOTED_BLOCK_END\]\]|^(?:SEC\.|SECTION)\s",
        text,
        re.M | re.I,
    ):
        if match.group().upper() == "[[QUOTED_BLOCK_START]]":
            depth += 1
        elif match.group().upper() == "[[QUOTED_BLOCK_END]]":
            depth = max(0, depth - 1)
        elif depth == 0:
            boundaries.append(match.start())
    boundaries = sorted({*boundaries, len(text)})
    ranges = list(zip(boundaries, boundaries[1:]))
    grouped = {}
    for index, item in enumerate(items):
        weights = [0] * len(ranges)
        for q in item["source_quotes"]:
            source = sources[q["source_ref"]]
            start = source["start_char"] + source["quoted_text"].index(q["quote"])
            end = start + len(q["quote"])
            for i, (a, b) in enumerate(ranges):
                weights[i] += max(0, min(end, b) - max(start, a))
        section = max(range(len(weights)), key=weights.__getitem__)
        # Very large sections can contain many independent programs; retain the
        # source-chunk subdivision rather than force them into one paragraph.
        key = (
            section,
            (
                item["source_quotes"][0]["source_ref"]
                if ranges[section][1] - ranges[section][0] > 16000
                else ""
            ),
        )
        grouped.setdefault(key, []).append(index)
    return [grouped[key] for key in sorted(grouped)]


def group_policy_drafts(preflight, items):
    """Join whole accepted drafts; never paraphrase, clip or drop conditions.

    This preserves draft meaning, not proof of the draft's legal accuracy.
    Long groups stay as multiple paginated entries with their original evidence.
    """
    result = []
    for members in section_assignments(preflight, items):
        current = None
        for index in members:
            item = copy.deepcopy(items[index])
            combined = f"{current['text']} {item['text']}" if current else ""
            if (
                current
                and current["title"] == item["title"]
                and len(combined.split()) <= 55
                and len(combined) < 410
            ):
                current["text"] = combined
                for quote in item["source_quotes"]:
                    if quote not in current["source_quotes"]:
                        current["source_quotes"].append(quote)
            else:
                current = item
                result.append(current)
    return result
