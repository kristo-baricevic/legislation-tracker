"""Mechanical provenance/index checks; this does NOT create gold expectations.

Run with Python 3 from any directory. Original .htm snapshots are never changed.
Candidate paragraphs are a review worklist, not a financial extraction result.
"""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class SourceText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_pre = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.in_pre = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False

    def handle_data(self, data):
        if self.in_pre:
            self.parts.append(data)


def normalized(value):
    return " ".join(value.split())


def main():
    manifest = []
    failures = []
    quote_checks = []
    for path in sorted((ROOT / "sources").glob("*.htm")):
        raw = path.read_bytes()
        parser = SourceText()
        parser.feed(raw.decode("utf-8"))
        text = "".join(parser.parts)
        if not text.strip():
            raise ValueError(f"No GovInfo preformatted text in {path.name}")
        # Derived view only. Keep source markup, note/page markers and all words.
        path.with_suffix(".txt").write_text(text, encoding="utf-8")
        manifest.append({
            "package_id": path.stem,
            "retrieved_on": "2026-10-07",
            "source_url": f"https://www.govinfo.gov/content/pkg/{path.stem}/html/{path.name}",
            "raw_file": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "decoded_text_file": str(path.with_suffix(".txt").relative_to(ROOT)),
            "decoded_text_characters": len(text),
        })
        # On the two oversized documents only: retain every matching paragraph,
        # its source location, and an explicitly UNREVIEWED status. This regex is
        # intentionally broad; it neither establishes completeness nor interprets
        # an amount as appropriated money. A full-source manual pass is still due.
        if path.stem in {"PLAW-119publ21", "BILLS-118hr4366enr"}:
            candidates = []
            for match in re.finditer(r"\S[^\n]*(?:\n(?!\s*\n)[^\n]*)*", text):
                paragraph = match.group()
                if re.search(r"\$|\b(?:percent|appropriat\w*|resciss\w*|rescind\w*|fee\w*|funding|such sums|budget authority)\b", paragraph, re.I):
                    candidates.append({
                        "id": f"candidate-{len(candidates)+1:04d}",
                        "status": "unreviewed_not_gold",
                        "start_char": match.start(),
                        "end_char": match.end(),
                        "start_line": text.count("\n", 0, match.start()) + 1,
                        "end_line": text.count("\n", 0, match.end()) + 1,
                        "source_text": paragraph,
                    })
            path.with_suffix(".financial-candidates.json").write_text(
                json.dumps({"status": "UNREVIEWED WORKLIST, NOT AN ANSWER KEY",
                            "complete_financial_coverage": False,
                            "package_id": path.stem,
                            "candidates": candidates}, indent=2) + "\n")
        answer = ROOT / "answers" / (path.stem + ".md")
        if answer.exists():
            blocks = re.findall(r"(?:^>[^\n]*(?:\n|$))+", answer.read_text(), re.M)
            quote_checks.append({"answer": answer.name, "quote_blocks": len(blocks)})
            for index, block in enumerate(blocks, 1):
                quote = normalized("\n".join(line[1:].lstrip() for line in block.splitlines()))
                if quote and quote not in normalized(text):
                    failures.append({"answer": answer.name, "quote_number": index, "quote": quote})
    (ROOT / "sources" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report = {"sources": len(manifest), "answer_quote_checks": quote_checks,
              "total_quote_blocks": sum(item["quote_blocks"] for item in quote_checks),
              "quote_mismatches": failures,
              "scope": "Whitespace-normalized quote containment only; not semantic accuracy, section-location validation, completeness, or human approval."}
    (ROOT / "source-check-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
