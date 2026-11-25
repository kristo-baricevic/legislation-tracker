"""Exact, scoped source dependencies for bounded full-document review.

Ownership and interpretation are separate. A small legal unit stays complete in
each request that owns part of it; a large unit contributes its introductions,
continuations, referenced provisions and applicable definitions instead of all
of its unrelated siblings. XML ancestry takes precedence over text heuristics.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.types import ExpectedExtractionRejection

CONTEXT_PLANNER_VERSION = 1
UNIT_BYTES = 24_000
CONTAINERS = {
    "legis-body",
    "engrossed-amendment-body",
    "amendment-body",
    "division",
    "title",
    "subtitle",
    "chapter",
    "subchapter",
    "part",
    "subpart",
    "tgroup",
    "tbody",
}
NAVIGATION = {"toc", "table-of-contents"}
LEVELS = (
    "section",
    "subsection",
    "paragraph",
    "subparagraph",
    "clause",
    "subclause",
    "item",
    "subitem",
)
REFERENCE = re.compile(
    r"\b(?P<kind>section|subsection|paragraph|subparagraph|clause|subclause|item|subitem)s?\s+"
    r"(?P<label>\d+(?:\.\d+)*[A-Za-z]?(?:-[A-Za-z0-9]+)*|(?:\([A-Za-z0-9]+\))+)"
    r"(?P<suffix>(?:\([A-Za-z0-9]+\))*)",
    re.I,
)
SCOPE = re.compile(
    r"\bthis\s+(Act|division|title|subtitle|chapter|subchapter|part|subpart|section|subsection|paragraph|subparagraph)\b",
    re.I,
)
QUALIFICATION = re.compile(
    r"\b(?:except|unless|only if|may not|shall not|must not|notwithstanding|"
    r"no (?:funds|amounts)|nothing in|prohibit\w*|limitation\w*|"
    r"(?:shall|may) (?:not )?apply|applies|applicable|remain available|"
    r"effective date|takes? effect|terminat\w*|sunset)\b",
    re.I,
)
DEFINITION = re.compile(
    r"\b(?:the\s+)?term\s+[\"“‘`']*(?P<term>[^\n;:.]{1,120}?)"
    r"[\"”’`']*\s+(?:means|includes|has the meaning|shall mean)\b",
    re.I,
)
QUOTED_DEFINITION = re.compile(
    r"[\"“‘](?P<term>[^\"”’\n]{1,100})[\"”’]\s+(?:means|includes)\b", re.I
)


@dataclass(frozen=True)
class Node:
    start: int
    end: int
    tag: str
    label: str = ""
    heading: str = ""
    parent: int | None = None
    identity: str = ""
    quoted_depth: int = 0
    references: tuple[str, ...] = ()
    table_label_level: int | None = None


def _label(value):
    return re.sub(r"^(?:Sec\.|Section)\s*", "", value, flags=re.I).strip().rstrip(".")


def _normalize(value):
    return " ".join(value.casefold().split()).strip("‘’“”\"'` .;:")


def _text_nodes(text, sections):
    """Recognized text hierarchy, scoped to authoritative section boundaries.

    Never infer title/section ancestry from flattened XML when XML nodes exist.
    A section-only caller retains exact local offsets without promoting quoted
    section headings into siblings of the enclosing bill section.
    """
    result = []
    if sections:
        for identity, start, end, label, heading in sections:
            root = len(result)
            result.append(
                Node(start, end, "section", _label(label), heading, identity=identity)
            )
            try:
                parsed = parse_federal_structure("SEC. 0. SOURCE\n" + text[start:end])
            except ExpectedExtractionRejection:
                parsed = ()
            prefix = len("SEC. 0. SOURCE\n")
            parents = {}
            for item in parsed:
                if item.span.start_char < prefix or item.level not in LEVELS[1:]:
                    continue
                a, b = (
                    start + item.span.start_char - prefix,
                    min(end, start + item.span.end_char - prefix),
                )
                parent_item = parsed.parents.get(id(item))
                parent = parents.get(id(parent_item), root)
                parents[id(item)] = len(result)
                result.append(
                    Node(a, b, item.level, item.label, item.heading or "", parent)
                )
    else:
        try:
            parsed = parse_federal_structure(text)
        except ExpectedExtractionRejection:
            parsed = ()
        indexes = {}
        for item in parsed:
            parent = indexes.get(id(parsed.parents.get(id(item))))
            indexes[id(item)] = len(result)
            result.append(
                Node(
                    item.span.start_char,
                    item.span.end_char,
                    item.level,
                    _label(item.label),
                    item.heading or "",
                    parent,
                )
            )
    if not result:
        result = [Node(0, len(text), "section", identity="document")]
    return result


class DependencyIndex:
    def __init__(self, text, sections):
        self.text = text
        xml = getattr(sections, "provisions", ())
        self.nodes = (
            [
                Node(
                    p.start,
                    p.end,
                    p.tag,
                    _label(p.label),
                    p.heading,
                    p.parent,
                    getattr(p, "identity", ""),
                    p.quoted_depth,
                    getattr(p, "references", ()),
                    getattr(p, "table_label_level", None),
                )
                for p in xml
            ]
            if xml
            else _text_nodes(text, sections)
        )
        self.children = defaultdict(list)
        self._ancestors, self._quotes = [], []
        for i, node in enumerate(self.nodes):
            self.children[node.parent].append(i)
            ancestors = (
                (node.parent, *self._ancestors[node.parent])
                if node.parent is not None
                else ()
            )
            self._ancestors.append(ancestors)
            self._quotes.append(
                i
                if node.tag in {"quoted-block", "quoted-text"}
                else self._quotes[node.parent]
                if node.parent is not None
                else None
            )
        self._required = {}
        self.by_identity = {
            n.identity: i for i, n in enumerate(self.nodes) if n.identity
        }
        self.direct = [self._direct(i) for i in range(len(self.nodes))]
        self.direct_text = [
            "\n".join(text[a:b] for a, b in spans) for spans in self.direct
        ]
        self.sections = defaultdict(list)
        for i, node in enumerate(self.nodes):
            if node.tag == "section":
                self.sections[self.quote_scope(i), node.label.casefold()].append(i)
        self.definitions = defaultdict(list)
        self.qualifications = defaultdict(list)
        self.links = defaultdict(set)
        self.introduction_links = defaultdict(set)
        self.table_authorizations = defaultdict(set)
        self.tables_under = defaultdict(list)
        for i, node in enumerate(self.nodes):
            if node.tag == "table":
                for ancestor in self.ancestors(i):
                    self.tables_under[ancestor].append(i)
        self.unresolved = defaultdict(set)
        self._index_dependencies()

    def _direct(self, index):
        node = self.nodes[index]
        cursor, spans = node.start, []
        for child in self.children[index]:
            item = self.nodes[child]
            if cursor < item.start:
                spans.append((cursor, item.start))
            cursor = max(cursor, item.end)
        if cursor < node.end:
            spans.append((cursor, node.end))
        return spans

    def ancestors(self, index):
        return self._ancestors[index]

    def quote_scope(self, index):
        return self._quotes[index]

    def scope(self, index, level):
        quote = self.quote_scope(index)
        if level.casefold() == "act":
            return quote
        for i in (index, *self.ancestors(index)):
            if self.nodes[i].tag == level.casefold() and self.quote_scope(i) == quote:
                return i
        return quote

    def _definition_scope(self, index, raw):
        declaration = re.search(
            r"\b(?:in|for purposes of|as used in)\s+this\s+(Act|division|title|subtitle|chapter|section|subsection|paragraph)\b",
            raw,
            re.I,
        )
        if declaration:
            return self.scope(index, declaration[1])
        for ancestor in self.ancestors(index):
            introduction = self.direct_text[ancestor]
            declaration = re.search(
                r"\b(?:in|for purposes of|as used in)\s+this\s+(Act|division|title|subtitle|chapter|section|subsection)\b",
                introduction,
                re.I,
            )
            if declaration:
                return self.scope(index, declaration[1])
            if self.nodes[ancestor].tag == "section":
                break
        # A definition subsection inherits its legal section. A standalone
        # definitions section inherits the nearest title/division (or bill).
        section = self.scope(index, "section")
        if (
            section is not None
            and "definition" not in self.nodes[section].heading.casefold()
        ):
            return section
        for i in self.ancestors(index):
            if self.nodes[i].tag in {"subtitle", "title", "division"}:
                return i
        return self.quote_scope(index)

    def _descendant(self, index, scope):
        return (
            (scope is None and self.quote_scope(index) is None)
            or index == scope
            or scope in self.ancestors(index)
        )

    def _path_target(self, index, labels):
        current = [index]
        for label in labels:
            following = []
            for parent in current:
                for child in self.children[parent]:
                    if self.nodes[child].label.casefold() == label.casefold():
                        following.append(child)
            current = following
        return current

    def _external_amendment(self, index):
        if self.quote_scope(index) is not None:
            return False
        operation = external = False
        for i in (index, *self.ancestors(index)):
            raw = self.direct_text[i]
            operation = operation or bool(
                re.search(r"\b(?:amend\w*|striking|inserting|repeal\w*)\b", raw, re.I)
            )
            external = external or bool(
                re.search(
                    r"\b(?:United States Code|U\.S\.C\.|Public Law|title\s+\d+|such (?:section|subsection|Act))\b|\bof\s+(?!this\s+Act\b)[^.;]{1,100}\bAct\b",
                    raw,
                    re.I,
                )
            )
            if operation and external:
                return True
            if self.nodes[i].tag == "section":
                break
        return False

    def _reference_targets(self, index, match, raw, *, after=None):
        kind, label = match["kind"].casefold(), match["label"]
        suffix = re.findall(r"\([A-Za-z0-9]+\)", match["suffix"])
        after = raw[match.end() : match.end() + 100] if after is None else after
        qualified = re.match(
            r"\s+of\s+(?!this\s+(?:Act|section|subsection|paragraph)\b)", after, re.I
        )
        if qualified:
            return []
        if (
            self._external_amendment(index)
            and not re.match(
                r"\s+of\s+this\s+(?:Act|section|subsection)\b", after, re.I
            )
            and not re.search(
                r"\b(?:added|amended|redesignated|transferred|inserted)\s+by\s*$",
                raw[: match.start()],
                re.I,
            )
        ):
            return []
        if kind == "section":
            candidates = self.sections.get(
                (self.quote_scope(index), label.casefold()), []
            )
            # Bare section numbers inside instructions amending another law
            # are not numbers in the current bill.
            explicit_local = re.match(r"\s+of\s+this\s+Act\b", after, re.I)
            if (
                not explicit_local
                and self.quote_scope(index) is None
                and re.search(r"\b(?:amend\w*|striking|inserting)\b", raw, re.I)
            ):
                return []
            return (
                self._path_target(candidates[0], suffix) if len(candidates) == 1 else []
            )
        labels = re.findall(r"\([A-Za-z0-9]+\)", label) + suffix
        if not labels:
            return []
        rank = LEVELS.index(kind)
        enclosing = next(
            (
                i
                for i in (index, *self.ancestors(index))
                if self.nodes[i].tag in LEVELS[:rank]
                and self.quote_scope(i) == self.quote_scope(index)
            ),
            None,
        )
        return self._path_target(enclosing, labels) if enclosing is not None else []

    def _index_dependencies(self):
        for i, node in enumerate(self.nodes):
            if node.tag in NAVIGATION:
                continue
            raw = self.direct_text[i]
            normalized = " ".join(raw.split())
            for pattern in (DEFINITION, QUOTED_DEFINITION):
                for match in pattern.finditer(normalized):
                    term = _normalize(match["term"])
                    if term:
                        self.definitions[term].append(
                            (self._definition_scope(i, normalized), i)
                        )
            if QUALIFICATION.search(normalized):
                for match in SCOPE.finditer(normalized):
                    scope = self.scope(i, match[1])
                    level = match[1].casefold()
                    if level not in LEVELS:
                        # Mere mentions of enactment, authorization or an
                        # amendment by "this Act" do not make a local rule a
                        # restriction on every other provision of the bill.
                        preceding = normalized[
                            max(0, match.start() - 140) : match.start()
                        ]
                        explicit = re.search(
                            r"\b(?:nothing|no provision)\s+in\s*$", preceding, re.I
                        ) or re.search(
                            r"\b(?:no|none of the)\s+(?:funds|amounts)\b[^.;:]{0,120}$",
                            preceding,
                            re.I,
                        )
                        if re.search(
                            r"\b(?:according to|provides that|states that|made available to carry out)\b",
                            normalized[: match.start()],
                            re.I,
                        ):
                            explicit = False
                        if not explicit or (scope is None and level != "act"):
                            continue
                    if scope != i:
                        self.qualifications[scope].append(i)
            for identity in node.references:
                if identity in self.by_identity:
                    self.links[i].add(self.by_identity[identity])
            for match in REFERENCE.finditer(normalized):
                if (
                    node.tag == "section"
                    and match.start() == 0
                    and match["kind"].casefold() == "section"
                    and match["label"].casefold() == node.label.casefold()
                ):
                    continue  # A rendered section heading is not a cross-reference.
                # A plural reference shares its final qualification: resolve
                # each member of "sections 2 and 3 of this Act", including
                # lists of relative subsection/paragraph paths.
                cursor, members = match.end(), [match]
                while extra := re.match(
                    r"\s*(?:,\s*(?:(?:and|or)\s+)?|(?:and|or)\s+)(\d+(?:\.\d+)*[A-Za-z]?(?:\([A-Za-z0-9]+\))*|(?:\([A-Za-z0-9]+\))+)(?![A-Za-z0-9])",
                    normalized[cursor:],
                ):
                    synthetic = REFERENCE.match(match["kind"] + " " + extra[1])
                    members.append(synthetic)
                    cursor += extra.end()
                after = normalized[cursor : cursor + 100]
                targets = []
                for member in members:
                    resolved = self._reference_targets(
                        i,
                        member,
                        normalized if member is match else member[0],
                        after=after,
                    )
                    if not resolved:
                        self.unresolved[i].add(member[0])
                    targets.extend(resolved)
                if not targets:
                    self.unresolved[i].add(match[0])
                preceding = normalized[max(0, match.start() - 160) : match.start()]
                amendment_identity = re.search(
                    r"\b(?:amendments?\s+(?:made|effected)|(?:law|provision)\s+amended|changes?\s+made)\s+by\s*$",
                    preceding,
                    re.I,
                )
                amendment_identity = amendment_identity or (
                    re.search(
                        r"\bas\s+(?:added|redesignated|transferred)\s+by\s*$",
                        preceding,
                        re.I,
                    )
                )
                identity_frame = re.search(
                    r"\b(?:shall (?:take effect|be executed|continue in effect)|remains? in effect|is amended as follows|by conforming|by striking any heading)\b",
                    normalized,
                    re.I,
                ) or any(
                    re.search(
                        r"^(?:savings(?: provision| clause)?|(?:further )?technical amendments|coordination with other amendments.*|conforming amendments)$",
                        self.nodes[a].heading,
                        re.I,
                    )
                    for a in (i, *self.ancestors(i))
                )
                amendment_identity = (
                    amendment_identity
                    and identity_frame
                    and not re.search(
                        r"\b(?:means|has the meaning|defined|subject to|requirements?|conditions?|eligibility|entitled|pursuant to)\b",
                        normalized,
                        re.I,
                    )
                )
                table_reference = re.search(
                    r"\bfunding\s+table\b[^.;]{0,100}$", preceding, re.I
                ) and re.search(
                    r"\b(?:authorized to be appropriated|hereby appropriated|authorization of appropriations)\b",
                    normalized,
                    re.I,
                )
                for target in targets:
                    # A precise provision inserted into another statute is
                    # available evidence, not an unavailable external citation.
                    # E.g. 'section 6100 of title 10, as added by section 1'
                    # resolves to quoted section 6100 inside bill section 1.
                    inserted = []
                    if re.search(r"\bas\s+added\s+by\s*$", preceding, re.I):
                        prior = list(REFERENCE.finditer(normalized[: match.start()]))
                        if prior and prior[-1]["kind"].casefold() == "section":
                            reference = prior[-1]
                            inserted = [
                                j
                                for (_, label), candidates in self.sections.items()
                                if label == reference["label"].casefold()
                                for j in candidates
                                if self.quote_scope(j) is not None
                                and target in self.ancestors(j)
                            ]
                            if len(inserted) == 1:
                                suffix = re.findall(
                                    r"\([A-Za-z0-9]+\)", reference["suffix"]
                                )
                                inserted = self._path_target(inserted[0], suffix)
                            else:
                                inserted = []
                            if inserted:
                                self.unresolved[i].discard(reference[0])
                    if inserted:
                        self.links[i].discard(target)
                        self.links[i].update(inserted)
                    elif amendment_identity:
                        self.links[i].discard(target)
                        self.introduction_links[i].add(target)
                    elif table_reference and self.tables_under[target]:
                        # The authorization owns the legal authority, while
                        # each separately owned table row carries its amount.
                        # Give rows that authority too; never interpret a table
                        # labeled 'authorized' as money actually appropriated.
                        self.links[i].discard(target)
                        self.introduction_links[i].add(target)
                        for table in self.tables_under[target]:
                            self.table_authorizations[table].add(i)
                    else:
                        self.links[i].add(target)
                # A sibling can qualify an earlier action by referring back to
                # it. Outbound references from the action do not find this rule.
                if re.search(
                    r"\b(?:may not|shall not|must not|only if|unless|no funds|prohibit\w*|subject to|condition\w*|matching|eligible|eligibility)\b",
                    normalized,
                    re.I,
                ):
                    for target in targets:
                        if self.scope(i, "section") == self.scope(target, "section"):
                            self.links[target].add(i)
        alternatives = sorted(self.definitions, key=len, reverse=True)
        for term in tuple(alternatives):
            if term.endswith("y") and len(term) > 1 and term[-2] not in "aeiou":
                plural = term[:-1] + "ies"
            elif term.endswith(("s", "x", "ch", "sh")):
                plural = term + "es"
            else:
                plural = term + "s"
            self.definitions[plural].extend(self.definitions[term])
        alternatives = sorted(self.definitions, key=len, reverse=True)
        self.definition_pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(t) for t in alternatives)
                + r")(?!\w)",
                re.I,
            )
            if alternatives
            else None
        )
        self.definition_links = defaultdict(set)
        if self.definition_pattern:
            for i, raw in enumerate(self.direct_text):
                if self.nodes[i].tag in NAVIGATION:
                    continue
                for match in self.definition_pattern.finditer(_normalize(raw)):
                    for scope, defining in self.definitions[_normalize(match[0])]:
                        if self._descendant(i, scope):
                            self.definition_links[i].add(defining)
        table_parts = defaultdict(lambda: {"heads": [], "labels": [], "rows": []})
        for i, node in enumerate(self.nodes):
            table = next(
                (p for p in self.ancestors(i) if self.nodes[p].tag == "table"), None
            )
            if table is None:
                continue
            if node.tag == "thead":
                table_parts[table]["heads"].append(i)
            elif node.tag == "row":
                table_parts[table]["rows"].append(i)
                if node.table_label_level is not None:
                    table_parts[table]["labels"].append(i)
        for parts in table_parts.values():
            active = {}
            for row in parts["rows"]:
                self.links[row].update(parts["heads"])
                level = self.nodes[row].table_label_level
                if level is not None:
                    active = {
                        rank: heading
                        for rank, heading in active.items()
                        if rank < level
                    }
                    active[level] = row
                self.links[row].update(
                    heading for heading in active.values() if heading != row
                )

    def ownership_units(self):
        """Yield disjoint ranges; all whitespace and navigation retain ownership."""
        pieces = []

        def visit(index):
            node = self.nodes[index]
            size = len(self.text[node.start : node.end].encode())
            if node.tag in NAVIGATION or (
                node.tag not in CONTAINERS and size <= UNIT_BYTES
            ):
                pieces.append((node.start, node.end, index))
                return
            if self.children[index]:
                pieces.extend((a, b, index) for a, b in self.direct[index])
                for child in self.children[index]:
                    visit(child)
                return
            # Text-only source with independent sentences has no XML children.
            # Keep complete sentences, never discard the unsplit remainder.
            cursor = node.start
            for match in re.finditer(
                r"(?<=[.!?])\s+|\n+", self.text[node.start : node.end]
            ):
                end = node.start + match.end()
                if end > cursor:
                    pieces.append((cursor, end, index))
                    cursor = end
            if cursor < node.end:
                pieces.append((cursor, node.end, index))

        for root in self.children[None]:
            visit(root)
        cursor = 0
        result = []
        for a, b, index in sorted(pieces):
            if a < cursor:
                raise ValueError("overlapping_context_units")
            if cursor < a:
                result.append((cursor, a, None))
            result.append((a, b, index))
            cursor = b
        if cursor < len(self.text):
            result.append((cursor, len(self.text), None))
        return result

    def required(self, start, end, index):
        """Return the complete source ranges supporting one ownership unit."""
        if index is None:
            return ((start, end),), ()
        identity = (start, end, index)
        if identity in self._required:
            return self._required[identity]
        selected, expanded, pending = set(), set(), []
        unresolved = set()

        def add_range(a, b):
            if a < b and self.text[a:b].strip():
                selected.add((a, b))

        def include(node_index, *, whole=True):
            key = (node_index, whole)
            if key in expanded:
                return
            expanded.add(key)
            node = self.nodes[node_index]
            if node.tag in NAVIGATION:
                return
            if whole:
                add_range(node.start, node.end)
                pending.append(node_index)
                for child in self.children[node_index]:
                    inspect(child)
            else:
                for a, b in self.direct[node_index]:
                    add_range(a, b)
                pending.append(node_index)
            for ancestor in self.ancestors(node_index):
                if self.nodes[ancestor].tag not in NAVIGATION:
                    include(ancestor, whole=False)
            for scope in (node_index, *self.ancestors(node_index)):
                for qualifier in self.qualifications[scope]:
                    include(qualifier)

        def inspect(node_index):
            key = (node_index, "inspect")
            if key in expanded:
                return
            expanded.add(key)
            pending.append(node_index)
            for child in self.children[node_index]:
                if self.nodes[child].tag not in NAVIGATION:
                    inspect(child)

        node = self.nodes[index]
        add_range(start, end)
        if node.tag in NAVIGATION:
            # Navigation has no operative dependency on the thousands of
            # provision numbers it lists. Its own bytes are still reviewed.
            return (), ()
        if (start, end) == (node.start, node.end) and len(
            self.text[node.start : node.end].encode()
        ) <= UNIT_BYTES:
            include(index)
        else:
            # This is a parent's direct introduction/continuation or an
            # unstructured sentence, not ownership of every child provision.
            pending.append(index)
            for ancestor in self.ancestors(index):
                include(ancestor, whole=False)
        for a in (index, *self.ancestors(index), None):
            for qualifier in self.qualifications[a]:
                include(qualifier)
        while pending:
            current = pending.pop()
            unresolved.update(self.unresolved[current])
            for linked in self.links[current] | self.definition_links[current]:
                include(linked)
            for linked in self.introduction_links[current]:
                include(linked, whole=False)
                for table in self.tables_under[linked]:
                    include(table, whole=False)
                    for child in self.children[table]:
                        if self.nodes[child].tag in {"thead", "tgroup"}:
                            include(child, whole=self.nodes[child].tag == "thead")
                            for header in self.children[child]:
                                if self.nodes[header].tag == "thead":
                                    include(header)
            if self.nodes[current].tag == "table":
                for authorizer in self.table_authorizations[current]:
                    include(authorizer)
        merged = []
        for a, b in sorted(selected):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        result = tuple(merged), tuple(sorted(unresolved))
        self._required[identity] = result
        return result
